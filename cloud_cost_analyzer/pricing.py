"""Storage prices used to put a monthly cost on idle resources.

Prices are us-east-1 on-demand list prices in USD. Other regions cost a little
more, so treat the numbers as a floor outside us-east-1. They are kept in one
table so a price change is a one-line edit with a test next to it.

Sources: the Amazon EBS pricing page, checked 2026-11.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EBSPrice:
    per_gb_month: float
    # gp3 includes a baseline of IOPS and throughput in the storage price and
    # bills only what is provisioned above it.
    included_iops: int = 0
    per_iops_month: float = 0.0
    included_throughput_mbps: int = 0
    per_mbps_month: float = 0.0


EBS_PRICES: dict[str, EBSPrice] = {
    "gp3": EBSPrice(
        per_gb_month=0.08,
        included_iops=3000,
        per_iops_month=0.005,
        included_throughput_mbps=125,
        per_mbps_month=0.04,
    ),
    "gp2": EBSPrice(per_gb_month=0.10),
    "io1": EBSPrice(per_gb_month=0.125, per_iops_month=0.065),
    # io2 IOPS pricing is tiered (cheaper above 32,000). The first tier is
    # used for every IOPS, so very large io2 volumes come out a little high.
    "io2": EBSPrice(per_gb_month=0.125, per_iops_month=0.065),
    "st1": EBSPrice(per_gb_month=0.045),
    "sc1": EBSPrice(per_gb_month=0.015),
    "standard": EBSPrice(per_gb_month=0.05),
}

# Standard-tier snapshot storage. Snapshots are incremental, so billing is on
# the blocks a snapshot actually holds. The API only reports the source volume
# size, which makes this an upper bound.
SNAPSHOT_PER_GB_MONTH = 0.05

# Every public IPv4 address costs $0.005 an hour, attached or not.
PUBLIC_IPV4_MONTHLY = 0.005 * 730


def ebs_monthly_cost(
    volume_type: str,
    size_gb: int,
    iops: int | None = None,
    throughput_mbps: int | None = None,
) -> float:
    """Monthly cost of one EBS volume, including provisioned performance.

    An unknown volume type is priced as gp2, the most common general purpose
    rate, rather than dropped. A finding with an approximate price is more
    useful than a missing one.
    """
    price = EBS_PRICES.get(volume_type, EBS_PRICES["gp2"])
    cost = size_gb * price.per_gb_month
    if iops and price.per_iops_month:
        cost += max(iops - price.included_iops, 0) * price.per_iops_month
    if throughput_mbps and price.per_mbps_month:
        cost += max(throughput_mbps - price.included_throughput_mbps, 0) * price.per_mbps_month
    return round(cost, 2)
