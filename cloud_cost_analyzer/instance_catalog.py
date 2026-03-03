"""Instance vCPU counts, keyed to the family ladder in ec2_rightsizing.

Kept in its own module so both the legacy average-based analyzer and the temporal
recommender share one source of truth for instance capacity.
"""

from __future__ import annotations

INSTANCE_VCPUS: dict[str, int] = {
    # Burstable. micro/small/medium/large all expose 2 vCPUs.
    "t3.micro": 2, "t3.small": 2, "t3.medium": 2, "t3.large": 2,
    "t3.xlarge": 4, "t3.2xlarge": 8,
    # General purpose
    "m5.large": 2, "m5.xlarge": 4, "m5.2xlarge": 8, "m5.4xlarge": 16,
    "m5.8xlarge": 32, "m5.12xlarge": 48,
    "m6i.large": 2, "m6i.xlarge": 4, "m6i.2xlarge": 8, "m6i.4xlarge": 16,
    "m6i.8xlarge": 32, "m6i.12xlarge": 48,
    # Compute optimized
    "c6i.large": 2, "c6i.xlarge": 4, "c6i.2xlarge": 8, "c6i.4xlarge": 16,
    "c6i.8xlarge": 32,
    # Memory optimized
    "r6i.large": 2, "r6i.xlarge": 4, "r6i.2xlarge": 8, "r6i.4xlarge": 16,
    "r6i.8xlarge": 32,
}


def vcpus_for(instance_type: str) -> int | None:
    return INSTANCE_VCPUS.get(instance_type)
