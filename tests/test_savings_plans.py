"""Tests for Savings Plans purchase recommendations, against a mocked CE client."""

from unittest.mock import MagicMock

from cloud_cost_analyzer.savings_plans import SavingsPlansAnalyzer


def _ce_with_recommendation():
    ce = MagicMock()
    ce.get_savings_plans_purchase_recommendation.return_value = {
        "SavingsPlansPurchaseRecommendation": {
            "SavingsPlansPurchaseRecommendationDetails": [
                {
                    "SavingsPlansDetails": {"HourlyCommitmentToPurchase": "2.50"},
                    "EstimatedSavings": {"EstimatedMonthlySavingsAmount": "640.0"},
                    "EstimatedNewCommitmentUtilization": "92.5",
                    "CurrentAverageOnDemandSpend": "5.00",
                }
            ]
        }
    }
    return ce


class TestGetRecommendations:
    def test_parses_a_recommendation(self):
        analyzer = SavingsPlansAnalyzer(_ce_with_recommendation())
        recs = analyzer.get_recommendations(lookback_period_days=30)
        assert len(recs) == 1
        rec = recs[0]
        assert rec.hourly_commitment == 2.50
        assert rec.estimated_monthly_savings == 640.0
        assert rec.commitment_type == "ComputeSavingsPlans"
        assert rec.term == "ONE_YEAR"

    def test_passes_lookback_to_api(self):
        ce = _ce_with_recommendation()
        SavingsPlansAnalyzer(ce).get_recommendations(lookback_period_days=14)
        _, kwargs = ce.get_savings_plans_purchase_recommendation.call_args
        assert kwargs["LookbackPeriodInDays"] == "DAYS_14"

    def test_empty_response_yields_no_recommendations(self):
        ce = MagicMock()
        ce.get_savings_plans_purchase_recommendation.return_value = {}
        assert SavingsPlansAnalyzer(ce).get_recommendations() == []
