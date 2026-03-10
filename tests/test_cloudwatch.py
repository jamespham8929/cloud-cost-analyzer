"""Tests for the CloudWatch fetch and profile builder, against a mocked client."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from cloud_cost_analyzer.cloudwatch import fetch_utilization_samples, profile_instance


def _cw_returning(util_percent: float, points_per_call: int = 24):
    """A mocked CloudWatch client whose every call returns a day of datapoints."""
    cw = MagicMock()

    def get_metric_statistics(**kwargs):
        start = kwargs["StartTime"]
        return {
            "Datapoints": [
                {
                    "Timestamp": start + timedelta(hours=h),
                    "Average": util_percent,
                }
                for h in range(points_per_call)
            ]
        }

    cw.get_metric_statistics.side_effect = get_metric_statistics
    return cw


class TestFetch:
    def test_converts_percent_to_fraction(self):
        cw = _cw_returning(40.0)
        samples = fetch_utilization_samples(cw, "i-0abc", days=1)
        assert samples
        assert all(abs(s.cpu_utilization - 0.40) < 1e-9 for s in samples)

    def test_pages_day_by_day(self):
        cw = _cw_returning(20.0)
        fetch_utilization_samples(cw, "i-0abc", days=3)
        # One call per day window.
        assert cw.get_metric_statistics.call_count == 3


class TestProfileInstance:
    def test_builds_profile_for_known_type(self):
        cw = _cw_returning(15.0)
        profile = profile_instance(cw, "i-0abc", "m5.2xlarge", days=2)
        assert profile is not None
        assert profile.vcpus == 8
        assert abs(profile.mean_util - 0.15) < 1e-9

    def test_unknown_instance_type_returns_none(self):
        cw = _cw_returning(15.0)
        assert profile_instance(cw, "i-0abc", "x1.32xlarge", days=2) is None
