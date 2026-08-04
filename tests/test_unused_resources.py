"""Tests for unused resource detection."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from cloud_cost_analyzer.unused_resources import ResourceType, UnusedResourceScanner


def make_scanner():
    ec2 = MagicMock()
    return UnusedResourceScanner(ec2, "us-east-1"), ec2


class TestUnattachedVolumes:
    def test_finds_unattached_volume(self):
        scanner, ec2 = make_scanner()
        create_time = datetime.now(tz=timezone.utc) - timedelta(days=10)

        ec2.get_paginator.return_value.paginate.side_effect = [
            [{"Volumes": [{"VolumeId": "vol-001", "Size": 100, "VolumeType": "gp3", "CreateTime": create_time}]}],
            [{"Snapshots": []}],
            [{"Reservations": []}],
        ]
        ec2.describe_addresses.return_value = {"Addresses": []}

        findings = scanner._find_unattached_volumes()
        assert len(findings) == 1
        assert findings[0].resource_id == "vol-001"
        assert findings[0].resource_type == ResourceType.EBS_VOLUME
        assert findings[0].monthly_cost == 10.0  # 100 GB * $0.10

    def test_no_findings_when_no_available_volumes(self):
        scanner, ec2 = make_scanner()
        ec2.get_paginator.return_value.paginate.return_value = [{"Volumes": []}]

        findings = scanner._find_unattached_volumes()
        assert findings == []


class TestElasticIPs:
    def test_finds_unassociated_eip(self):
        scanner, ec2 = make_scanner()
        ec2.describe_addresses.return_value = {
            "Addresses": [
                {"AllocationId": "eipalloc-001", "PublicIp": "1.2.3.4"}
            ]
        }

        findings = scanner._find_unused_elastic_ips()
        assert len(findings) == 1
        assert findings[0].resource_id == "eipalloc-001"
        assert findings[0].monthly_cost == 3.65

    def test_skips_associated_eip(self):
        scanner, ec2 = make_scanner()
        ec2.describe_addresses.return_value = {
            "Addresses": [
                {"AllocationId": "eipalloc-002", "PublicIp": "5.6.7.8", "AssociationId": "eipassoc-001"}
            ]
        }

        findings = scanner._find_unused_elastic_ips()
        assert findings == []


class TestOldSnapshots:
    def test_finds_snapshot_older_than_cutoff(self):
        scanner, ec2 = make_scanner()
        old_time = datetime.now(tz=timezone.utc) - timedelta(days=120)

        ec2.get_paginator.return_value.paginate.return_value = [
            {"Snapshots": [{"SnapshotId": "snap-001", "StartTime": old_time, "VolumeSize": 200}]}
        ]

        findings = scanner._find_old_snapshots(days=90)
        assert len(findings) == 1
        assert findings[0].resource_id == "snap-001"
        assert findings[0].monthly_cost == 10.0  # 200 GB * $0.05

    def test_skips_recent_snapshot(self):
        scanner, ec2 = make_scanner()
        recent = datetime.now(tz=timezone.utc) - timedelta(days=30)

        ec2.get_paginator.return_value.paginate.return_value = [
            {"Snapshots": [{"SnapshotId": "snap-002", "StartTime": recent, "VolumeSize": 100}]}
        ]

        findings = scanner._find_old_snapshots(days=90)
        assert findings == []
