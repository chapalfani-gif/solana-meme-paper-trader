from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import unittest

from solana_meme_paper_trader.bitquery import BitqueryClient, METEORA_DBC, PUMPFUN, parse_launches


class FixtureBitqueryClient(BitqueryClient):
    def __init__(self, response):
        super().__init__(api_key="unit-test-key")
        self.response = response

    def execute(self, query, variables=None):
        return self.response


class AdapterTests(unittest.TestCase):
    def test_parse_pump_fun_mint(self):
        rows = [{
            "Instruction": {
                "Accounts": [{"Address": "account", "Token": {"Mint": "Mint111"}}],
                "Program": {"Address": PUMPFUN, "Method": "create_v2"},
            },
            "Block": {"Time": "2026-11-11T00:00:00Z"},
            "Transaction": {"Signature": "sig-1"},
        }]
        events = parse_launches(rows)
        self.assertEqual(events[0].mint, "Mint111")
        self.assertEqual(events[0].launchpad, "Pump.fun")
        self.assertEqual(events[0].signature, "sig-1")

    def test_ambiguous_mint_is_not_guessed(self):
        rows = [{
            "Instruction": {
                "Accounts": [{"Token": {"Mint": "MintA"}}, {"Token": {"Mint": "MintB"}}],
                "Program": {"Address": METEORA_DBC, "Method": "initialize_virtual_pool_with_spl_token"},
            }
        }]
        event = parse_launches(rows)[0]
        self.assertIsNone(event.mint)
        self.assertEqual(event.launchpad, "Meteora DBC")

    def test_quote_parses_usd_price_timestamp_and_signature(self):
        response = {"Solana": {"DEXTradeByTokens": [{
            "Block": {"Time": "2026-11-11T00:00:00Z"},
            "Transaction": {"Signature": "sig-2"},
            "Trade": {"PriceInUSD": "0.00125", "Currency": {"MintAddress": "Mint111", "Symbol": "TEST"}},
        }]}}
        client = FixtureBitqueryClient(response)
        query_file = Path(__file__).resolve().parents[1] / "queries" / "latest_usd_quote.graphql"
        quote = client.latest_usd_quote("Mint111", query_file)
        self.assertEqual(quote.price_usd, Decimal("0.00125"))
        self.assertEqual(quote.signature, "sig-2")
        self.assertEqual(quote.as_of, datetime(2026, 11, 11, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
