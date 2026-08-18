"""Versioned Reader configuration for independent broad-market observations."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .config import CONFIG_DIR


REGISTRY_PATH = CONFIG_DIR / "broad_market_anchors_v1.json"
_SYMBOL = re.compile(r"^(?:sh|sz)\d{6}$")


@dataclass(frozen=True)
class BroadMarketAnchor:
    symbol: str
    exchange: str
    security_code: str
    security_name: str
    display_order: int
    enabled: bool

    @property
    def reader_code(self) -> str:
        return f"{self.security_code}.{self.exchange.upper()}"


def load_broad_market_anchors() -> tuple[BroadMarketAnchor, ...]:
    document = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    values = tuple(BroadMarketAnchor(
        symbol=str(item["symbol"]), exchange=str(item["exchange"]),
        security_code=str(item["security_code"]), security_name=str(item["security_name"]),
        display_order=int(item["display_order"]), enabled=bool(item["enabled"]),
    ) for item in document["anchors"])
    if len(values) != 4 or len({item.symbol for item in values}) != len(values):
        raise ValueError("broad_market_anchors_invalid")
    if any(not _SYMBOL.fullmatch(item.symbol) or item.symbol[2:] != item.security_code for item in values):
        raise ValueError("broad_market_anchor_symbol_invalid")
    return tuple(sorted((item for item in values if item.enabled), key=lambda item: item.display_order))
