"""Tests for the click CLI, with the AWS layer replaced."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from cloud_cost_analyzer.cli import cli
from cloud_cost_analyzer.ec2_rightsizing import RightsizingFinding
from cloud_cost_analyzer.savings_plans import SavingsPlanRecommendation
from cloud_cost_analyzer.unused_resources import ResourceType, UnusedResourceFinding
from cloud_cost_analyzer.workload import UtilizationSample, build_profile

FINDING = RightsizingFinding(
    instance_id="i-abc", instance_name="web", current_type="m5.xlarge",
    recommended_type="m5.large", avg_cpu=10.0, peak_cpu=35.0,
    monthly_savings=70.0, region="us-east-1",
)
SMALL_FINDING = RightsizingFinding(
    instance_id="i-tiny", instance_name="cron", current_type="t3.small",
    recommended_type="t3.micro", avg_cpu=5.0, peak_cpu=9.0,
    monthly_savings=4.0, region="us-east-1",
)
UNUSED = UnusedResourceFinding(
    resource_id="vol-1", resource_type=ResourceType.EBS_VOLUME,
    description="100 GB gp3, unattached", monthly_cost=8.0,
    region="us-east-1", days_unused=30,
)
COVERAGE = {"period_days": 30, "overall_coverage_pct": 60.0, "by_service": {}}


@pytest.fixture
def analyzer():
    fake = MagicMock()
    fake.get_rightsizing_recommendations.return_value = [FINDING, SMALL_FINDING]
    fake.get_unused_resources.return_value = [UNUSED]
    fake.get_savings_plans_coverage.return_value = COVERAGE
    fake.get_savings_plans_recommendations.return_value = []
    with patch("cloud_cost_analyzer.cli.CostAnalyzer", return_value=fake) as cls:
        yield fake, cls


def run(*args):
    result = CliRunner().invoke(cli, list(args), obj={})
    assert result.exit_code == 0, result.output
    return result.output


class TestGlobalOptions:
    def test_passes_region_and_profile_through(self, analyzer):
        _, cls = analyzer
        run("--region", "eu-west-1", "--profile", "prod", "unused")
        cls.assert_called_once_with(region="eu-west-1", profile="prod")


class TestAnalyze:
    def test_json_report_holds_every_section(self, analyzer, tmp_path):
        path = tmp_path / "out.json"
        run("analyze", "--format", "json", "--output", str(path), "--lookback-days", "7")
        data = json.loads(path.read_text())

        fake, _ = analyzer
        fake.get_rightsizing_recommendations.assert_called_once_with(7)
        assert {r["instance_id"] for r in data["rightsizing"]} == {"i-abc", "i-tiny"}
        assert data["unused_resources"][0]["resource_id"] == "vol-1"
        assert data["coverage"] == COVERAGE


class TestRightsize:
    def test_filters_out_small_savings(self, analyzer):
        out = run("rightsize", "--min-savings", "10")
        assert "i-abc" in out
        assert "i-tiny" not in out

    def test_says_so_when_nothing_qualifies(self, analyzer):
        out = run("rightsize", "--min-savings", "1000")
        assert "No rightsizing opportunities found" in out


class TestUnused:
    def test_csv_output(self, analyzer, tmp_path):
        path = tmp_path / "unused.csv"
        run("unused", "--format", "csv", "--output", str(path))
        assert "vol-1" in path.read_text()


class TestCoverage:
    def test_prints_coverage(self, analyzer):
        out = run("coverage")
        assert '"overall_coverage_pct": 60.0' in out

    def test_recommend_with_nothing_to_buy(self, analyzer):
        out = run("coverage", "--recommend")
        assert "No Savings Plans purchase recommendations" in out

    def test_recommend_lists_plans(self, analyzer):
        fake, _ = analyzer
        fake.get_savings_plans_recommendations.return_value = [
            SavingsPlanRecommendation(
                commitment_type="ComputeSavingsPlans", term="ONE_YEAR",
                payment_option="NO_UPFRONT", hourly_commitment=2.5,
                estimated_monthly_savings=640.0, estimated_savings_pct=27.5,
                estimated_utilization_pct=92.5, current_on_demand_monthly=3650.0,
            )
        ]
        out = run("coverage", "--recommend", "--period", "60")
        fake.get_savings_plans_recommendations.assert_called_once_with(60)
        assert "$2.50" in out
        assert "$640" in out
        assert "92%" in out or "93%" in out


def _steady_profile(instance_type="m5.2xlarge", vcpus=8, level=0.15):
    samples = [
        UtilizationSample(1_700_000_000 + i * 3600, level) for i in range(14 * 24)
    ]
    return build_profile(instance_type, vcpus, samples)


class TestRightsizeTemporal:
    @pytest.fixture
    def ec2(self):
        session = MagicMock()
        ec2 = session.client.return_value
        ec2.get_paginator.return_value.paginate.return_value = [{
            "Reservations": [{"Instances": [
                {"InstanceId": "i-steady", "InstanceType": "m5.2xlarge"},
                {"InstanceId": "i-unknown", "InstanceType": "x99.huge"},
            ]}]
        }]
        with patch("boto3.Session", return_value=session):
            yield ec2

    def test_shows_a_safe_downsize(self, ec2):
        def profile(_cw, instance_id, instance_type, _days):
            return _steady_profile() if instance_id == "i-steady" else None

        with patch("cloud_cost_analyzer.cloudwatch.profile_instance", side_effect=profile):
            out = run("rightsize-temporal")
        assert "i-steady" in out
        assert "safe" in out
        assert "i-unknown" not in out

    def test_safe_only_hides_risky_rows(self, ec2):
        spiky = [
            UtilizationSample(1_700_000_000 + i * 3600, 0.9 if i % 24 == 9 else 0.1)
            for i in range(14 * 24)
        ]
        with patch(
            "cloud_cost_analyzer.cloudwatch.profile_instance",
            return_value=build_profile("m5.2xlarge", 8, spiky),
        ):
            out = run("rightsize-temporal", "--safe-only")
        assert "i-steady" not in out
