"""Top-level orchestrator that wires together the individual analysis modules."""

from __future__ import annotations

import boto3
from dataclasses import dataclass, field
from typing import Any

from .ec2_rightsizing import EC2RightsizingAnalyzer, RightsizingFinding
from .unused_resources import UnusedResourceScanner, UnusedResourceFinding


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
        from .savings_plans import SavingsPlansAnalyzer

        return SavingsPlansAnalyzer(self._ce).get_recommendations(lookback_days)

    def get_savings_plans_coverage(self, period_days: int = 30) -> dict[str, Any]:
        from datetime import datetime, timedelta, timezone

        end = datetime.now(tz=timezone.utc).date()
        start = end - timedelta(days=period_days)

        response = self._ce.get_savings_plans_coverage(
            TimePeriod={"Start": str(start), "End": str(end)},
            Granularity="MONTHLY",
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )

        total_on_demand = 0.0
        total_covered = 0.0
        by_service: dict[str, dict] = {}

        for period in response.get("SavingsPlansCoverages", []):
            for group in period.get("Groups", []):
                service = group["Attributes"].get("SERVICE", "Unknown")
                cov = group["Coverage"]
                on_demand = float(cov.get("OnDemandCost", "0"))
                covered = float(cov.get("CoveredUsage", "0")) * on_demand  # approx
                pct = float(cov.get("CoveragePercentage", "0"))

                total_on_demand += on_demand
                total_covered += covered
                by_service[service] = {
                    "on_demand_cost": round(on_demand, 2),
                    "coverage_pct": round(pct, 1),
                }

        overall_pct = (total_covered / total_on_demand * 100) if total_on_demand > 0 else 0.0

        return {
            "period_days": period_days,
            "total_on_demand_spend": round(total_on_demand, 2),
            "overall_coverage_pct": round(overall_pct, 1),
            "by_service": by_service,
        }
