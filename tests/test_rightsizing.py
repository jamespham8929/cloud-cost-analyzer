"""Tests for the EC2 rightsizing analyzer."""

from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest

from cloud_cost_analyzer.ec2_rightsizing import (
    EC2RightsizingAnalyzer,
    RightsizingFinding,
    CPU_LOW_THRESHOLD,
    CPU_PEAK_THRESHOLD,
)


def make_analyzer():
    ec2 = MagicMock()
    cw = MagicMock()
    return EC2RightsizingAnalyzer(ec2, cw, "us-east-1"), ec2, cw


def make_instance(instance_id="i-0abc123", instance_type="m5.2xlarge", name="test"):
    return {
        "InstanceId": instance_id,
        "InstanceType": instance_type,
        "Tags": [{"Key": "Name", "Value": name}],
    }


class TestRecommendDownsize:
    def test_recommends_one_size_down(self):
        analyzer, _, _ = make_analyzer()
        result = analyzer._recommend_downsize("m5.2xlarge", avg_cpu=4.0, peak_cpu=15.0)
        assert result == "m5.xlarge"

    def test_no_recommendation_when_cpu_high(self):
        analyzer, _, _ = make_analyzer()
        result = analyzer._recommend_downsize("m5.2xlarge", avg_cpu=45.0, peak_cpu=80.0)
        assert result is None

    def test_no_recommendation_when_peak_cpu_high(self):
        analyzer, _, _ = make_analyzer()
        result = analyzer._recommend_downsize("m5.2xlarge", avg_cpu=10.0, peak_cpu=60.0)
        assert result is None

    def test_no_recommendation_for_smallest_in_family(self):
        analyzer, _, _ = make_analyzer()
        result = analyzer._recommend_downsize("m5.large", avg_cpu=2.0, peak_cpu=5.0)
        assert result is None

    def test_no_recommendation_for_unknown_type(self):
        analyzer, _, _ = make_analyzer()
        result = analyzer._recommend_downsize("x1.32xlarge", avg_cpu=2.0, peak_cpu=5.0)
        assert result is None

    def test_t3_family(self):
        analyzer, _, _ = make_analyzer()
        result = analyzer._recommend_downsize("t3.xlarge", avg_cpu=5.0, peak_cpu=10.0)
        assert result == "t3.large"


class TestAnalyze:
    def _setup_cw_mock(self, cw, avg_values, peak_values):
        def get_metric_statistics(**kwargs):
            if "Average" in kwargs.get("Statistics", []):
                return {"Datapoints": [{"Average": v} for v in avg_values]}
            return {"Datapoints": [{"Maximum": v} for v in peak_values]}
        cw.get_metric_statistics.side_effect = get_metric_statistics

    def test_returns_finding_for_underutilized_instance(self):
        analyzer, ec2, cw = make_analyzer()

        ec2.get_paginator.return_value.paginate.return_value = [
            {"Reservations": [{"Instances": [make_instance("i-001", "m5.2xlarge")]}]}
        ]
        self._setup_cw_mock(cw, avg_values=[3.0, 4.0, 5.0], peak_values=[10.0, 12.0, 15.0])

        findings = analyzer.analyze(lookback_days=14)
        assert len(findings) == 1
        assert findings[0].instance_id == "i-001"
        assert findings[0].recommended_type == "m5.xlarge"
        assert findings[0].monthly_savings > 0

    def test_skips_instance_with_no_metrics(self):
        analyzer, ec2, cw = make_analyzer()

        ec2.get_paginator.return_value.paginate.return_value = [
            {"Reservations": [{"Instances": [make_instance("i-002", "m5.2xlarge")]}]}
        ]
        cw.get_metric_statistics.return_value = {"Datapoints": []}

        findings = analyzer.analyze(lookback_days=14)
        assert findings == []

    def test_skips_well_utilized_instance(self):
        analyzer, ec2, cw = make_analyzer()

        ec2.get_paginator.return_value.paginate.return_value = [
            {"Reservations": [{"Instances": [make_instance("i-003", "m5.2xlarge")]}]}
        ]
        self._setup_cw_mock(cw, avg_values=[55.0, 60.0], peak_values=[85.0, 90.0])

        findings = analyzer.analyze(lookback_days=14)
        assert findings == []
