"""Entry point for the cloud-cost-analyzer CLI."""

import click
from rich.console import Console

from .analyzer import CostAnalyzer
from .report import ReportWriter

console = Console()


@click.group()
@click.option("--profile", default=None, help="AWS profile name")
@click.option("--region", default="us-east-1", show_default=True, help="AWS region")
@click.pass_context
def cli(ctx, profile, region):
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile
    ctx.obj["region"] = region


@cli.command()
@click.option("--lookback-days", default=14, show_default=True)
@click.option("--output", default=None, help="Write report to file")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json", "csv"]))
@click.pass_context
def analyze(ctx, lookback_days, output, fmt):
    """Run a full cost analysis: rightsizing, unused resources, and coverage."""
    analyzer = CostAnalyzer(
        region=ctx.obj["region"],
        profile=ctx.obj["profile"],
    )
    with console.status("Analyzing EC2 utilization..."):
        rightsize_findings = analyzer.get_rightsizing_recommendations(lookback_days)

    with console.status("Scanning for unused resources..."):
        unused_findings = analyzer.get_unused_resources()

    with console.status("Fetching Savings Plans coverage..."):
        coverage = analyzer.get_savings_plans_coverage(lookback_days)

    writer = ReportWriter(rightsize_findings, unused_findings, coverage)
    writer.render(fmt=fmt, output_path=output, console=console)


@cli.command()
@click.option("--lookback-days", default=14, show_default=True)
@click.option("--min-savings", default=10.0, help="Minimum monthly savings to report (USD)")
@click.pass_context
def rightsize(ctx, lookback_days, min_savings):
    """Show EC2 rightsizing recommendations only."""
    analyzer = CostAnalyzer(region=ctx.obj["region"], profile=ctx.obj["profile"])
    findings = analyzer.get_rightsizing_recommendations(lookback_days)
    findings = [f for f in findings if f.monthly_savings >= min_savings]

    if not findings:
        console.print("[green]No rightsizing opportunities found.[/green]")
        return

    for f in sorted(findings, key=lambda x: x.monthly_savings, reverse=True):
        console.print(f"[bold]{f.instance_id}[/bold] ({f.current_type} → {f.recommended_type}) "
                      f"  CPU avg {f.avg_cpu:.1f}%  savings ${f.monthly_savings:.0f}/mo")


@cli.command()
@click.option("--output", default=None)
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json", "csv"]))
@click.pass_context
def unused(ctx, output, fmt):
    """List unused resources (EBS, EIPs, snapshots, stopped instances)."""
    analyzer = CostAnalyzer(region=ctx.obj["region"], profile=ctx.obj["profile"])
    findings = analyzer.get_unused_resources()
    writer = ReportWriter([], findings, {})
    writer.render(fmt=fmt, output_path=output, console=console)


@cli.command()
@click.option("--period", default=30, show_default=True, help="Lookback period in days")
@click.pass_context
def coverage(ctx, period):
    """Show Savings Plans and Reserved Instance coverage gaps."""
    analyzer = CostAnalyzer(region=ctx.obj["region"], profile=ctx.obj["profile"])
    data = analyzer.get_savings_plans_coverage(period)
    console.print_json(data=data)


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
