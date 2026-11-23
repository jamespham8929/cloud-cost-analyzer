"""Tests for the CostAnalyzer orchestrator, with stubbed AWS clients."""

from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.stub import Stubber

from cloud_cost_analyzer.analyzer import CostAnalyzer


def _client(service):
    return boto3.client(
        service,
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


@pytest.fixture
def analyzer():
    clients = {name: _client(name) for name in ("ec2", "cloudwatch", "ce")}
    session = MagicMock()
    session.client.side_effect = lambda name, **_: clients[name]
    with patch("cloud_cost_analyzer.analyzer.boto3.Session", return_value=session):
        built = CostAnalyzer(region="us-east-1")
    stubbers = {name: Stubber(client) for name, client in clients.items()}
    for stubber in stubbers.values():
        stubber.activate()
    yield built, stubbers
    for stubber in stubbers.values():
        stubber.assert_no_pending_responses()
        stubber.deactivate()


def _coverage_item(service, covered, on_demand):
    return {
        "Attributes": {"SERVICE": service},
        "Coverage": {
            "SpendCoveredBySavingsPlans": str(covered),
            "OnDemandCost": str(on_demand),
            "TotalCost": str(covered + on_demand),
            "CoveragePercentage": "0",
        },
        "TimePeriod": {"Start": "2026-10-24", "End": "2026-11-01"},
    }


class TestSavingsPlansCoverage:
    def test_reports_real_coverage(self, analyzer):
        # The first version read a CoveredUsage key that Cost Explorer does not
        # return, so overall coverage was always 0%.
        built, stubbers = analyzer
        stubbers["ce"].add_response("get_savings_plans_coverage", {
            "SavingsPlansCoverages": [
                _coverage_item("Amazon Elastic Compute Cloud - Compute", 600, 200),
                _coverage_item("AWS Lambda", 0, 200),
            ],
        })
        data = built.get_savings_plans_coverage(30)

        assert data["period_days"] == 30
        assert data["total_on_demand_spend"] == 400.0
        assert data["total_covered_spend"] == 600.0
        assert data["overall_coverage_pct"] == 60.0
        assert data["by_service"]["Amazon Elastic Compute Cloud - Compute"]["coverage_pct"] == 75.0
        assert data["by_service"]["AWS Lambda"]["coverage_pct"] == 0.0

    def test_sums_a_service_seen_in_two_months(self, analyzer):
        built, stubbers = analyzer
        stubbers["ce"].add_response("get_savings_plans_coverage", {
            "SavingsPlansCoverages": [
                _coverage_item("AWS Lambda", 50, 50),
                _coverage_item("AWS Lambda", 150, 50),
            ],
        })
        data = built.get_savings_plans_coverage(30)
        assert data["by_service"]["AWS Lambda"] == {"on_demand_cost": 100.0, "coverage_pct": 66.7}

    def test_no_spend_reports_zero(self, analyzer):
        built, stubbers = analyzer
        stubbers["ce"].add_response("get_savings_plans_coverage", {"SavingsPlansCoverages": []})
        data = built.get_savings_plans_coverage(30)
        assert data["overall_coverage_pct"] == 0.0
        assert data["by_service"] == {}


class TestSavingsPlansRecommendations:
    def test_delegates_with_a_valid_lookback(self, analyzer):
        built, stubbers = analyzer
        stubbers["ce"].add_response(
            "get_savings_plans_purchase_recommendation",
            {},
            {
                "SavingsPlansType": "COMPUTE_SP",
                "TermInYears": "ONE_YEAR",
                "PaymentOption": "NO_UPFRONT",
                "LookbackPeriodInDays": "SIXTY_DAYS",
            },
        )
        assert built.get_savings_plans_recommendations(45) == []


class TestUnusedResources:
    def test_prices_an_unattached_io1_volume_with_its_iops(self, analyzer):
        from datetime import datetime, timedelta, timezone

        built, stubbers = analyzer
        ec2 = stubbers["ec2"]
        ec2.add_response("describe_volumes", {"Volumes": [{
            "VolumeId": "vol-io1",
            "Size": 100,
            "VolumeType": "io1",
            "Iops": 1000,
            "CreateTime": datetime.now(tz=timezone.utc) - timedelta(days=3),
            "State": "available",
        }]})
        ec2.add_response("describe_addresses", {"Addresses": []})
        ec2.add_response("describe_snapshots", {"Snapshots": []})
        ec2.add_response("describe_instances", {"Reservations": []})

        findings = built.get_unused_resources()

        assert [f.resource_id for f in findings] == ["vol-io1"]
        assert findings[0].monthly_cost == 77.5
