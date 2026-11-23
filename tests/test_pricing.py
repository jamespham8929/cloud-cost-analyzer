"""Tests for the EBS and storage price table."""

import pytest

from cloud_cost_analyzer.pricing import EBS_PRICES, ebs_monthly_cost


class TestEBSMonthlyCost:
    def test_gp3_is_cheaper_than_gp2_per_gb(self):
        # The original scanner priced every volume at the gp2 rate, which
        # overstated gp3 waste by 25%.
        assert ebs_monthly_cost("gp3", 100) == 8.0
        assert ebs_monthly_cost("gp2", 100) == 10.0

    def test_gp3_baseline_performance_is_free(self):
        assert ebs_monthly_cost("gp3", 100, iops=3000, throughput_mbps=125) == 8.0

    def test_gp3_bills_iops_and_throughput_above_baseline(self):
        # 100 GB * 0.08 + 2000 extra IOPS * 0.005 + 125 extra MB/s * 0.04
        assert ebs_monthly_cost("gp3", 100, iops=5000, throughput_mbps=250) == 8.0 + 10.0 + 5.0

    def test_io1_bills_every_provisioned_iops(self):
        # 100 GB * 0.125 + 1000 IOPS * 0.065
        assert ebs_monthly_cost("io1", 100, iops=1000) == 12.5 + 65.0

    def test_gp2_ignores_reported_iops(self):
        # gp2 reports a burst baseline in Iops, but it is not billed.
        assert ebs_monthly_cost("gp2", 100, iops=300) == 10.0

    @pytest.mark.parametrize("volume_type, per_gb", [
        ("st1", 0.045),
        ("sc1", 0.015),
        ("standard", 0.05),
    ])
    def test_hdd_and_magnetic_rates(self, volume_type, per_gb):
        assert ebs_monthly_cost(volume_type, 1000) == round(1000 * per_gb, 2)

    def test_unknown_type_falls_back_to_gp2(self):
        assert ebs_monthly_cost("gp9", 100) == 10.0

    def test_every_type_has_a_positive_storage_price(self):
        assert all(p.per_gb_month > 0 for p in EBS_PRICES.values())
