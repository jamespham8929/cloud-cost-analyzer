"""Naive average/p95 rightsizing vs temporal, confidence-scored rightsizing.

The trap: a service with a low average and a low overall p95, but a sharp daily
spike. Because the spike occupies less than 5% of the day, the overall p95 sits
down at baseline and a p95-based rightsizer happily downsizes the instance. Then
the next morning the daily spike lands on an instance too small to hold it.

This script builds exactly that workload and shows the two approaches disagree:
the naive sizer recommends a downsize that would be throttled by the daily peak,
while the temporal sizer refuses it because the recurring peak needs the capacity.

Run:
    PYTHONPATH=. python benchmarks/naive_vs_temporal.py
"""

from __future__ import annotations

from cloud_cost_analyzer.instance_catalog import INSTANCE_VCPUS
from cloud_cost_analyzer.temporal_rightsizing import TemporalRightsizer
from cloud_cost_analyzer.workload import (
    UtilizationSample,
    build_profile,
    percentile,
)
from cloud_cost_analyzer.ec2_rightsizing import INSTANCE_FAMILY_LADDER, MONTHLY_COST

BASE_TS = 1_700_000_000
TARGET = 0.65


def make_samples(days, value_for_hour):
    out = []
    for day in range(days):
        for hour in range(24):
            ts = BASE_TS + day * 86400 + hour * 3600
            out.append(UtilizationSample(ts, value_for_hour(hour)))
    return out


def naive_recommendation(instance_type, vcpus, samples):
    """Size the instance from the overall p95, the way a noise-averse rightsizer
    does. Returns the recommended type, or None if no downsize."""
    values = sorted(s.cpu_utilization for s in samples)
    overall_p95 = percentile(values, 0.95)
    family = instance_type.split(".")[0]
    ladder = INSTANCE_FAMILY_LADDER.get(family, [])
    demand = overall_p95 * vcpus
    need = demand / TARGET
    for candidate in ladder:
        if INSTANCE_VCPUS.get(candidate, 0) >= need:
            if INSTANCE_VCPUS[candidate] < vcpus:
                return candidate, overall_p95
            return None, overall_p95
    return None, overall_p95


def evaluate(label, samples):
    instance, vcpus = "m5.2xlarge", 8
    profile = build_profile(instance, vcpus, samples)

    naive_type, overall_p95 = naive_recommendation(instance, vcpus, samples)
    temporal = TemporalRightsizer(TARGET).recommend(profile)

    print(f"\n=== {label} ===")
    print(f"  mean util {profile.mean_util:.0%}, overall p95 {overall_p95:.0%}, "
          f"recurring daily peak {profile.recurring_peak_util:.0%}")

    if naive_type:
        peak_on_naive = profile.recurring_peak_util * vcpus / INSTANCE_VCPUS[naive_type]
        verdict = "WOULD THROTTLE on the daily peak" if peak_on_naive > 1.0 \
            else f"daily peak lands at {peak_on_naive:.0%}"
        print(f"  naive (p95-based):  downsize to {naive_type}  -> {verdict}")
    else:
        print(f"  naive (p95-based):  no downsize")

    if temporal and temporal.is_actionable:
        print(f"  temporal:           downsize to {temporal.recommended_type} "
              f"[{temporal.confidence.tier.value}, score {temporal.confidence.score:.2f}], "
              f"peak lands at {temporal.projected_peak_util:.0%}")
    elif temporal:
        print(f"  temporal:           downsize to {temporal.recommended_type} held back "
              f"[{temporal.confidence.tier.value}, score {temporal.confidence.score:.2f}]")
    else:
        reasons = ", ".join(
            r for r in (
                "recurring peak needs current capacity",
            )
        )
        print(f"  temporal:           no downsize ({reasons})")


def main():
    steady = make_samples(14, lambda h: 0.15)
    spiky = make_samples(14, lambda h: 0.85 if h == 9 else 0.10)

    evaluate("steady service (safe to downsize)", steady)
    evaluate("spiky service, low average but daily 85% peak", spiky)
    print()


if __name__ == "__main__":
    main()
