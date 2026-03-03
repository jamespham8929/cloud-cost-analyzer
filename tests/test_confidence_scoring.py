"""Tests for the rightsizing confidence model."""

import pytest

from cloud_cost_analyzer.confidence import RiskTier, score_recommendation
from cloud_cost_analyzer.workload import UtilizationSample, build_profile

BASE_TS = 1_700_000_000


def make_profile(value_for_hour, days=14, instance="m5.2xlarge", vcpus=8):
    samples = []
    for day in range(days):
        for hour in range(24):
            ts = BASE_TS + day * 86400 + hour * 3600
            samples.append(UtilizationSample(ts, value_for_hour(hour)))
    return build_profile(instance, vcpus, samples)


class TestTiering:
    def test_steady_well_covered_workload_is_safe(self):
        profile = make_profile(lambda h: 0.12)
        result = score_recommendation(profile, recommended_vcpus=2, target_peak_utilization=0.65)
        assert result.tier == RiskTier.SAFE
        assert result.score >= 0.75

    def test_short_history_lowers_score(self):
        long_history = make_profile(lambda h: 0.12, days=14)
        short_history = make_profile(lambda h: 0.12, days=2)
        long_res = score_recommendation(long_history, 2, 0.65)
        short_res = score_recommendation(short_history, 2, 0.65)
        assert short_res.score < long_res.score
        assert any("days of data" in r for r in short_res.reasons)

    def test_tight_headroom_flagged(self):
        # Load of 0.40 on 8 vCPUs is 3.2 vCPU of demand. On a 4 vCPU instance the
        # peak lands at 80%, above the 65% target, so the margin score drops and
        # the recommendation carries a headroom warning.
        profile = make_profile(lambda h: 0.40)
        result = score_recommendation(profile, recommended_vcpus=4, target_peak_utilization=0.65)
        assert result.breakdown.headroom_margin < 1.0
        assert any("headroom" in r for r in result.reasons)


class TestBreakdownTransparency:
    def test_breakdown_factors_in_unit_range(self):
        profile = make_profile(lambda h: 0.15)
        result = score_recommendation(profile, 2, 0.65)
        b = result.breakdown
        for factor in (b.data_coverage, b.headroom_margin, b.burstiness, b.volatility, b.trend):
            assert 0.0 <= factor <= 1.0

    def test_weighted_score_matches_breakdown(self):
        profile = make_profile(lambda h: 0.15)
        result = score_recommendation(profile, 2, 0.65)
        assert result.score == pytest.approx(result.breakdown.weighted_score())
