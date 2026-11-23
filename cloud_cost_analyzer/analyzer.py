"""Top-level orchestrator that wires together the individual analysis modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import boto3

from .ec2_rightsizing import EC2RightsizingAnalyzer, RightsizingFinding
from .savings_plans import SavingsPlansAnalyzer, coverage_pct
from .unused_resources import UnusedResourceFinding, UnusedResourceScanner


@dataclass
class CoverageReport:
    period_days: int
    on_demand_spend: float
    covered_spend: float
    coverage_pct: float
    by_service: dict[str, dict] = field(default_factory=dict)


class CostAnalyzer:
    def __init__(self, region: str = "us-east-1", profile: str | None = None):
        session = boto3.Session(profile_name=profile, region_name=region)
        self._region = region
        self._ec2 = session.client("ec2")
        self._cw = session.client("cloudwatch")
        self._ce = session.client("ce", region_name="us-east-1")

        self._rightsizer = EC2RightsizingAnalyzer(self._ec2, self._cw, region)
        self._unused_scanner = UnusedResourceScanner(self._ec2, region)

    def get_rightsizing_recommendations(
        self, lookback_days: int = 14
    ) -> list[RightsizingFinding]:
        return self._rightsizer.analyze(lookback_days=lookback_days)

    def get_unused_resources(self) -> list[UnusedResourceFinding]:
        return self._unused_scanner.scan()

    def get_savings_plans_recommendations(self, lookback_days: int = 30):
        return SavingsPlansAnalyzer(self._ce).get_recommendations(lookback_days)

    def get_savings_plans_coverage(self, period_days: int = 30) -> dict[str, Any]:
        sums = SavingsPlansAnalyzer(self._ce).coverage_sums("SERVICE", period_days)

        by_service = {
            service: {
                "on_demand_cost": round(e["on_demand"], 2),
                "coverage_pct": round(coverage_pct(e["covered"], e["on_demand"]), 1),
            }
            for service, e in sums.items()
        }
        total_on_demand = sum(e["on_demand"] for e in sums.values())
        total_covered = sum(e["covered"] for e in sums.values())

        return {
            "period_days": period_days,
            "total_on_demand_spend": round(total_on_demand, 2),
            "total_covered_spend": round(total_covered, 2),
            "overall_coverage_pct": round(coverage_pct(total_covered, total_on_demand), 1),
            "by_service": by_service,
        }
