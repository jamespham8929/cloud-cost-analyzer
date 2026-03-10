"""Temporal, confidence-scored rightsizing.

The naive recommender downsizes when average CPU is low and peak CPU is low. It
gets two things wrong:

  1. It sizes from a single peak number, so one outlier scrape blocks a valid
     downsize, and a service whose average is low but whose daily peak is high
     gets wrongly downsized.
  2. It hands back a yes/no with no sense of how safe the change is.

This recommender sizes the instance from the recurring daily peak with an
explicit headroom policy, then attaches a confidence score and a risk tier so the
safe wins are separable from the gambles.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .confidence import ConfidenceResult, RiskTier, score_recommendation
from .ec2_rightsizing import INSTANCE_FAMILY_LADDER, MONTHLY_COST
from .instance_catalog import INSTANCE_VCPUS
from .workload import WorkloadProfile

# Default headroom: the recurring peak may occupy at most 65% of the instance,
# leaving 35% for spikes above the modeled peak and for growth.
DEFAULT_TARGET_PEAK_UTILIZATION = 0.65


@dataclass(frozen=True)
class TemporalRecommendation:
    instance_type: str
    recommended_type: str
    current_vcpus: int
    recommended_vcpus: int
    recurring_peak_util: float
    projected_peak_util: float       # peak util on the recommended instance
    monthly_savings: float
    confidence: ConfidenceResult

    @property
    def is_actionable(self) -> bool:
        return self.confidence.tier == RiskTier.SAFE and self.monthly_savings > 0


class TemporalRightsizer:
    def __init__(self, target_peak_utilization: float = DEFAULT_TARGET_PEAK_UTILIZATION):
        if not 0 < target_peak_utilization < 1:
            raise ValueError("target_peak_utilization must be between 0 and 1")
        self._target = target_peak_utilization

    def recommend(self, profile: WorkloadProfile) -> TemporalRecommendation | None:
        family = self._family(profile.instance_type)
        ladder = INSTANCE_FAMILY_LADDER.get(family)
        if not ladder:
            return None

        # Peak compute demand in vCPU-equivalents, plus the headroom policy.
        peak_demand_vcpus = profile.recurring_peak_util * profile.vcpus
        required_vcpus = peak_demand_vcpus / self._target

        candidate = self._smallest_fitting(ladder, required_vcpus)
        if candidate is None:
            return None

        candidate_vcpus = INSTANCE_VCPUS[candidate]
        if candidate_vcpus >= profile.vcpus:
            return None  # already right-sized or would be an upsize

        current_cost = MONTHLY_COST.get(profile.instance_type, 0.0)
        candidate_cost = MONTHLY_COST.get(candidate, 0.0)
        savings = current_cost - candidate_cost
        if savings <= 0:
            return None

        projected_peak_util = peak_demand_vcpus / candidate_vcpus
        confidence = score_recommendation(profile, candidate_vcpus, self._target)

        return TemporalRecommendation(
            instance_type=profile.instance_type,
            recommended_type=candidate,
            current_vcpus=profile.vcpus,
            recommended_vcpus=candidate_vcpus,
            recurring_peak_util=profile.recurring_peak_util,
            projected_peak_util=projected_peak_util,
            monthly_savings=savings,
            confidence=confidence,
        )

    def _smallest_fitting(self, ladder: list[str], required_vcpus: float) -> str | None:
        # Ladder is smallest to largest. Pick the first instance whose vCPUs meet
        # the requirement (ceil so we never under-provision on a fractional need).
        need = math.ceil(required_vcpus)
        for instance_type in ladder:
            if INSTANCE_VCPUS.get(instance_type, 0) >= need:
                return instance_type
        return None

    def _family(self, instance_type: str) -> str | None:
        m = re.match(r"([a-z0-9]+)\.", instance_type)
        return m.group(1) if m else None
