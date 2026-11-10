from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from solana_meme_paper_trader.config import load_settings
from solana_meme_paper_trader.ledger import Ledger, LedgerError
from solana_meme_paper_trader.models import Quote
from solana_meme_paper_trader.paper import PaperBroker, PaperTradeError

ROOT = Path(__file__).resolve().parents[1]
MINT = "TokenMint111111111111111111111111111111111"


class PaperBrokerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        base = load_settings(ROOT / "config.example.toml")
        self.now = datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc)
        self.settings = replace(
            base,
            state_path=Path(self.tmp.name) / "ledger.sqlite3",
            starting_cash_usd=Decimal("1000"),
            max_trade_usd=Decimal("150"),
            max_position_usd=Decimal("200"),
            max_quote_age_seconds=15,
            fee_bps=100,
            slippage_bps=100,
        )
        self.ledger = Ledger(self.settings.state_path, self.settings.starting_cash_usd)
        self.broker = PaperBroker(self.settings, self.ledger)

    def tearDown(self):
        self.tmp.cleanup()

    def quote(self, price="1", seconds_old=3):
        return Quote(MINT, Decimal(price), self.now - timedelta(seconds=seconds_old), "test feed")

    def test_buy_accounts_for_fee_and_buy_slippage(self):
        fill = self.broker.buy(MINT, Decimal("100"), self.quote(), self.now)
        self.assertEqual(fill.side, "buy")
        self.assertEqual(fill.fee_usd, Decimal("1"))
        self.assertEqual(fill.fill_price_usd, Decimal("1.01"))
        self.assertEqual(fill.gross_usd, Decimal("99"))
        self.assertEqual(self.ledger.cash(), Decimal("900"))
        position = self.ledger.position(MINT)
        self.assertIsNotNone(position)
        self.assertEqual(position["cost_usd"], Decimal("100"))
        self.assertGreater(position["quantity"], Decimal("98"))
        self.assertEqual(self.ledger.totals()["fees_usd"], Decimal("1"))

    def test_sell_accounts_for_fee_slippage_and_realized_pnl(self):
        bought = self.broker.buy(MINT, Decimal("100"), self.quote(), self.now)
        sell_amount = bought.token_amount / 2
        fill = self.broker.sell(MINT, sell_amount, self.quote("1.1"), self.now)
        self.assertEqual(fill.side, "sell")
        self.assertLess(fill.fill_price_usd, Decimal("1.1"))
        self.assertGreater(fill.fee_usd, Decimal("0"))
        self.assertGreater(fill.cash_delta_usd, Decimal("0"))
        self.assertIsNotNone(self.ledger.position(MINT))
        self.assertEqual(self.ledger.fill_count(), 2)
        self.assertEqual(self.ledger.totals()["realized_pnl_usd"], fill.realized_pnl_usd)

    def test_stale_quote_is_rejected(self):
        with self.assertRaisesRegex(PaperTradeError, "stale"):
            self.broker.buy(MINT, Decimal("10"), self.quote(seconds_old=16), self.now)
        self.assertEqual(self.ledger.cash(), Decimal("1000"))

    def test_quote_for_different_mint_is_rejected(self):
        quote = Quote("DifferentMint", Decimal("1"), self.now, "test")
        with self.assertRaisesRegex(PaperTradeError, "does not match"):
            self.broker.buy(MINT, Decimal("10"), quote, self.now)

    def test_trade_and_position_limits_are_enforced(self):
        with self.assertRaisesRegex(PaperTradeError, "max_trade_usd"):
            self.broker.buy(MINT, Decimal("151"), self.quote(), self.now)
        self.broker.buy(MINT, Decimal("100"), self.quote(), self.now)
        with self.assertRaisesRegex(PaperTradeError, "max_position_usd"):
            self.broker.buy(MINT, Decimal("101"), self.quote(), self.now)

    def test_over_sell_does_not_change_ledger(self):
        self.broker.buy(MINT, Decimal("20"), self.quote(), self.now)
        before = self.ledger.cash()
        with self.assertRaises(LedgerError):
            self.broker.sell(MINT, Decimal("999999"), self.quote(), self.now)
        self.assertEqual(before, self.ledger.cash())


if __name__ == "__main__":
    unittest.main()
