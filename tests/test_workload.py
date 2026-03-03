"""Tests for temporal workload profiling."""

import pytest

from cloud_cost_analyzer.workload import (
    UtilizationSample,
    build_profile,
    percentile,
)

BASE_TS = 1_700_000_000  # fixed epoch start for deterministic hour bucketing


def hourly_samples(days: int, value_for_hour, samples_per_hour: int = 1):
    """Generate one or more samples per hour over `days`, value chosen per hour."""
    out = []
    for day in range(days):
        for hour in range(24):
            for k in range(samples_per_hour):
                ts = BASE_TS + day * 86400 + hour * 3600 + k * (3600 // samples_per_hour)
                out.append(UtilizationSample(ts, value_for_hour(hour)))
    return out


class TestPercentile:
    def test_median(self):
        assert percentile([1, 2, 3, 4, 5], 0.5) == 3

    def test_interpolated(self):
        assert percentile([0, 10], 0.5) == 5

    def test_p95_of_uniform(self):
        vals = sorted([float(i) for i in range(100)])
        assert percentile(vals, 0.95) == pytest.approx(94.05, abs=0.5)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            percentile([], 0.5)


class TestSteadyWorkload:
    def test_flat_load_has_low_peak_to_mean(self):
        samples = hourly_samples(14, lambda h: 0.15)
        profile = build_profile("m5.2xlarge", 8, samples)
        assert profile.mean_util == pytest.approx(0.15, abs=1e-9)
        assert profile.recurring_peak_util == pytest.approx(0.15, abs=1e-9)
        assert profile.peak_to_mean == pytest.approx(1.0, abs=1e-9)
        assert not profile.is_bursty
        assert profile.coverage_days == pytest.approx(13.96, abs=0.1)


class TestSpikyWorkload:
    def test_daily_spike_drives_recurring_peak(self):
        # Low baseline, one predictable spike each day at hour 9.
        samples = hourly_samples(14, lambda h: 0.85 if h == 9 else 0.10)
        profile = build_profile("m5.2xlarge", 8, samples)
        # Mean stays low, but the recurring peak captures the daily spike.
        assert profile.mean_util < 0.20
        assert profile.recurring_peak_util == pytest.approx(0.85, abs=1e-9)
        assert profile.peak_to_mean > 3.0
        assert profile.is_bursty

    def test_one_off_spike_does_not_become_recurring_peak(self):
        # A single outlier in one hour on one day should be discarded by the
        # per-hour p95, so the recurring peak stays near baseline.
        samples = hourly_samples(14, lambda h: 0.10)
        # Inject a single outlier at day 0, hour 9.
        samples.append(UtilizationSample(BASE_TS + 9 * 3600, 0.99))
        profile = build_profile("m5.2xlarge", 8, samples)
        assert profile.recurring_peak_util < 0.30
        assert profile.max_util == pytest.approx(0.99)


class TestTrend:
    def test_growing_load_detected(self):
        # Utilization climbs from ~0.1 to ~0.4 over 14 days.
        samples = []
        for day in range(14):
            for hour in range(24):
                ts = BASE_TS + day * 86400 + hour * 3600
                samples.append(UtilizationSample(ts, 0.10 + 0.02 * day))
        profile = build_profile("m5.2xlarge", 8, samples)
        assert profile.trend_per_day > 0.01
        assert profile.is_growing

    def test_flat_load_not_growing(self):
        samples = hourly_samples(14, lambda h: 0.15)
        profile = build_profile("m5.2xlarge", 8, samples)
        assert abs(profile.trend_per_day) < 1e-6
        assert not profile.is_growing
