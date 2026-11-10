from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from .config import Settings
from .ledger import Ledger
from .models import PaperFill, Quote, utc_now


class PaperTradeError(ValueError):
    pass


def ensure_fresh_quote(quote: Quote, mint: str, settings: Settings, now: datetime) -> None:
    if quote.mint != mint:
        raise PaperTradeError("quote mint does not match requested mint")
    if now.tzinfo is None or now.utcoffset() is None:
        raise PaperTradeError("current time must be timezone-aware")
    age = (now.astimezone(quote.as_of.tzinfo) - quote.as_of).total_seconds()
    if age < -1:
        raise PaperTradeError("quote timestamp is in the future")
    if age > settings.max_quote_age_seconds:
        raise PaperTradeError(f"quote is stale ({age:.1f}s old; limit {settings.max_quote_age_seconds}s)")


class PaperBroker:
    def __init__(self, settings: Settings, ledger: Ledger):
        self.settings = settings
        self.ledger = ledger

    def buy(self, mint: str, usd_budget: Decimal, quote: Quote, now: datetime | None = None) -> PaperFill:
        current = now or utc_now()
        ensure_fresh_quote(quote, mint, self.settings, current)
        budget = Decimal(usd_budget)
        if not budget.is_finite() or budget <= 0:
            raise PaperTradeError("buy budget must be a positive finite USD amount")
        if budget > self.settings.max_trade_usd:
            raise PaperTradeError(f"buy exceeds max_trade_usd (${self.settings.max_trade_usd})")
        old_position = self.ledger.position(mint)
        old_cost = old_position["cost_usd"] if old_position else Decimal("0")
        if old_cost + budget > self.settings.max_position_usd:
            raise PaperTradeError(f"buy would exceed max_position_usd (${self.settings.max_position_usd})")

        fee = budget * Decimal(self.settings.fee_bps) / Decimal(10_000)
        gross = budget - fee
        fill_price = quote.price_usd * (Decimal(1) + Decimal(self.settings.slippage_bps) / Decimal(10_000))
        token_amount = gross / fill_price
        if token_amount <= 0:
            raise PaperTradeError("simulated token amount is not positive")
        timestamp = current.isoformat()
        fill_id = str(uuid.uuid4())
        self.ledger.apply_buy(
            fill_id=fill_id,
            timestamp=timestamp,
            mint=mint,
            token_amount=token_amount,
            fill_price_usd=fill_price,
            gross_usd=gross,
            fee_usd=fee,
            cash_spend_usd=budget,
            quote_time=quote.as_of.isoformat(),
            quote_source=quote.source,
            modeled_latency_ms=self.settings.modeled_latency_ms,
        )
        return PaperFill(fill_id, current, "buy", mint, token_amount, fill_price, gross, fee, -budget,
                         Decimal("0"), quote.as_of, quote.source, self.settings.modeled_latency_ms)

    def sell(self, mint: str, token_amount: Decimal, quote: Quote, now: datetime | None = None) -> PaperFill:
        current = now or utc_now()
        ensure_fresh_quote(quote, mint, self.settings, current)
        amount = Decimal(token_amount)
        if not amount.is_finite() or amount <= 0:
            raise PaperTradeError("sell amount must be a positive finite token quantity")
        fill_price = quote.price_usd * (Decimal(1) - Decimal(self.settings.slippage_bps) / Decimal(10_000))
        gross = amount * fill_price
        fee = gross * Decimal(self.settings.fee_bps) / Decimal(10_000)
        proceeds = gross - fee
        fill_id = str(uuid.uuid4())
        realized = self.ledger.apply_sell(
            fill_id=fill_id,
            timestamp=current.isoformat(),
            mint=mint,
            token_amount=amount,
            fill_price_usd=fill_price,
            gross_usd=gross,
            fee_usd=fee,
            net_proceeds_usd=proceeds,
            quote_time=quote.as_of.isoformat(),
            quote_source=quote.source,
            modeled_latency_ms=self.settings.modeled_latency_ms,
        )
        return PaperFill(fill_id, current, "sell", mint, amount, fill_price, gross, fee, proceeds, realized,
                         quote.as_of, quote.source, self.settings.modeled_latency_ms)
