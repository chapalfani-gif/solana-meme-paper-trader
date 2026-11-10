from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import unittest

from solana_meme_paper_trader.config import load_settings
from solana_meme_paper_trader.models import Quote
from solana_meme_paper_trader.proposal import ProposalError, create_proposal

ROOT = Path(__file__).resolve().parents[1]
MINT = "TokenMint111111111111111111111111111111111"
NOW = datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc)


class ProposalTests(unittest.TestCase):
    def setUp(self):
        base = load_settings(ROOT / "config.example.toml")
        self.settings = replace(base, live_proposals_enabled=True)
        self.quote = Quote(MINT, Decimal("0.25"), NOW - timedelta(seconds=2), "fixture")

    def test_proposal_is_non_executable_and_expires(self):
        proposal = create_proposal(self.settings, MINT, "buy", Decimal("20"), self.quote, NOW)
        data = proposal.to_dict()
        self.assertFalse(data["executable_onchain"])
        self.assertFalse(data["submitted"])
        self.assertEqual(data["amount_unit"], "USD budget (fee included)")
        self.assertLessEqual(proposal.expires_at, NOW + timedelta(seconds=self.settings.max_quote_age_seconds))

    def test_proposal_mode_is_disabled_by_default(self):
        settings = replace(self.settings, live_proposals_enabled=False)
        with self.assertRaisesRegex(ProposalError, "disabled"):
            create_proposal(settings, MINT, "buy", Decimal("20"), self.quote, NOW)

    def test_stale_quote_is_not_proposed(self):
        stale = Quote(MINT, Decimal("0.25"), NOW - timedelta(seconds=20), "fixture")
        with self.assertRaisesRegex(ValueError, "stale"):
            create_proposal(self.settings, MINT, "buy", Decimal("20"), stale, NOW)


if __name__ == "__main__":
    unittest.main()
