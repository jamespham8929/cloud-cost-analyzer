"""Entry point for the cloud-cost-analyzer CLI."""

import click
from rich.console import Console
from rich.table import Table

from .analyzer import CostAnalyzer
from .report import ReportWriter

console = Console()

_TIER_COLOR = {"safe": "green", "moderate": "yellow", "risky": "red"}


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


@cli.command("rightsize-temporal")
@click.option("--lookback-days", default=14, show_default=True)
@click.option("--target-peak", default=0.65, show_default=True,
              help="Max fraction of the instance the recurring peak may occupy")
@click.option("--safe-only", is_flag=True, help="Only show recommendations scored safe")
@click.pass_context
def rightsize_temporal(ctx, lookback_days, target_peak, safe_only):
    """Temporal, confidence-scored rightsizing.

    Sizes each instance from its recurring daily peak rather than its average,
    and attaches a risk tier so the safe wins are separable from the gambles.
    """
    import boto3

    from .cloudwatch import profile_instance
    from .temporal_rightsizing import TemporalRightsizer

    session = boto3.Session(profile_name=ctx.obj["profile"], region_name=ctx.obj["region"])
    ec2 = session.client("ec2")
    cw = session.client("cloudwatch")
    rightsizer = TemporalRightsizer(target_peak_utilization=target_peak)

    table = Table(show_header=True, header_style="bold")
    for col in ("Instance", "Current", "Recommended", "Daily peak", "Risk", "Score", "Savings/mo", "Why"):
        table.add_column(col)

    paginator = ec2.get_paginator("describe_instances")
    pages = paginator.paginate(Filters=[{"Name": "instance-state-name", "Values": ["running"]}])
    for page in pages:
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                profile = profile_instance(cw, inst["InstanceId"], inst["InstanceType"], lookback_days)
                if profile is None:
                    continue
                rec = rightsizer.recommend(profile)
                if rec is None:
                    continue
                if safe_only and not rec.is_actionable:
                    continue

                tier = rec.confidence.tier.value
                color = _TIER_COLOR.get(tier, "white")
                table.add_row(
                    inst["InstanceId"],
                    rec.instance_type,
                    rec.recommended_type,
                    f"{rec.recurring_peak_util:.0%}",
                    f"[{color}]{tier}[/{color}]",
                    f"{rec.confidence.score:.2f}",
                    f"${rec.monthly_savings:.0f}",
                    "; ".join(rec.confidence.reasons) or "clean",
                )

    console.print(table)


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
@click.option("--recommend", is_flag=True, help="Also show Savings Plans purchase recommendations")
@click.pass_context
def coverage(ctx, period, recommend):
    """Show Savings Plans coverage gaps, and optionally purchase recommendations."""
    analyzer = CostAnalyzer(region=ctx.obj["region"], profile=ctx.obj["profile"])
    data = analyzer.get_savings_plans_coverage(period)
    console.print_json(data=data)

    if recommend:
        recs = analyzer.get_savings_plans_recommendations(period)
        if not recs:
            console.print("[green]No Savings Plans purchase recommendations.[/green]")
            return
        table = Table(show_header=True, header_style="bold")
        for col in ("Commitment", "Term", "Payment", "$/hr", "Est. savings/mo"):
            table.add_column(col)
        for r in recs:
            table.add_row(
                r.commitment_type, r.term, r.payment_option,
                f"${r.hourly_commitment:.2f}", f"${r.estimated_monthly_savings:.0f}",
            )
        console.print(table)


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
