from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import decimal_value


class LedgerError(RuntimeError):
    pass


class Ledger:
    """Single-process local ledger. It stores paper-trade records only."""

    def __init__(self, path: str | Path, starting_cash_usd: Decimal):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS positions (
                    mint TEXT PRIMARY KEY,
                    quantity TEXT NOT NULL,
                    cost_usd TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fills (
                    fill_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    side TEXT NOT NULL,
                    mint TEXT NOT NULL,
                    token_amount TEXT NOT NULL,
                    fill_price_usd TEXT NOT NULL,
                    gross_usd TEXT NOT NULL,
                    fee_usd TEXT NOT NULL,
                    cash_delta_usd TEXT NOT NULL,
                    realized_pnl_usd TEXT NOT NULL,
                    quote_time TEXT NOT NULL,
                    quote_source TEXT NOT NULL,
                    modeled_latency_ms INTEGER NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('cash_usd', ?)",
                (str(starting_cash_usd),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('starting_cash_usd', ?)",
                (str(starting_cash_usd),),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def cash(self) -> Decimal:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM meta WHERE key='cash_usd'").fetchone()
        return decimal_value(row["value"], field="cash_usd")

    def position(self, mint: str) -> dict[str, Decimal] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT quantity, cost_usd FROM positions WHERE mint=?", (mint,)).fetchone()
        if row is None:
            return None
        return {"quantity": decimal_value(row["quantity"]), "cost_usd": decimal_value(row["cost_usd"])}

    def positions(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT mint, quantity, cost_usd FROM positions ORDER BY mint").fetchall()
        return [
            {"mint": row["mint"], "quantity": decimal_value(row["quantity"]), "cost_usd": decimal_value(row["cost_usd"])}
            for row in rows
        ]

    def apply_buy(
        self,
        *,
        fill_id: str,
        timestamp: str,
        mint: str,
        token_amount: Decimal,
        fill_price_usd: Decimal,
        gross_usd: Decimal,
        fee_usd: Decimal,
        cash_spend_usd: Decimal,
        quote_time: str,
        quote_source: str,
        modeled_latency_ms: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cash = decimal_value(connection.execute("SELECT value FROM meta WHERE key='cash_usd'").fetchone()["value"])
                if cash_spend_usd > cash:
                    raise LedgerError(f"insufficient paper cash: need ${cash_spend_usd}, have ${cash}")
                row = connection.execute("SELECT quantity, cost_usd FROM positions WHERE mint=?", (mint,)).fetchone()
                old_qty = Decimal("0") if row is None else decimal_value(row["quantity"])
                old_cost = Decimal("0") if row is None else decimal_value(row["cost_usd"])
                new_qty = old_qty + token_amount
                new_cost = old_cost + cash_spend_usd
                connection.execute(
                    "INSERT INTO positions(mint, quantity, cost_usd) VALUES(?, ?, ?) "
                    "ON CONFLICT(mint) DO UPDATE SET quantity=excluded.quantity, cost_usd=excluded.cost_usd",
                    (mint, str(new_qty), str(new_cost)),
                )
                connection.execute("UPDATE meta SET value=? WHERE key='cash_usd'", (str(cash - cash_spend_usd),))
                connection.execute(
                    "INSERT INTO fills VALUES(?, ?, 'buy', ?, ?, ?, ?, ?, ?, '0', ?, ?, ?)",
                    (fill_id, timestamp, mint, str(token_amount), str(fill_price_usd), str(gross_usd), str(fee_usd),
                     str(-cash_spend_usd), quote_time, quote_source, modeled_latency_ms),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def apply_sell(
        self,
        *,
        fill_id: str,
        timestamp: str,
        mint: str,
        token_amount: Decimal,
        fill_price_usd: Decimal,
        gross_usd: Decimal,
        fee_usd: Decimal,
        net_proceeds_usd: Decimal,
        quote_time: str,
        quote_source: str,
        modeled_latency_ms: int,
    ) -> Decimal:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute("SELECT quantity, cost_usd FROM positions WHERE mint=?", (mint,)).fetchone()
                if row is None:
                    raise LedgerError(f"no paper position exists for {mint}")
                old_qty = decimal_value(row["quantity"])
                old_cost = decimal_value(row["cost_usd"])
                if token_amount > old_qty:
                    raise LedgerError(f"insufficient token balance: requested {token_amount}, have {old_qty}")
                removed_cost = old_cost * token_amount / old_qty
                realized = net_proceeds_usd - removed_cost
                remaining_qty = old_qty - token_amount
                remaining_cost = old_cost - removed_cost
                if remaining_qty == 0:
                    connection.execute("DELETE FROM positions WHERE mint=?", (mint,))
                else:
                    connection.execute(
                        "UPDATE positions SET quantity=?, cost_usd=? WHERE mint=?",
                        (str(remaining_qty), str(remaining_cost), mint),
                    )
                cash = decimal_value(connection.execute("SELECT value FROM meta WHERE key='cash_usd'").fetchone()["value"])
                connection.execute("UPDATE meta SET value=? WHERE key='cash_usd'", (str(cash + net_proceeds_usd),))
                connection.execute(
                    "INSERT INTO fills VALUES(?, ?, 'sell', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (fill_id, timestamp, mint, str(token_amount), str(fill_price_usd), str(gross_usd), str(fee_usd),
                     str(net_proceeds_usd), str(realized), quote_time, quote_source, modeled_latency_ms),
                )
                connection.commit()
                return realized
            except Exception:
                connection.rollback()
                raise

    def totals(self) -> dict[str, Decimal]:
        with self._connect() as connection:
            rows = connection.execute("SELECT fee_usd, realized_pnl_usd FROM fills").fetchall()
        return {
            "fees_usd": sum((decimal_value(row["fee_usd"]) for row in rows), Decimal("0")),
            "realized_pnl_usd": sum((decimal_value(row["realized_pnl_usd"]) for row in rows), Decimal("0")),
        }

    def fill_count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0])
