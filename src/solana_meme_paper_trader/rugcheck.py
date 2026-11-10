from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from .bitquery import AdapterError
from .models import RiskEvidence, utc_now


class RugCheckAdapter:
    """Fetches a report only; it does not submit reports, votes, or paid refresh requests."""

    def __init__(self, base_url: str = "https://api.rugcheck.xyz", timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def fetch_report(self, mint: str) -> dict[str, Any]:
        encoded_mint = urllib.parse.quote(mint, safe="")
        url = f"{self.base_url}/v1/tokens/{encoded_mint}/report"
        request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            raise AdapterError(f"RugCheck HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise AdapterError(f"RugCheck request failed: {exc}") from exc
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AdapterError("RugCheck returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise AdapterError("RugCheck report is not a JSON object")
        return payload


def _path_value(document: Any, dotted_path: str) -> Any:
    value = document
    for component in dotted_path.split("."):
        if isinstance(value, dict):
            value = value.get(component)
        elif isinstance(value, list) and component.isdigit():
            index = int(component)
            value = value[index] if index < len(value) else None
        else:
            return None
        if value is None:
            return None
    return value


def normalize_report(
    raw_report: dict[str, Any],
    mint: str,
    field_map: dict[str, str],
    fetched_at: datetime | None = None,
) -> RiskEvidence:
    """Map provider-specific JSON fields into strict evidence; unmapped values remain unknown."""
    allowed = {
        "liquidity_usd",
        "top_holder_pct",
        "mint_authority_active",
        "freeze_authority_active",
        "risk_flags",
    }
    unknown = set(field_map) - allowed
    if unknown:
        raise ValueError("unsupported RugCheck mapping(s): " + ", ".join(sorted(unknown)))
    values = {name: _path_value(raw_report, path) for name, path in field_map.items()}
    data = {
        "mint": mint,
        "fetched_at": (fetched_at or utc_now()).isoformat(),
        "provider": "RugCheck",
        **values,
    }
    # RiskEvidence validates types and leaves unmapped gates unknown so the risk policy can fail closed.
    return RiskEvidence.from_dict(data)
