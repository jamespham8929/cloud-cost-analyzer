"""Formats and writes analysis results in text, JSON, or CSV formats."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table


class ReportWriter:
    def __init__(self, rightsize_findings, unused_findings, coverage_data):
        self._rightsize = rightsize_findings
        self._unused = unused_findings
        self._coverage = coverage_data

    def render(self, fmt: str = "text", output_path: str | None = None, console: Console | None = None):
        if fmt == "json":
            data = self._to_dict()
            text = json.dumps(data, indent=2)
            if output_path:
                Path(output_path).write_text(text)
            else:
                (console or Console()).print_json(text)

        elif fmt == "csv":
            self._write_csv(output_path)

        else:
            self._render_text(console or Console())

    def _render_text(self, console: Console):
        if self._rightsize:
            console.rule("[bold]EC2 Rightsizing Recommendations[/bold]")
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Instance ID")
            table.add_column("Current Type")
            table.add_column("Recommended")
            table.add_column("Avg CPU %", justify="right")
            table.add_column("Peak CPU %", justify="right")
            table.add_column("Savings/mo", justify="right")

            for f in sorted(self._rightsize, key=lambda x: x.monthly_savings, reverse=True):
                table.add_row(
                    f.instance_id, f.current_type, f.recommended_type,
                    f"{f.avg_cpu:.1f}", f"{f.peak_cpu:.1f}", f"${f.monthly_savings:.0f}"
                )
            console.print(table)

        if self._unused:
            console.rule("[bold]Unused Resources[/bold]")
            table = Table(show_header=True, header_style="bold yellow")
            table.add_column("Resource ID")
            table.add_column("Type")
            table.add_column("Description")
            table.add_column("Cost/mo", justify="right")
            table.add_column("Days Unused", justify="right")

            for f in self._unused:
                table.add_row(
                    f.resource_id, f.resource_type.value,
                    f.description, f"${f.monthly_cost:.2f}", str(f.days_unused)
                )
            console.print(table)

        total_rightsize = sum(f.monthly_savings for f in self._rightsize)
        total_unused = sum(f.monthly_cost for f in self._unused)
        total = total_rightsize + total_unused

        console.rule("[bold green]Summary[/bold green]")
        console.print(f"  Rightsizing savings:   [green]${total_rightsize:,.0f}/mo[/green]")
        console.print(f"  Unused resource waste: [yellow]${total_unused:,.0f}/mo[/yellow]")
        console.print(f"  [bold]Total potential:       ${total:,.0f}/mo  (${total * 12:,.0f}/yr)[/bold]")

    def _to_dict(self) -> dict[str, Any]:
        return {
            "rightsizing": [
                {
                    "instance_id": f.instance_id,
                    "current_type": f.current_type,
                    "recommended_type": f.recommended_type,
                    "avg_cpu_pct": round(f.avg_cpu, 1),
                    "peak_cpu_pct": round(f.peak_cpu, 1),
                    "monthly_savings_usd": round(f.monthly_savings, 2),
                }
                for f in self._rightsize
            ],
            "unused_resources": [
                {
                    "resource_id": f.resource_id,
                    "type": f.resource_type.value,
                    "description": f.description,
                    "monthly_cost_usd": round(f.monthly_cost, 2),
                    "days_unused": f.days_unused,
                }
                for f in self._unused
            ],
            "coverage": self._coverage,
        }

    def _write_csv(self, output_path: str | None):
        rows = []
        for f in self._rightsize:
            rows.append({
                "resource_id": f.instance_id,
                "type": "EC2 Rightsize",
                "description": f"{f.current_type} → {f.recommended_type}",
                "monthly_impact_usd": round(f.monthly_savings, 2),
            })
        for f in self._unused:
            rows.append({
                "resource_id": f.resource_id,
                "type": f.resource_type.value,
                "description": f.description,
                "monthly_impact_usd": round(f.monthly_cost, 2),
            })

        if output_path:
            with open(output_path, "w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=["resource_id", "type", "description", "monthly_impact_usd"])
                writer.writeheader()
                writer.writerows(rows)
        else:
            import sys
            writer = csv.DictWriter(sys.stdout, fieldnames=["resource_id", "type", "description", "monthly_impact_usd"])
            writer.writeheader()
            writer.writerows(rows)
