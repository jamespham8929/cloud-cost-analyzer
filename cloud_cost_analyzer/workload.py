"""Temporal workload modeling.

A rightsizing decision made from average CPU is dangerous, and one made from peak
CPU is wasteful. Average hides the daily spike that actually sizes the instance.
Peak overreacts to a single outlier scrape. Neither captures the shape of the
load.

This module turns a utilization time series into a profile that describes that
shape: the recurring daily peak (distinct from one-off spikes), how volatile the
load is, how bursty it is, and whether it is trending up. Those are the inputs a
sound rightsizing decision actually needs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class UtilizationSample:
    timestamp: float        # epoch seconds
    cpu_utilization: float  # fraction in [0, 1]


def percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted list. q in [0, 1]."""
    if not sorted_values:
        raise ValueError("percentile of empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[int(pos)]
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


@dataclass(frozen=True)
class WorkloadProfile:
    instance_type: str
    vcpus: int
    n_samples: int
    coverage_days: float

    mean_util: float
    p50_util: float
    p95_util: float
    p99_util: float
    max_util: float

    recurring_peak_util: float   # the predictable daily peak, not a one-off spike
    volatility: float            # coefficient of variation (std / mean)
    peak_to_mean: float          # recurring peak divided by mean
    trend_per_day: float         # slope of utilization over time, per day

    hourly_peak_util: dict[int, float] = field(default_factory=dict)

    @property
    def is_bursty(self) -> bool:
        # A workload whose recurring peak is far above its mean cannot be sized
        # from its average. The 3x threshold is the boundary used in ADR 0002.
        return self.peak_to_mean >= 3.0

    @property
    def is_growing(self) -> bool:
        # Utilization climbing by more than 1 percentage point per day means the
        # service may need the headroom soon, so a downsize is risky.
        return self.trend_per_day >= 0.01


def build_profile(
    instance_type: str, vcpus: int, samples: list[UtilizationSample]
) -> WorkloadProfile:
    if len(samples) < 2:
        raise ValueError("need at least two samples to build a profile")

    ordered = sorted(samples, key=lambda s: s.timestamp)
    values = [s.cpu_utilization for s in ordered]
    sorted_values = sorted(values)

    mean = sum(values) / len(values)
    coverage_days = (ordered[-1].timestamp - ordered[0].timestamp) / 86400.0

    hourly_peak = _hourly_recurring(ordered)
    # The recurring peak is the highest of the per-hour 75th percentiles. The p75
    # within each hour bucket keeps a peak that shows up on most days while
    # rejecting a one-off spike, which would need to appear in more than a quarter
    # of an hour's samples to move the number.
    recurring_peak = max(hourly_peak.values()) if hourly_peak else percentile(sorted_values, 0.75)

    return WorkloadProfile(
        instance_type=instance_type,
        vcpus=vcpus,
        n_samples=len(values),
        coverage_days=coverage_days,
        mean_util=mean,
        p50_util=percentile(sorted_values, 0.50),
        p95_util=percentile(sorted_values, 0.95),
        p99_util=percentile(sorted_values, 0.99),
        max_util=sorted_values[-1],
        recurring_peak_util=recurring_peak,
        volatility=_coefficient_of_variation(values, mean),
        peak_to_mean=(recurring_peak / mean) if mean > 0 else float("inf"),
        trend_per_day=_trend_per_day(ordered),
        hourly_peak_util=hourly_peak,
    )


def _hourly_recurring(samples: list[UtilizationSample]) -> dict[int, float]:
    buckets: dict[int, list[float]] = {}
    for s in samples:
        hour = datetime.fromtimestamp(s.timestamp, tz=timezone.utc).hour
        buckets.setdefault(hour, []).append(s.cpu_utilization)
    return {hour: percentile(sorted(vals), 0.75) for hour, vals in buckets.items()}


def _coefficient_of_variation(values: list[float], mean: float) -> float:
    if mean <= 0:
        return float("inf")
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance) / mean


def _trend_per_day(samples: list[UtilizationSample]) -> float:
    """Least-squares slope of utilization against time, expressed per day."""
    t0 = samples[0].timestamp
    xs = [(s.timestamp - t0) / 86400.0 for s in samples]  # days since start
    ys = [s.cpu_utilization for s in samples]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    numer = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    return numer / denom
