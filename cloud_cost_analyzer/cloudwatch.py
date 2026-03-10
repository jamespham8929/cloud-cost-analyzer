"""Fetch a CPU utilization time series from CloudWatch and build a profile.

The temporal recommender needs the shape of the load, not a single average. That
means pulling the full series at a usable resolution. CloudWatch caps a single
GetMetricStatistics call at 1440 data points, so for multi-week windows we page
day by day.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .instance_catalog import vcpus_for
from .workload import UtilizationSample, WorkloadProfile, build_profile


def fetch_utilization_samples(
    cw_client,
    instance_id: str,
    days: int = 14,
    period_seconds: int = 3600,
) -> list[UtilizationSample]:
    end = datetime.now(tz=timezone.utc)
    samples: list[UtilizationSample] = []

    # Page one day at a time to stay under the 1440-point response limit.
    cursor = end - timedelta(days=days)
    while cursor < end:
        window_end = min(cursor + timedelta(days=1), end)
        resp = cw_client.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=cursor,
            EndTime=window_end,
            Period=period_seconds,
            Statistics=["Average"],
        )
        for point in resp.get("Datapoints", []):
            samples.append(UtilizationSample(
                timestamp=point["Timestamp"].timestamp(),
                cpu_utilization=point["Average"] / 100.0,  # percent -> fraction
            ))
        cursor = window_end

    return samples


def profile_instance(
    cw_client,
    instance_id: str,
    instance_type: str,
    days: int = 14,
) -> WorkloadProfile | None:
    vcpus = vcpus_for(instance_type)
    if vcpus is None:
        return None
    samples = fetch_utilization_samples(cw_client, instance_id, days)
    if len(samples) < 2:
        return None
    return build_profile(instance_type, vcpus, samples)
