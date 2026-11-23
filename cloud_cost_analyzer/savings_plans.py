"""Savings Plans coverage analysis and purchase recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

HOURS_PER_MONTH = 730

# Cost Explorer only computes recommendations over these windows.
_LOOKBACK_WINDOWS = [(7, "SEVEN_DAYS"), (30, "THIRTY_DAYS"), (60, "SIXTY_DAYS")]


def lookback_window(days: int) -> str:
    """Smallest supported window that covers the requested days.

    A request for 14 days becomes THIRTY_DAYS, not SEVEN_DAYS, because a
    shorter window would ignore load the caller asked to include.
    """
    for limit, name in _LOOKBACK_WINDOWS:
        if days <= limit:
            return name
    return "SIXTY_DAYS"


@dataclass
class SavingsPlanRecommendation:
    commitment_type: str  # "ComputeSavingsPlans" | "EC2InstanceSavingsPlans"
    term: str             # "ONE_YEAR" | "THREE_YEARS"
    payment_option: str   # "NO_UPFRONT" | "PARTIAL_UPFRONT" | "ALL_UPFRONT"
    hourly_commitment: float
    estimated_monthly_savings: float
    estimated_savings_pct: float
    # How much of the commitment the past usage would have used. Under 100%
    # means part of the commitment would be paid for and not used.
    estimated_utilization_pct: float
    current_on_demand_monthly: float


class SavingsPlansAnalyzer:
    def __init__(self, ce_client):
        self._ce = ce_client

    def get_recommendations(
        self,
        lookback_period_days: int = 30,
        payment_option: str = "NO_UPFRONT",
        term: str = "ONE_YEAR",
    ) -> list[SavingsPlanRecommendation]:
        response = self._ce.get_savings_plans_purchase_recommendation(
            SavingsPlansType="COMPUTE_SP",
            TermInYears=term,
            PaymentOption=payment_option,
            LookbackPeriodInDays=lookback_window(lookback_period_days),
        )

        recommendations = []
        details = (
            response.get("SavingsPlansPurchaseRecommendation", {})
            .get("SavingsPlansPurchaseRecommendationDetails", [])
        )
        for rec in details:
            hourly_on_demand = float(rec.get("CurrentAverageHourlyOnDemandSpend", "0"))
            recommendations.append(SavingsPlanRecommendation(
                commitment_type="ComputeSavingsPlans",
                term=term,
                payment_option=payment_option,
                hourly_commitment=float(rec.get("HourlyCommitmentToPurchase", "0")),
                estimated_monthly_savings=float(rec.get("EstimatedMonthlySavingsAmount", "0")),
                estimated_savings_pct=float(rec.get("EstimatedSavingsPercentage", "0")),
                estimated_utilization_pct=float(rec.get("EstimatedAverageUtilization", "0")),
                current_on_demand_monthly=hourly_on_demand * HOURS_PER_MONTH,
            ))

        return recommendations

    def coverage_sums(self, dimension: str, lookback_days: int = 30) -> dict[str, dict[str, float]]:
        """Covered and on-demand spend per value of one dimension.

        Each item in the response already carries the grouped value in its
        Attributes. A 30-day window spans two calendar months, so the same key
        can appear once per period. Sum them before taking any ratio.
        """
        end = datetime.now(tz=timezone.utc).date()
        start = end - timedelta(days=lookback_days)
        request: dict[str, Any] = {
            "TimePeriod": {"Start": str(start), "End": str(end)},
            "Granularity": "MONTHLY",
            "GroupBy": [{"Type": "DIMENSION", "Key": dimension}],
        }

        sums: dict[str, dict[str, float]] = {}
        while True:
            response = self._ce.get_savings_plans_coverage(**request)
            for item in response.get("SavingsPlansCoverages", []):
                attributes = item.get("Attributes", {})
                key = attributes.get(dimension) or next(iter(attributes.values()), "Unknown")
                coverage = item.get("Coverage", {})
                entry = sums.setdefault(key, {"on_demand": 0.0, "covered": 0.0})
                entry["on_demand"] += float(coverage.get("OnDemandCost", "0"))
                entry["covered"] += float(coverage.get("SpendCoveredBySavingsPlans", "0"))
            token = response.get("NextToken")
            if not token:
                return sums
            request["NextToken"] = token

    def get_coverage_by_account(
        self, lookback_days: int = 30
    ) -> dict[str, dict[str, Any]]:
        sums = self.coverage_sums("LINKED_ACCOUNT", lookback_days)
        return {
            account: {
                "coverage_pct": round(coverage_pct(e["covered"], e["on_demand"]), 1),
                "on_demand_cost": round(e["on_demand"], 2),
                "spend_covered": round(e["covered"], 2),
            }
            for account, e in sums.items()
        }


def coverage_pct(covered: float, on_demand: float) -> float:
    """Share of eligible spend a Savings Plan paid for.

    Eligible spend is what the plan covered plus what still ran on demand.
    This matches Cost Explorer's own CoveragePercentage.
    """
    total = covered + on_demand
    return covered / total * 100 if total > 0 else 0.0
