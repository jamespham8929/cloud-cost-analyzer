"""Scans for AWS resources that are running but not being used."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


class ResourceType(str, Enum):
    EBS_VOLUME = "EBS Volume"
    ELASTIC_IP = "Elastic IP"
    SNAPSHOT = "Snapshot"
    STOPPED_INSTANCE = "Stopped Instance"


@dataclass
class UnusedResourceFinding:
    resource_id: str
    resource_type: ResourceType
    description: str
    monthly_cost: float
    region: str
    days_unused: int


class UnusedResourceScanner:
    def __init__(self, ec2_client, region: str):
        self._ec2 = ec2_client
        self._region = region

    def scan(self) -> list[UnusedResourceFinding]:
        findings: list[UnusedResourceFinding] = []
        findings.extend(self._find_unattached_volumes())
        findings.extend(self._find_unused_elastic_ips())
        findings.extend(self._find_old_snapshots(days=90))
        findings.extend(self._find_stopped_instances(days=7))
        return sorted(findings, key=lambda f: f.monthly_cost, reverse=True)

    def _find_unattached_volumes(self) -> list[UnusedResourceFinding]:
        findings = []
        paginator = self._ec2.get_paginator("describe_volumes")
        for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
            for vol in page["Volumes"]:
                created = vol["CreateTime"]
                if isinstance(created, str):
                    created = datetime.fromisoformat(created)
                days_unused = (datetime.now(tz=timezone.utc) - created).days

                size_gb = vol["Size"]
                vol_type = vol.get("VolumeType", "gp2")
                cost_per_gb = 0.10 if vol_type == "gp3" else 0.10
                monthly_cost = size_gb * cost_per_gb

                findings.append(UnusedResourceFinding(
                    resource_id=vol["VolumeId"],
                    resource_type=ResourceType.EBS_VOLUME,
                    description=f"{size_gb} GB {vol_type}, unattached",
                    monthly_cost=monthly_cost,
                    region=self._region,
                    days_unused=days_unused,
                ))
        return findings

    def _find_unused_elastic_ips(self) -> list[UnusedResourceFinding]:
        findings = []
        response = self._ec2.describe_addresses(Filters=[{"Name": "domain", "Values": ["vpc"]}])
        for addr in response.get("Addresses", []):
            if addr.get("AssociationId"):
                continue
            findings.append(UnusedResourceFinding(
                resource_id=addr["AllocationId"],
                resource_type=ResourceType.ELASTIC_IP,
                description=f"Elastic IP {addr.get('PublicIp', '')} not associated",
                monthly_cost=3.65,
                region=self._region,
                days_unused=0,
            ))
        return findings

    def _find_old_snapshots(self, days: int = 90) -> list[UnusedResourceFinding]:
        findings = []
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)

        paginator = self._ec2.get_paginator("describe_snapshots")
        for page in paginator.paginate(OwnerIds=["self"]):
            for snap in page["Snapshots"]:
                start_time = snap["StartTime"]
                if isinstance(start_time, str):
                    start_time = datetime.fromisoformat(start_time)
                if start_time > cutoff:
                    continue

                age_days = (datetime.now(tz=timezone.utc) - start_time).days
                size_gb = snap.get("VolumeSize", 0)
                monthly_cost = size_gb * 0.05

                findings.append(UnusedResourceFinding(
                    resource_id=snap["SnapshotId"],
                    resource_type=ResourceType.SNAPSHOT,
                    description=f"{size_gb} GB snapshot, {age_days} days old",
                    monthly_cost=monthly_cost,
                    region=self._region,
                    days_unused=age_days,
                ))
        return findings

    def _find_stopped_instances(self, days: int = 7) -> list[UnusedResourceFinding]:
        findings = []
        paginator = self._ec2.get_paginator("describe_instances")
        for page in paginator.paginate(Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]):
            for reservation in page["Reservations"]:
                for inst in reservation["Instances"]:
                    name = next(
                        (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                        inst["InstanceId"],
                    )
                    findings.append(UnusedResourceFinding(
                        resource_id=inst["InstanceId"],
                        resource_type=ResourceType.STOPPED_INSTANCE,
                        description=f"{inst['InstanceType']} stopped ({name})",
                        monthly_cost=0.0,
                        region=self._region,
                        days_unused=0,
                    ))
        return findings
