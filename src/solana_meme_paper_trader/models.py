from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


def decimal_value(value: Any, *, field: str = "value") -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal number") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        result = datetime.fromisoformat(text)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return result.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Quote:
    mint: str
    price_usd: Decimal
    as_of: datetime
    source: str
    signature: str | None = None

    def __post_init__(self) -> None:
        if not self.mint.strip():
            raise ValueError("mint is required")
        if self.price_usd <= 0:
            raise ValueError("price_usd must be greater than zero")
        object.__setattr__(self, "as_of", parse_datetime(self.as_of))


@dataclass(frozen=True)
class LaunchEvent:
    mint: str | None
    launchpad: str
    program_id: str
    method: str
    block_time: datetime | None
    signature: str | None


@dataclass(frozen=True)
class RiskEvidence:
    mint: str
    fetched_at: datetime
    provider: str
    liquidity_usd: Decimal | None
    top_holder_pct: Decimal | None
    mint_authority_active: bool | None
    freeze_authority_active: bool | None
    risk_flags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RiskEvidence":
        required = ("mint", "fetched_at")
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError("risk evidence missing: " + ", ".join(missing))

        def optional_decimal(name: str) -> Decimal | None:
            value = data.get(name)
            return None if value is None or value == "" else decimal_value(value, field=name)

        for name in ("mint_authority_active", "freeze_authority_active"):
            value = data.get(name)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{name} must be true, false, or null")
        raw_flags = data.get("risk_flags", [])
        if raw_flags is None:
            raw_flags = []
        if not isinstance(raw_flags, list):
            raise ValueError("risk_flags must be a list")
        return cls(
            mint=str(data["mint"]),
            fetched_at=parse_datetime(data["fetched_at"]),
            provider=str(data.get("provider", "manual")),
            liquidity_usd=optional_decimal("liquidity_usd"),
            top_holder_pct=optional_decimal("top_holder_pct"),
            mint_authority_active=data.get("mint_authority_active"),
            freeze_authority_active=data.get("freeze_authority_active"),
            risk_flags=tuple(str(item) for item in raw_flags),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["fetched_at"] = self.fetched_at.isoformat()
        for key in ("liquidity_usd", "top_holder_pct"):
            value = data[key]
            data[key] = None if value is None else str(value)
        data["risk_flags"] = list(self.risk_flags)
        return data


@dataclass(frozen=True)
class PaperFill:
    fill_id: str
    timestamp: datetime
    side: str
    mint: str
    token_amount: Decimal
    fill_price_usd: Decimal
    gross_usd: Decimal
    fee_usd: Decimal
    cash_delta_usd: Decimal
    realized_pnl_usd: Decimal
    quote_time: datetime
    quote_source: str
    modeled_latency_ms: int


@dataclass(frozen=True)
class TradeProposal:
    proposal_id: str
    created_at: datetime
    expires_at: datetime
    mint: str
    side: str
    amount: Decimal
    amount_unit: str
    reference_price_usd: Decimal
    max_slippage_bps: int
    estimated_fee_usd: Decimal
    quote_source: str
    quote_time: datetime
    executable_onchain: bool = False
    submitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "mint": self.mint,
            "side": self.side,
            "amount": str(self.amount),
            "amount_unit": self.amount_unit,
            "reference_price_usd": str(self.reference_price_usd),
            "max_slippage_bps": self.max_slippage_bps,
            "estimated_fee_usd": str(self.estimated_fee_usd),
            "quote_source": self.quote_source,
            "quote_time": self.quote_time.isoformat(),
            "executable_onchain": False,
            "submitted": False,
            "manual_next_step": "Verify the mint and current quote in a trusted wallet/DEX; construct and sign any transaction yourself.",
            "warning": "This is a non-executable trade intent, not a swap transaction or a live order.",
        }
