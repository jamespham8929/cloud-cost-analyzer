"""Tests for temporal, confidence-scored rightsizing.

The headline behavior: a steady, underused instance is a safe downsize, and a
spiky instance with the same low average is correctly refused. This is the case
average-based tooling gets wrong.
"""

import pytest

from cloud_cost_analyzer.confidence import RiskTier
from cloud_cost_analyzer.temporal_rightsizing import TemporalRightsizer
from cloud_cost_analyzer.workload import UtilizationSample, build_profile

BASE_TS = 1_700_000_000


def hourly_samples(days: int, value_for_hour):
    out = []
    for day in range(days):
        for hour in range(24):
            ts = BASE_TS + day * 86400 + hour * 3600
            out.append(UtilizationSample(ts, value_for_hour(hour)))
    return out


class TestSafeDownsize:
    def test_steady_underused_instance_is_a_safe_downsize(self):
        samples = hourly_samples(14, lambda h: 0.15)
        profile = build_profile("m5.2xlarge", 8, samples)
        rec = TemporalRightsizer().recommend(profile)

        assert rec is not None
        assert rec.recommended_vcpus < rec.current_vcpus
        assert rec.monthly_savings > 0
        assert rec.confidence.tier == RiskTier.SAFE
        assert rec.is_actionable
        # Peak must stay under the headroom target on the smaller instance.
        assert rec.projected_peak_util <= 0.65 + 1e-9


class TestRefusesSpiky:
    def test_spiky_instance_with_low_average_is_not_downsized(self):
        # Same low average as the steady case, but a daily spike to 85%.
        samples = hourly_samples(14, lambda h: 0.85 if h == 9 else 0.10)
        profile = build_profile("m5.2xlarge", 8, samples)
        rec = TemporalRightsizer().recommend(profile)
        # The recurring peak needs the current capacity, so no downsize is offered.
        assert rec is None


class TestGrowingWorkload:
    def test_growing_load_lowers_confidence(self):
        steady = hourly_samples(14, lambda h: 0.12)
        steady_rec = TemporalRightsizer().recommend(build_profile("m5.2xlarge", 8, steady))

        growing = []
        for day in range(14):
            for hour in range(24):
                ts = BASE_TS + day * 86400 + hour * 3600
                growing.append(UtilizationSample(ts, 0.08 + 0.005 * day))
        growing_rec = TemporalRightsizer().recommend(build_profile("m5.2xlarge", 8, growing))

        assert steady_rec is not None and growing_rec is not None
        # Both may downsize, but the growing one must score lower on confidence.
        assert growing_rec.confidence.score < steady_rec.confidence.score


class TestEdgeCases:
    def test_unknown_family_returns_none(self):
        samples = hourly_samples(14, lambda h: 0.10)
        profile = build_profile("x1.32xlarge", 128, samples)
        assert TemporalRightsizer().recommend(profile) is None

    def test_smallest_in_family_not_downsized(self):
        samples = hourly_samples(14, lambda h: 0.10)
        profile = build_profile("m5.large", 2, samples)
        # Already the smallest m5, nothing smaller to recommend.
        assert TemporalRightsizer().recommend(profile) is None

    def test_invalid_target_rejected(self):
        with pytest.raises(ValueError):
            TemporalRightsizer(target_peak_utilization=1.5)
