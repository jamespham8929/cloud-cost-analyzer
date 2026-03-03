"""Confidence scoring for rightsizing recommendations.

A rightsizing tool that emits a downsize with no risk signal forces a human to
re-derive the risk before acting, or worse, to act blindly. This module scores
each recommendation from 0 to 1 and sorts it into a risk tier, so the safe wins
can be actioned and the risky ones held for review.

The score is a weighted blend of five factors, each normalized to [0, 1] where 1
is "low risk." The factors are deliberately transparent: the breakdown is part of
the output so a reviewer can see exactly why a recommendation scored the way it
did, rather than trusting an opaque number.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .workload import WorkloadProfile


class RiskTier(str, Enum):
    SAFE = "safe"          # act on it
    MODERATE = "moderate"  # review before acting
    RISKY = "risky"        # do not downsize without strong justification


# Weights sum to 1.0. Headroom and burstiness dominate because they are the two
# factors most likely to cause a downsize to cause an incident.
WEIGHTS = {
    "data_coverage": 0.15,
    "headroom_margin": 0.30,
    "burstiness": 0.25,
    "volatility": 0.15,
    "trend": 0.15,
}

IDEAL_COVERAGE_DAYS = 14.0


@dataclass(frozen=True)
class ConfidenceBreakdown:
    data_coverage: float
    headroom_margin: float
    burstiness: float
    volatility: float
    trend: float

    def weighted_score(self) -> float:
        return (
            WEIGHTS["data_coverage"] * self.data_coverage
            + WEIGHTS["headroom_margin"] * self.headroom_margin
            + WEIGHTS["burstiness"] * self.burstiness
            + WEIGHTS["volatility"] * self.volatility
            + WEIGHTS["trend"] * self.trend
        )


@dataclass(frozen=True)
class ConfidenceResult:
    score: float
    tier: RiskTier
    breakdown: ConfidenceBreakdown
    reasons: tuple[str, ...]


def score_recommendation(
    profile: WorkloadProfile,
    recommended_vcpus: int,
    target_peak_utilization: float,
) -> ConfidenceResult:
    """Score a proposed downsize to `recommended_vcpus`.

    `target_peak_utilization` is the headroom policy: the fraction of the new
    instance the recurring peak is allowed to occupy.
    """
    reasons: list[str] = []

    coverage = _clamp(profile.coverage_days / IDEAL_COVERAGE_DAYS)
    if profile.coverage_days < 7:
        reasons.append(f"only {profile.coverage_days:.1f} days of data")

    # Peak compute demand in vCPU-equivalents, and what fraction of the proposed
    # instance it would occupy. Lower projected utilization means more slack.
    peak_demand_vcpus = profile.recurring_peak_util * profile.vcpus
    projected_peak_util = peak_demand_vcpus / recommended_vcpus if recommended_vcpus else 1.0
    # Margin score: 1.0 when projected peak is comfortably under target, 0 when
    # it meets or exceeds the instance's capacity.
    headroom_margin = _clamp((1.0 - projected_peak_util) / (1.0 - target_peak_utilization))
    if projected_peak_util > target_peak_utilization:
        reasons.append(
            f"projected peak {projected_peak_util:.0%} exceeds target headroom "
            f"{target_peak_utilization:.0%}"
        )

    burstiness = _clamp(1.0 - (profile.peak_to_mean - 1.0) / 4.0)  # 1x->1.0, 5x->0.0
    if profile.is_bursty:
        reasons.append(f"bursty workload (peak/mean {profile.peak_to_mean:.1f}x)")

    volatility = _clamp(1.0 - profile.volatility)  # CV of 0 -> 1.0, CV >= 1 -> 0
    if profile.volatility > 0.5:
        reasons.append(f"high volatility (CV {profile.volatility:.2f})")

    if profile.trend_per_day <= 0:
        trend = 1.0
    else:
        trend = _clamp(1.0 - profile.trend_per_day / 0.02)  # +2pp/day -> 0
        reasons.append(f"utilization trending up {profile.trend_per_day * 100:.1f}pp/day")

    breakdown = ConfidenceBreakdown(
        data_coverage=coverage,
        headroom_margin=headroom_margin,
        burstiness=burstiness,
        volatility=volatility,
        trend=trend,
    )
    score = breakdown.weighted_score()
    return ConfidenceResult(
        score=score,
        tier=_tier(score),
        breakdown=breakdown,
        reasons=tuple(reasons),
    )


def _tier(score: float) -> RiskTier:
    if score >= 0.75:
        return RiskTier.SAFE
    if score >= 0.50:
        return RiskTier.MODERATE
    return RiskTier.RISKY


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))
