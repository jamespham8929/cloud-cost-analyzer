"""Savings Plans coverage analysis and purchase recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class SavingsPlanRecommendation:
    commitment_type: str  # "ComputeSavingsPlans" | "EC2InstanceSavingsPlans"
    term: str             # "ONE_YEAR" | "THREE_YEAR"
    payment_option: str   # "NO_UPFRONT" | "PARTIAL_UPFRONT" | "ALL_UPFRONT"
    hourly_commitment: float
    estimated_monthly_savings: float
    estimated_coverage_pct: float
    on_demand_cost_covered: float


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
            LookbackPeriodInDays=f"DAYS_{lookback_period_days}",
        )

        recommendations = []
        for rec in response.get("SavingsPlansPurchaseRecommendation", {}).get("SavingsPlansPurchaseRecommendationDetails", []):
            details = rec.get("SavingsPlansDetails", {})
            est = rec.get("EstimatedSavings", {})

            recommendations.append(SavingsPlanRecommendation(
                commitment_type="ComputeSavingsPlans",
                term=term,
                payment_option=payment_option,
                hourly_commitment=float(details.get("HourlyCommitmentToPurchase", "0")),
                estimated_monthly_savings=float(est.get("EstimatedMonthlySavingsAmount", "0")),
                estimated_coverage_pct=float(rec.get("EstimatedNewCommitmentUtilization", "0")),
                on_demand_cost_covered=float(rec.get("CurrentAverageOnDemandSpend", "0")) * 720,
            ))

        return recommendations

    def get_coverage_by_account(
        self, lookback_days: int = 30
    ) -> dict[str, dict[str, Any]]:
        end = datetime.now(tz=timezone.utc).date()
        start = end - timedelta(days=lookback_days)

        response = self._ce.get_savings_plans_coverage(
            TimePeriod={"Start": str(start), "End": str(end)},
            Granularity="MONTHLY",
            GroupBy=[{"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"}],
        )

        by_account: dict[str, dict] = {}
        for period in response.get("SavingsPlansCoverages", []):
            for group in period.get("Groups", []):
                account_id = group["Attributes"].get("LINKED_ACCOUNT", "unknown")
                cov = group.get("Coverage", {})
                by_account[account_id] = {
                    "coverage_pct": round(float(cov.get("CoveragePercentage", "0")), 1),
                    "on_demand_cost": round(float(cov.get("OnDemandCost", "0")), 2),
                    "spend_covered": round(float(cov.get("SpendCoveredBySavingsPlans", "0")), 2),
                }

        return by_account
