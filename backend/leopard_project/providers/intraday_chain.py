from __future__ import annotations

from datetime import datetime

from ..models import DailyBar, SectorMapping
from .eastmoney_spot import EastmoneyBoardSpotProvider
from .ths_exact_spot import ThsExactSpotProvider


class ResearchIntradayProviderChain:
    """Explicit local research chain; never promotes either source to production."""

    provider_key = "research_intraday_chain"
    provider_role = "research_provider"
    ths_exact_sector_keys = frozenset({"computing_power_rental", "retail", "small_appliances"})

    def __init__(
        self,
        *,
        eastmoney: EastmoneyBoardSpotProvider | None = None,
        ths_exact: ThsExactSpotProvider | None = None,
    ) -> None:
        self.eastmoney = eastmoney or EastmoneyBoardSpotProvider()
        self.ths_exact = ths_exact or ThsExactSpotProvider()

    @property
    def request_count(self) -> int:
        return self.eastmoney.request_count + self.ths_exact.request_count

    def begin_cycle(self) -> None:
        self.eastmoney.begin_cycle()
        self.ths_exact.begin_cycle()

    def fetch_intraday_snapshot(self, mapping: SectorMapping, as_of: datetime) -> DailyBar:
        provider = self.ths_exact if mapping.sector_key in self.ths_exact_sector_keys else self.eastmoney
        return provider.fetch_intraday_snapshot(mapping, as_of)
