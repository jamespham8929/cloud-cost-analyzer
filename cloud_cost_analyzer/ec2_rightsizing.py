"""EC2 rightsizing analysis using CloudWatch CPU utilization metrics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Ordered from smallest to largest within each family for downsize lookups
INSTANCE_FAMILY_LADDER: dict[str, list[str]] = {
    "m6i": ["m6i.large", "m6i.xlarge", "m6i.2xlarge", "m6i.4xlarge", "m6i.8xlarge", "m6i.12xlarge"],
    "m5":  ["m5.large", "m5.xlarge", "m5.2xlarge", "m5.4xlarge", "m5.8xlarge", "m5.12xlarge"],
    "c6i": ["c6i.large", "c6i.xlarge", "c6i.2xlarge", "c6i.4xlarge", "c6i.8xlarge"],
    "r6i": ["r6i.large", "r6i.xlarge", "r6i.2xlarge", "r6i.4xlarge", "r6i.8xlarge"],
    "t3":  ["t3.micro", "t3.small", "t3.medium", "t3.large", "t3.xlarge", "t3.2xlarge"],
}

# Approximate on-demand monthly cost per instance type (us-east-1, Linux)
MONTHLY_COST: dict[str, float] = {
    "t3.micro": 7.59, "t3.small": 15.18, "t3.medium": 30.37, "t3.large": 60.74,
    "m5.large": 69.12, "m5.xlarge": 138.24, "m5.2xlarge": 276.48, "m5.4xlarge": 552.96,
    "m6i.large": 69.12, "m6i.xlarge": 138.24, "m6i.2xlarge": 276.48, "m6i.4xlarge": 552.96,
    "c6i.large": 61.20, "c6i.xlarge": 122.40, "c6i.2xlarge": 244.80, "c6i.4xlarge": 489.60,
    "r6i.large": 91.98, "r6i.xlarge": 183.96, "r6i.2xlarge": 367.92, "r6i.4xlarge": 735.84,
}

# Thresholds for rightsizing decisions
CPU_LOW_THRESHOLD = 20.0  # avg CPU below this triggers a downsize check
CPU_PEAK_THRESHOLD = 40.0  # peak CPU must also be below this to recommend downsize


@dataclass
class RightsizingFinding:
    instance_id: str
    instance_name: str
    current_type: str
    recommended_type: str
    avg_cpu: float
    peak_cpu: float
    monthly_savings: float
    region: str


class EC2RightsizingAnalyzer:
    def __init__(self, ec2_client, cw_client, region: str):
        self._ec2 = ec2_client
        self._cw = cw_client
        self._region = region

    def analyze(self, lookback_days: int = 14) -> list[RightsizingFinding]:
        instances = self._get_running_instances()
        findings: list[RightsizingFinding] = []

        for inst in instances:
            avg_cpu, peak_cpu = self._get_cpu_stats(inst["InstanceId"], lookback_days)
            if avg_cpu is None:
                continue

            recommendation = self._recommend_downsize(inst["InstanceType"], avg_cpu, peak_cpu)
            if recommendation is None:
                continue

            current_cost = MONTHLY_COST.get(inst["InstanceType"], 0)
            recommended_cost = MONTHLY_COST.get(recommendation, 0)
            savings = current_cost - recommended_cost

            if savings <= 0:
                continue

            name = next(
                (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                inst["InstanceId"],
            )

            findings.append(RightsizingFinding(
                instance_id=inst["InstanceId"],
                instance_name=name,
                current_type=inst["InstanceType"],
                recommended_type=recommendation,
                avg_cpu=avg_cpu,
                peak_cpu=peak_cpu,
                monthly_savings=savings,
                region=self._region,
            ))

        return findings

    def _get_running_instances(self) -> list[dict]:
        instances = []
        paginator = self._ec2.get_paginator("describe_instances")
        for page in paginator.paginate(Filters=[{"Name": "instance-state-name", "Values": ["running"]}]):
            for reservation in page["Reservations"]:
                instances.extend(reservation["Instances"])
        return instances

    def _get_cpu_stats(self, instance_id: str, lookback_days: int) -> tuple[float | None, float | None]:
        end_time = datetime.now(tz=timezone.utc)
        start_time = end_time - timedelta(days=lookback_days)

        common = {
            "Namespace": "AWS/EC2",
            "MetricName": "CPUUtilization",
            "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
            "StartTime": start_time,
            "EndTime": end_time,
            "Period": 3600,
        }

        avg_resp = self._cw.get_metric_statistics(**common, Statistics=["Average"])
        peak_resp = self._cw.get_metric_statistics(**common, Statistics=["Maximum"])

        avg_points = [p["Average"] for p in avg_resp.get("Datapoints", [])]
        peak_points = [p["Maximum"] for p in peak_resp.get("Datapoints", [])]

        if not avg_points:
            return None, None

        return sum(avg_points) / len(avg_points), max(peak_points)

    def _recommend_downsize(
        self, current_type: str, avg_cpu: float, peak_cpu: float
    ) -> str | None:
        if avg_cpu >= CPU_LOW_THRESHOLD or peak_cpu >= CPU_PEAK_THRESHOLD:
            return None

        family = re.match(r"([a-z0-9]+\.[a-z0-9]*[a-z])", current_type)
        if not family:
            return None

        family_name = family.group(1).rsplit(".", 1)[0]
        ladder = INSTANCE_FAMILY_LADDER.get(family_name)
        if not ladder:
            return None

        try:
            idx = ladder.index(current_type)
        except ValueError:
            return None

        if idx == 0:
            return None  # already smallest in family

        return ladder[idx - 1]
