from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import LaunchEvent, Quote, parse_datetime


class AdapterError(RuntimeError):
    pass


PUMPFUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
RAYDIUM_LAUNCHPAD = "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"
METEORA_DBC = "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN"
HEAVEN = "HEAVENoP2qxoeuF8Dj2oT1GHEnu49U5mJYkdeC8BAX2o"
MOONIT = "MoonCVVNZFSYkqNXP6bxHLPL6QQJiMagDL3qcqUQTrG"
BAGS_PROGRAM = "BAGSB9TpGrZxQbEsrEznv5jXXdwyP6AXerN8aVRiAmcv"


class BitqueryClient:
    """Small synchronous GraphQL client. It never signs or sends Solana transactions."""

    def __init__(self, endpoint: str = "https://streaming.bitquery.io/graphql", api_key: str | None = None, timeout: int = 20):
        self.endpoint = endpoint
        self.api_key = api_key if api_key is not None else os.environ.get("BITQUERY_API_KEY", "")
        self.timeout = timeout

    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise AdapterError("BITQUERY_API_KEY is not set; provide it in the environment, never in a tracked file")
        payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            raise AdapterError(f"Bitquery HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise AdapterError(f"Bitquery request failed: {exc}") from exc
        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AdapterError("Bitquery returned invalid JSON") from exc
        if result.get("errors"):
            messages = "; ".join(str(item.get("message", item)) for item in result["errors"])
            raise AdapterError(f"Bitquery GraphQL error: {messages[:1200]}")
        if not isinstance(result.get("data"), dict):
            raise AdapterError("Bitquery response has no data object")
        return result["data"]

    def fetch_launches(self, query_file: str | Path) -> list[LaunchEvent]:
        query = Path(query_file).read_text(encoding="utf-8")
        data = self.execute(query)
        rows = data.get("Solana", {}).get("Instructions", [])
        return parse_launches(rows)

    def latest_usd_quote(self, mint: str, query_file: str | Path) -> Quote:
        query = Path(query_file).read_text(encoding="utf-8")
        data = self.execute(query, {"token": mint})
        rows = data.get("Solana", {}).get("DEXTradeByTokens", [])
        if not rows:
            raise AdapterError(f"Bitquery returned no USD-priced trades for mint {mint}")
        row = rows[0]
        trade = row.get("Trade") or {}
        block = row.get("Block") or {}
        try:
            price = Decimal(str(trade["PriceInUSD"]))
            as_of = parse_datetime(block["Time"])
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise AdapterError("Bitquery latest-trade row is missing a valid USD price or timestamp") from exc
        if not price.is_finite() or price <= 0:
            raise AdapterError("Bitquery returned a non-positive or non-finite price")
        transaction = row.get("Transaction") or {}
        return Quote(
            mint=mint,
            price_usd=price,
            as_of=as_of,
            source="Bitquery Solana DEXTradeByTokens / PriceInUSD",
            signature=transaction.get("Signature"),
        )


def _launchpad(program_id: str, method: str, accounts: list[dict[str, Any]]) -> str:
    if program_id == PUMPFUN:
        return "Pump.fun"
    if program_id == RAYDIUM_LAUNCHPAD:
        return "Raydium Launchpad"
    if program_id == HEAVEN:
        return "Heaven"
    if program_id == MOONIT:
        return "Moonit"
    if program_id == METEORA_DBC:
        addresses = [str(account.get("Address", "")) for account in accounts]
        if BAGS_PROGRAM in addresses:
            return "Bags (Meteora DBC)"
        if any(address.endswith("jups") for address in addresses):
            return "Jupiter Studio (Meteora DBC)"
        return "Meteora DBC"
    return "Unknown"


def parse_launches(rows: list[dict[str, Any]]) -> list[LaunchEvent]:
    events: list[LaunchEvent] = []
    for row in rows:
        instruction = row.get("Instruction") or {}
        program = instruction.get("Program") or {}
        accounts = instruction.get("Accounts") or []
        program_id = str(program.get("Address") or "")
        mints = {
            str(token.get("Mint"))
            for account in accounts
            for token in [account.get("Token") or {}]
            if token.get("Mint")
        }
        mint = next(iter(mints)) if len(mints) == 1 else None
        block_time = (row.get("Block") or {}).get("Time")
        try:
            parsed_time = parse_datetime(block_time) if block_time else None
        except (TypeError, ValueError):
            parsed_time = None
        events.append(
            LaunchEvent(
                mint=mint,
                launchpad=_launchpad(program_id, str(program.get("Method") or ""), accounts),
                program_id=program_id,
                method=str(program.get("Method") or ""),
                block_time=parsed_time,
                signature=(row.get("Transaction") or {}).get("Signature"),
            )
        )
    return events
