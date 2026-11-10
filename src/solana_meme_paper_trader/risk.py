from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .models import RiskEvidence, utc_now


@dataclass(frozen=True)
class RiskPolicy:
    min_liquidity_usd: Decimal
    max_top_holder_pct: Decimal
    max_age_seconds: int

    def check(self, evidence: RiskEvidence, expected_mint: str, now: datetime | None = None) -> list[str]:
        current = now or utc_now()
        reasons: list[str] = []
        if evidence.mint != expected_mint:
            reasons.append("risk report mint does not match the requested token")
        age = (current - evidence.fetched_at).total_seconds()
        if age < -1:
            reasons.append("risk report timestamp is in the future")
        elif age > self.max_age_seconds:
            reasons.append("risk report is stale")
        if evidence.liquidity_usd is None:
            reasons.append("liquidity evidence is missing")
        elif evidence.liquidity_usd < self.min_liquidity_usd:
            reasons.append(f"liquidity is below the configured minimum (${self.min_liquidity_usd})")
        if evidence.top_holder_pct is None:
            reasons.append("top-holder concentration evidence is missing")
        elif evidence.top_holder_pct > self.max_top_holder_pct:
            reasons.append(f"top-holder concentration exceeds {self.max_top_holder_pct}%")
        if evidence.mint_authority_active is None:
            reasons.append("mint-authority status is unknown")
        elif evidence.mint_authority_active:
            reasons.append("mint authority is active")
        if evidence.freeze_authority_active is None:
            reasons.append("freeze-authority status is unknown")
        elif evidence.freeze_authority_active:
            reasons.append("freeze authority is active")
        if evidence.risk_flags:
            reasons.append("risk flags present: " + ", ".join(evidence.risk_flags))
        return reasons

    def require_clear(self, evidence: RiskEvidence, expected_mint: str, now: datetime | None = None) -> None:
        reasons = self.check(evidence, expected_mint, now)
        if reasons:
            raise ValueError("paper entry blocked by risk gate: " + "; ".join(reasons))
