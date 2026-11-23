"""Tests for the text, JSON, and CSV report writer."""

import csv
import io
import json

from rich.console import Console

from cloud_cost_analyzer.ec2_rightsizing import RightsizingFinding
from cloud_cost_analyzer.report import ReportWriter
from cloud_cost_analyzer.unused_resources import ResourceType, UnusedResourceFinding

RIGHTSIZE = [
    RightsizingFinding(
        instance_id="i-small", instance_name="web", current_type="m5.xlarge",
        recommended_type="m5.large", avg_cpu=12.3, peak_cpu=40.0,
        monthly_savings=70.0, region="us-east-1",
    ),
    RightsizingFinding(
        instance_id="i-big", instance_name="batch", current_type="m5.4xlarge",
        recommended_type="m5.2xlarge", avg_cpu=8.0, peak_cpu=30.0,
        monthly_savings=280.0, region="us-east-1",
    ),
]
UNUSED = [
    UnusedResourceFinding(
        resource_id="vol-1", resource_type=ResourceType.EBS_VOLUME,
        description="100 GB gp3, unattached", monthly_cost=8.0,
        region="us-east-1", days_unused=30,
    ),
]
COVERAGE = {"overall_coverage_pct": 60.0}


def _text_output(writer):
    buffer = io.StringIO()
    writer.render(fmt="text", console=Console(file=buffer, width=200, color_system=None))
    return buffer.getvalue()


class TestText:
    def test_lists_findings_and_totals(self):
        out = _text_output(ReportWriter(RIGHTSIZE, UNUSED, COVERAGE))
        assert "i-big" in out and "i-small" in out
        assert "vol-1" in out
        assert "$350/mo" in out   # rightsizing total
        assert "$8/mo" in out     # unused total
        assert "$358/mo" in out
        assert "$4,296/yr" in out

    def test_sorts_rightsizing_by_savings(self):
        out = _text_output(ReportWriter(RIGHTSIZE, [], {}))
        assert out.index("i-big") < out.index("i-small")

    def test_empty_report_still_prints_a_summary(self):
        out = _text_output(ReportWriter([], [], {}))
        assert "Rightsizing" in out
        assert "$0/mo" in out


class TestJSON:
    def test_writes_every_section_to_a_file(self, tmp_path):
        path = tmp_path / "report.json"
        ReportWriter(RIGHTSIZE, UNUSED, COVERAGE).render(fmt="json", output_path=str(path))
        data = json.loads(path.read_text())

        assert [r["instance_id"] for r in data["rightsizing"]] == ["i-small", "i-big"]
        assert data["rightsizing"][0]["monthly_savings_usd"] == 70.0
        assert data["unused_resources"][0] == {
            "resource_id": "vol-1",
            "type": "EBS Volume",
            "description": "100 GB gp3, unattached",
            "monthly_cost_usd": 8.0,
            "days_unused": 30,
        }
        assert data["coverage"] == COVERAGE

    def test_prints_to_the_console_without_a_path(self):
        buffer = io.StringIO()
        ReportWriter([], UNUSED, {}).render(
            fmt="json", console=Console(file=buffer, color_system=None)
        )
        assert json.loads(buffer.getvalue())["unused_resources"][0]["resource_id"] == "vol-1"


class TestCSV:
    def test_writes_one_row_per_finding(self, tmp_path):
        path = tmp_path / "report.csv"
        ReportWriter(RIGHTSIZE, UNUSED, {}).render(fmt="csv", output_path=str(path))
        with open(path, newline="") as fh:
            rows = list(csv.DictReader(fh))

        assert [r["resource_id"] for r in rows] == ["i-small", "i-big", "vol-1"]
        assert rows[0]["type"] == "EC2 Rightsize"
        assert rows[0]["description"] == "m5.xlarge → m5.large"
        assert rows[2]["monthly_impact_usd"] == "8.0"

    def test_writes_to_stdout_without_a_path(self, capsys):
        ReportWriter([], UNUSED, {}).render(fmt="csv")
        out = capsys.readouterr().out
        assert out.splitlines()[0] == "resource_id,type,description,monthly_impact_usd"
        assert "vol-1" in out
