from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from solana_meme_paper_trader.models import RiskEvidence
from solana_meme_paper_trader.risk import RiskPolicy
from solana_meme_paper_trader.rugcheck import normalize_report

MINT = "TokenMint111111111111111111111111111111111"
NOW = datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc)
POLICY = RiskPolicy(Decimal("5000"), Decimal("20"), 3600)


class RiskGateTests(unittest.TestCase):
    def evidence(self, **overrides):
        data = {
            "mint": MINT,
            "fetched_at": (NOW - timedelta(minutes=5)).isoformat(),
            "provider": "test",
            "liquidity_usd": "10000",
            "top_holder_pct": "10",
            "mint_authority_active": False,
            "freeze_authority_active": False,
            "risk_flags": [],
        }
        data.update(overrides)
        return RiskEvidence.from_dict(data)

    def test_clear_evidence_passes(self):
        self.assertEqual(POLICY.check(self.evidence(), MINT, NOW), [])

    def test_missing_or_unsafe_evidence_fails_closed(self):
        evidence = RiskEvidence.from_dict({"mint": MINT, "fetched_at": NOW.isoformat()})
        reasons = POLICY.check(evidence, MINT, NOW)
        self.assertTrue(any("missing" in reason for reason in reasons))
        self.assertGreaterEqual(len(reasons), 4)

    def test_thresholds_flags_staleness_and_mint_are_enforced(self):
        evidence = self.evidence(
            mint="OtherMint",
            fetched_at=(NOW - timedelta(hours=2)).isoformat(),
            liquidity_usd="100",
            top_holder_pct="35",
            mint_authority_active=True,
            risk_flags=["suspicious concentration"],
        )
        reasons = POLICY.check(evidence, MINT, NOW)
        self.assertTrue(any("does not match" in reason for reason in reasons))
        self.assertTrue(any("stale" in reason for reason in reasons))
        self.assertTrue(any("liquidity" in reason for reason in reasons))
        self.assertTrue(any("concentration" in reason for reason in reasons))
        self.assertTrue(any("mint authority" in reason for reason in reasons))
        self.assertTrue(any("risk flags" in reason for reason in reasons))

    def test_rugcheck_mapping_is_explicit_and_unknowns_remain_unknown(self):
        raw = {"markets": [{"liquidity": {"usd": 12500}}], "token": {"freezeAuthority": None}}
        evidence = normalize_report(raw, MINT, {
            "liquidity_usd": "markets.0.liquidity.usd",
            "freeze_authority_active": "token.freezeAuthorityActive",
        }, fetched_at=NOW)
        self.assertEqual(evidence.liquidity_usd, Decimal("12500"))
        self.assertIsNone(evidence.freeze_authority_active)
        self.assertIsNone(evidence.top_holder_pct)

    def test_authority_fields_must_be_boolean_or_null(self):
        with self.assertRaisesRegex(ValueError, "must be true, false, or null"):
            RiskEvidence.from_dict({"mint": MINT, "fetched_at": NOW.isoformat(), "mint_authority_active": "false"})


if __name__ == "__main__":
    unittest.main()
