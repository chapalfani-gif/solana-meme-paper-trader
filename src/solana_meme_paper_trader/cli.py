from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .bitquery import AdapterError, BitqueryClient
from .config import Settings, load_settings
from .ledger import Ledger, LedgerError
from .models import Quote, RiskEvidence, parse_datetime, utc_now
from .paper import PaperBroker, ensure_fresh_quote
from .proposal import create_proposal
from .risk import RiskPolicy
from .rugcheck import RugCheckAdapter, normalize_report


def _settings(path: str) -> Settings:
    return load_settings(path)


def _bitquery(settings: Settings) -> BitqueryClient:
    return BitqueryClient(endpoint=settings.bitquery_url)


def _quote(client: BitqueryClient, settings: Settings, mint: str) -> Quote:
    query_path = settings.config_path.parent / "queries" / "latest_usd_quote.graphql"
    if not query_path.exists():
        query_path = Path(__file__).resolve().parents[2] / "queries" / "latest_usd_quote.graphql"
    return client.latest_usd_quote(mint, query_path)


def _ledger(settings: Settings) -> Ledger:
    return Ledger(settings.state_path, settings.starting_cash_usd)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _fill_dict(fill: Any) -> dict[str, Any]:
    return {
        "fill_id": fill.fill_id,
        "timestamp": fill.timestamp.isoformat(),
        "mode": "paper",
        "side": fill.side,
        "mint": fill.mint,
        "token_amount": str(fill.token_amount),
        "fill_price_usd": str(fill.fill_price_usd),
        "gross_usd": str(fill.gross_usd),
        "fee_usd": str(fill.fee_usd),
        "cash_delta_usd": str(fill.cash_delta_usd),
        "realized_pnl_usd": str(fill.realized_pnl_usd),
        "quote_time": fill.quote_time.isoformat(),
        "quote_source": fill.quote_source,
        "modeled_latency_ms": fill.modeled_latency_ms,
        "submitted_on_chain": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smp", description="Read-only Solana data and paper trading; no live order execution")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("config-check", help="validate configuration")
    check.add_argument("--config", default="config.toml")

    discover = sub.add_parser("discover", help="query recent launchpad instruction events")
    discover.add_argument("--config", default="config.toml")
    discover.add_argument("--query-file")

    quote = sub.add_parser("quote", help="fetch the latest USD trade quote")
    quote.add_argument("--config", default="config.toml")
    quote.add_argument("--mint", required=True)

    risk = sub.add_parser("risk-fetch", help="fetch a RugCheck report; no paid refresh is requested")
    risk.add_argument("--config", default="config.toml")
    risk.add_argument("--mint", required=True)
    risk.add_argument("--out")
    risk.add_argument("--normalized-out", help="optional output requiring explicit risk.field_map configuration")

    paper = sub.add_parser("paper", help="paper-only ledger actions")
    paper_sub = paper.add_subparsers(dest="paper_command", required=True)
    status = paper_sub.add_parser("status", help="show local cash, positions, fees and realized P/L")
    status.add_argument("--config", default="config.toml")
    status.add_argument("--mark", action="store_true", help="read fresh Bitquery prices for ephemeral unrealized P/L")
    buy = paper_sub.add_parser("buy", help="simulate a buy using a fresh Bitquery quote")
    buy.add_argument("--config", default="config.toml")
    buy.add_argument("--mint", required=True)
    buy.add_argument("--usd", required=True, type=Decimal, help="total cash budget including modeled fee")
    buy.add_argument("--risk-file", required=True, help="normalized RiskEvidence JSON; unknown risk blocks entry")
    sell = paper_sub.add_parser("sell", help="simulate a sell using a fresh Bitquery quote")
    sell.add_argument("--config", default="config.toml")
    sell.add_argument("--mint", required=True)
    sell.add_argument("--quantity", required=True, type=Decimal)

    proposal = sub.add_parser("proposal", help="create a non-executable live trade intent for manual review")
    proposal_sub = proposal.add_subparsers(dest="proposal_command", required=True)
    create = proposal_sub.add_parser("create")
    create.add_argument("--config", default="config.toml")
    create.add_argument("--mint", required=True)
    create.add_argument("--side", choices=("buy", "sell"), required=True)
    create.add_argument("--amount", required=True, type=Decimal, help="USD budget for buy; token quantity for sell")
    create.add_argument("--confirm-proposal-only", action="store_true", help="acknowledge this creates no transaction and sends nothing")
    create.add_argument("--out", help="proposal JSON path; default is state/proposals/<id>.json")
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "config-check":
        settings = _settings(args.config)
        print(json.dumps({"valid": True, "mode": "paper", "live_execution_enabled": settings.live_execution_enabled,
                          "live_proposals_enabled": settings.live_proposals_enabled,
                          "state_path": str(settings.state_path)}, indent=2))
        return 0

    if args.command == "discover":
        settings = _settings(args.config)
        query_file = Path(args.query_file).resolve() if args.query_file else settings.launch_query_path
        events = _bitquery(settings).fetch_launches(query_file)
        print(json.dumps([{
            "mint": event.mint,
            "launchpad": event.launchpad,
            "program_id": event.program_id,
            "method": event.method,
            "block_time": event.block_time.isoformat() if event.block_time else None,
            "signature": event.signature,
            "tradeable_mint_decoded": event.mint is not None,
        } for event in events], indent=2))
        return 0

    if args.command == "quote":
        settings = _settings(args.config)
        quote = _quote(_bitquery(settings), settings, args.mint)
        print(json.dumps({"mint": quote.mint, "price_usd": str(quote.price_usd), "as_of": quote.as_of.isoformat(),
                          "source": quote.source, "signature": quote.signature}, indent=2))
        return 0

    if args.command == "risk-fetch":
        settings = _settings(args.config)
        raw = RugCheckAdapter(settings.rugcheck_base_url).fetch_report(args.mint)
        output = Path(args.out) if args.out else settings.state_path.parent / "risk-raw" / f"{args.mint}.json"
        _write_json(output, {"mint": args.mint, "fetched_at": utc_now().isoformat(), "provider": "RugCheck", "raw_report": raw})
        result: dict[str, Any] = {"raw_report_saved": str(output), "normalized": False}
        if args.normalized_out:
            evidence = normalize_report(raw, args.mint, settings.rugcheck_field_map)
            normalized_path = Path(args.normalized_out)
            _write_json(normalized_path, evidence.to_dict())
            result.update({"normalized": True, "normalized_evidence_saved": str(normalized_path),
                           "note": "Unmapped fields remain unknown and block paper entry."})
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "paper":
        settings = _settings(args.config)
        ledger = _ledger(settings)
        if args.paper_command == "status":
            totals = ledger.totals()
            positions = ledger.positions()
            marked_positions: list[dict[str, Any]] = []
            unrealized_pnl = Decimal("0")
            all_positions_marked = True
            client = _bitquery(settings) if args.mark and positions else None
            for row in positions:
                item = {"mint": row["mint"], "quantity": str(row["quantity"]), "cost_usd": str(row["cost_usd"])}
                if client is not None:
                    try:
                        quote = _quote(client, settings, row["mint"])
                        ensure_fresh_quote(quote, row["mint"], settings, utc_now())
                        market_value = row["quantity"] * quote.price_usd
                        pnl = market_value - row["cost_usd"]
                        item.update({"mark_price_usd": str(quote.price_usd), "mark_time": quote.as_of.isoformat(),
                                     "market_value_usd": str(market_value), "unrealized_pnl_usd": str(pnl)})
                        unrealized_pnl += pnl
                    except (AdapterError, ValueError) as exc:
                        item["mark_error"] = str(exc)
                        all_positions_marked = False
                marked_positions.append(item)
            print(json.dumps({
                "mode": "paper",
                "cash_usd": str(ledger.cash()),
                "positions": marked_positions,
                "realized_pnl_usd": str(totals["realized_pnl_usd"]),
                "unrealized_pnl_usd": str(unrealized_pnl) if args.mark and all_positions_marked else None,
                "mark_to_market": "fresh Bitquery trade quotes; ephemeral only" if args.mark else "not requested",
                "fees_usd": str(totals["fees_usd"]),
                "fill_count": ledger.fill_count(),
            }, indent=2))
            return 0
        client = _bitquery(settings)
        quote = _quote(client, settings, args.mint)
        broker = PaperBroker(settings, ledger)
        if args.paper_command == "buy":
            raw = json.loads(Path(args.risk_file).read_text(encoding="utf-8"))
            evidence = RiskEvidence.from_dict(raw)
            policy = RiskPolicy(settings.min_liquidity_usd, settings.max_top_holder_pct, settings.max_risk_age_seconds)
            policy.require_clear(evidence, args.mint)
            fill = broker.buy(args.mint, args.usd, quote)
        else:
            fill = broker.sell(args.mint, args.quantity, quote)
        print(json.dumps(_fill_dict(fill), indent=2))
        return 0

    if args.command == "proposal" and args.proposal_command == "create":
        if not args.confirm_proposal_only:
            raise ValueError("pass --confirm-proposal-only to acknowledge no transaction will be created or sent")
        settings = _settings(args.config)
        quote = _quote(_bitquery(settings), settings, args.mint)
        intent = create_proposal(settings, args.mint, args.side, args.amount, quote)
        output = Path(args.out) if args.out else settings.state_path.parent / "proposals" / f"{intent.proposal_id}.json"
        _write_json(output, intent.to_dict())
        print(json.dumps({"proposal_saved": str(output), **intent.to_dict()}, indent=2))
        return 0

    raise ValueError("unsupported command")


def main() -> None:
    args = _parser().parse_args()
    try:
        exit_code = _run(args)
    except (ValueError, OSError, json.JSONDecodeError, AdapterError, LedgerError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        exit_code = 2
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
