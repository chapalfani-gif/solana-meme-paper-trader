from __future__ import annotations

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import decimal_value


@dataclass(frozen=True)
class Settings:
    config_path: Path
    state_path: Path
    bitquery_url: str
    launch_query_path: Path
    starting_cash_usd: Decimal
    fee_bps: int
    slippage_bps: int
    modeled_latency_ms: int
    max_quote_age_seconds: int
    max_trade_usd: Decimal
    max_position_usd: Decimal
    min_liquidity_usd: Decimal
    max_top_holder_pct: Decimal
    max_risk_age_seconds: int
    rugcheck_base_url: str
    rugcheck_field_map: dict[str, str]
    live_proposals_enabled: bool
    live_execution_enabled: bool

    def validate(self) -> None:
        if self.starting_cash_usd <= 0:
            raise ValueError("starting_cash_usd must be positive")
        if self.fee_bps < 0 or self.fee_bps >= 10_000:
            raise ValueError("fee_bps must be between 0 and 9999")
        if self.slippage_bps < 0 or self.slippage_bps >= 10_000:
            raise ValueError("slippage_bps must be between 0 and 9999")
        if self.modeled_latency_ms < 0:
            raise ValueError("modeled_latency_ms cannot be negative")
        if self.max_quote_age_seconds <= 0 or self.max_risk_age_seconds <= 0:
            raise ValueError("quote and risk age limits must be positive")
        if self.max_trade_usd <= 0 or self.max_position_usd <= 0:
            raise ValueError("trade and position limits must be positive")
        if self.min_liquidity_usd < 0:
            raise ValueError("min_liquidity_usd cannot be negative")
        if self.max_top_holder_pct < 0 or self.max_top_holder_pct > 100:
            raise ValueError("max_top_holder_pct must be within 0..100")
        if self.live_execution_enabled:
            raise ValueError("live execution is not implemented and must remain false")
        if not self.bitquery_url.startswith("https://"):
            raise ValueError("bitquery endpoint must use HTTPS")
        if not self.rugcheck_base_url.startswith("https://"):
            raise ValueError("RugCheck endpoint must use HTTPS")


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"[{name}] must be a TOML table")
    return value


def load_settings(path: str | Path) -> Settings:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    app = _table(raw, "app")
    bitquery = _table(raw, "bitquery")
    paper = _table(raw, "paper")
    risk = _table(raw, "risk")
    live = _table(raw, "live")
    if app.get("mode", "paper") != "paper":
        raise ValueError("only app.mode='paper' is supported")

    def project_path(value: str) -> Path:
        candidate = Path(value).expanduser()
        return candidate.resolve() if candidate.is_absolute() else (config_path.parent / candidate).resolve()

    settings = Settings(
        config_path=config_path,
        state_path=project_path(str(app.get("state_path", "state/ledger.sqlite3"))),
        bitquery_url=str(bitquery.get("url", "https://streaming.bitquery.io/graphql")),
        launch_query_path=project_path(str(bitquery.get("launch_query_file", "queries/launches.graphql"))),
        starting_cash_usd=decimal_value(paper.get("starting_cash_usd", "1000"), field="starting_cash_usd"),
        fee_bps=int(paper.get("fee_bps", 100)),
        slippage_bps=int(paper.get("slippage_bps", 100)),
        modeled_latency_ms=int(paper.get("modeled_latency_ms", 750)),
        max_quote_age_seconds=int(paper.get("max_quote_age_seconds", 15)),
        max_trade_usd=decimal_value(paper.get("max_trade_usd", "25"), field="max_trade_usd"),
        max_position_usd=decimal_value(paper.get("max_position_usd", "100"), field="max_position_usd"),
        min_liquidity_usd=decimal_value(risk.get("min_liquidity_usd", "5000"), field="min_liquidity_usd"),
        max_top_holder_pct=decimal_value(risk.get("max_top_holder_pct", "20"), field="max_top_holder_pct"),
        max_risk_age_seconds=int(risk.get("max_age_seconds", 3600)),
        rugcheck_base_url=str(risk.get("rugcheck_base_url", "https://api.rugcheck.xyz")),
        rugcheck_field_map={str(k): str(v) for k, v in _table(risk, "field_map").items()},
        live_proposals_enabled=bool(live.get("proposals_enabled", False)),
        live_execution_enabled=bool(live.get("execution_enabled", False)),
    )
    settings.validate()
    return settings
