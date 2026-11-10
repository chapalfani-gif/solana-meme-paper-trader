from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from .config import Settings
from .models import Quote, TradeProposal, utc_now
from .paper import ensure_fresh_quote


class ProposalError(ValueError):
    pass


def create_proposal(
    settings: Settings,
    mint: str,
    side: str,
    amount: Decimal,
    quote: Quote,
    now: datetime | None = None,
) -> TradeProposal:
    if not settings.live_proposals_enabled:
        raise ProposalError("proposal mode is disabled; set [live].proposals_enabled=true after reviewing the non-executable scope")
    current = now or utc_now()
    ensure_fresh_quote(quote, mint, settings, current)
    side = side.lower()
    value = Decimal(amount)
    if side not in {"buy", "sell"}:
        raise ProposalError("side must be buy or sell")
    if not value.is_finite() or value <= 0:
        raise ProposalError("amount must be a positive finite number")
    if side == "buy":
        if value > settings.max_trade_usd:
            raise ProposalError(f"proposal exceeds max_trade_usd (${settings.max_trade_usd})")
        amount_unit = "USD budget (fee included)"
        notional = value
    else:
        amount_unit = "token quantity"
        notional = value * quote.price_usd
        if notional > settings.max_trade_usd:
            raise ProposalError(f"proposal notional exceeds max_trade_usd (${settings.max_trade_usd})")
    fee = notional * Decimal(settings.fee_bps) / Decimal(10_000)
    expires = quote.as_of + timedelta(seconds=settings.max_quote_age_seconds)
    if expires <= current:
        raise ProposalError("quote is too old to produce a reviewable proposal")
    return TradeProposal(
        proposal_id=str(uuid.uuid4()),
        created_at=current,
        expires_at=expires,
        mint=mint,
        side=side,
        amount=value,
        amount_unit=amount_unit,
        reference_price_usd=quote.price_usd,
        max_slippage_bps=settings.slippage_bps,
        estimated_fee_usd=fee,
        quote_source=quote.source,
        quote_time=quote.as_of,
    )
