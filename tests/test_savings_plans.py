"""Tests for Savings Plans recommendations and coverage.

These use botocore's Stubber with a real Cost Explorer client. The stubber
checks every request and every canned response against the AWS API model, so
a wrong field name or enum value fails here instead of in a real account. The
first version of these tests used a MagicMock, and both the code and the
mock agreed on field names that the API does not have.
"""

import boto3
import pytest
from botocore.stub import Stubber

from cloud_cost_analyzer.savings_plans import SavingsPlansAnalyzer, lookback_window


@pytest.fixture
def ce():
    client = boto3.client(
        "ce",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


RECOMMENDATION_RESPONSE = {
    "SavingsPlansPurchaseRecommendation": {
        "SavingsPlansPurchaseRecommendationDetails": [
            {
                "SavingsPlansDetails": {"Region": "us-east-1"},
                "HourlyCommitmentToPurchase": "2.50",
                "EstimatedMonthlySavingsAmount": "640.0",
                "EstimatedSavingsPercentage": "27.5",
                "EstimatedAverageUtilization": "92.5",
                "CurrentAverageHourlyOnDemandSpend": "5.00",
            }
        ]
    }
}


class TestLookbackWindow:
    @pytest.mark.parametrize("days, expected", [
        (1, "SEVEN_DAYS"),
        (7, "SEVEN_DAYS"),
        (8, "THIRTY_DAYS"),
        (14, "THIRTY_DAYS"),
        (30, "THIRTY_DAYS"),
        (45, "SIXTY_DAYS"),
        (90, "SIXTY_DAYS"),
    ])
    def test_rounds_up_to_a_supported_window(self, days, expected):
        assert lookback_window(days) == expected


class TestGetRecommendations:
    def test_parses_a_recommendation(self, ce):
        client, stubber = ce
        stubber.add_response(
            "get_savings_plans_purchase_recommendation",
            RECOMMENDATION_RESPONSE,
            {
                "SavingsPlansType": "COMPUTE_SP",
                "TermInYears": "ONE_YEAR",
                "PaymentOption": "NO_UPFRONT",
                "LookbackPeriodInDays": "THIRTY_DAYS",
            },
        )
        recs = SavingsPlansAnalyzer(client).get_recommendations(lookback_period_days=30)

        assert len(recs) == 1
        rec = recs[0]
        assert rec.hourly_commitment == 2.50
        assert rec.estimated_monthly_savings == 640.0
        assert rec.estimated_savings_pct == 27.5
        assert rec.estimated_utilization_pct == 92.5
        assert rec.current_on_demand_monthly == 5.00 * 730
        assert rec.commitment_type == "ComputeSavingsPlans"
        assert rec.term == "ONE_YEAR"

    def test_sends_a_lookback_the_api_accepts(self, ce):
        client, stubber = ce
        stubber.add_response(
            "get_savings_plans_purchase_recommendation",
            {},
            {
                "SavingsPlansType": "COMPUTE_SP",
                "TermInYears": "THREE_YEARS",
                "PaymentOption": "ALL_UPFRONT",
                "LookbackPeriodInDays": "THIRTY_DAYS",
            },
        )
        SavingsPlansAnalyzer(client).get_recommendations(
            lookback_period_days=14, payment_option="ALL_UPFRONT", term="THREE_YEARS",
        )

    def test_empty_response_yields_no_recommendations(self, ce):
        client, stubber = ce
        stubber.add_response("get_savings_plans_purchase_recommendation", {})
        assert SavingsPlansAnalyzer(client).get_recommendations() == []


def _coverage_item(key, value, covered, on_demand, start="2026-10-01", end="2026-11-01"):
    total = covered + on_demand
    return {
        "Attributes": {key: value},
        "Coverage": {
            "SpendCoveredBySavingsPlans": str(covered),
            "OnDemandCost": str(on_demand),
            "TotalCost": str(total),
            "CoveragePercentage": str(covered / total * 100 if total else 0),
        },
        "TimePeriod": {"Start": start, "End": end},
    }


class TestCoverageByAccount:
    def test_sums_an_account_across_months(self, ce):
        client, stubber = ce
        stubber.add_response("get_savings_plans_coverage", {
            "SavingsPlansCoverages": [
                _coverage_item("LINKED_ACCOUNT", "111111111111", 300, 100),
                _coverage_item("LINKED_ACCOUNT", "111111111111", 100, 100,
                               start="2026-11-01", end="2026-11-23"),
                _coverage_item("LINKED_ACCOUNT", "222222222222", 0, 50),
            ],
        })
        result = SavingsPlansAnalyzer(client).get_coverage_by_account(30)

        assert result["111111111111"] == {
            "coverage_pct": round(400 / 600 * 100, 1),
            "on_demand_cost": 200.0,
            "spend_covered": 400.0,
        }
        assert result["222222222222"]["coverage_pct"] == 0.0

    def test_follows_next_token(self, ce):
        client, stubber = ce
        stubber.add_response("get_savings_plans_coverage", {
            "SavingsPlansCoverages": [_coverage_item("LINKED_ACCOUNT", "111111111111", 10, 10)],
            "NextToken": "page-2",
        })
        stubber.add_response("get_savings_plans_coverage", {
            "SavingsPlansCoverages": [_coverage_item("LINKED_ACCOUNT", "333333333333", 5, 5)],
        })
        result = SavingsPlansAnalyzer(client).get_coverage_by_account(30)
        assert set(result) == {"111111111111", "333333333333"}

    def test_no_spend_means_zero_coverage(self, ce):
        client, stubber = ce
        stubber.add_response("get_savings_plans_coverage", {"SavingsPlansCoverages": []})
        assert SavingsPlansAnalyzer(client).get_coverage_by_account(30) == {}
