# cloud-cost-analyzer

A CLI tool that analyzes AWS usage data and produces a prioritized cost-reduction report. It identifies EC2 instances eligible for rightsizing, unused resources burning money silently, and coverage gaps in Reserved Instances and Savings Plans.

## What it checks

- **EC2 rightsizing**: compares CloudWatch CPU/memory utilization against the past 14 days and flags overprovisioned instances with recommended downsizes
- **Unused resources**: detects unattached EBS volumes, idle Elastic IPs, unused snapshots older than 90 days, and stopped instances
- **Savings Plans coverage**: pulls Cost Explorer coverage data and surfaces accounts or services with low on-demand spend that would benefit from a commitment

## Installation

Python 3.10+ required.

```bash
pip install -r requirements.txt
```

AWS credentials must be configured via environment variables, `~/.aws/credentials`, or an instance profile with read access to Cost Explorer, CloudWatch, and EC2.

## Usage

```bash
# Full analysis across all regions, output to terminal
python -m cloud_cost_analyzer.cli analyze

# Target a specific region and write a JSON report
python -m cloud_cost_analyzer.cli analyze --region us-east-1 --output report.json

# EC2 rightsizing only
python -m cloud_cost_analyzer.cli rightsize --region us-east-1 --lookback-days 14

# Unused resources only, CSV output
python -m cloud_cost_analyzer.cli unused --output unused.csv --format csv

# Savings Plans coverage summary
python -m cloud_cost_analyzer.cli coverage --period 30
```

## Sample output

```
=== EC2 Rightsizing Recommendations ===
i-0abc123 (m5.2xlarge, us-east-1a)
  Avg CPU: 4.2%  Peak CPU: 11.8%  → Recommend: m5.large  Savings: $87/mo

=== Unused Resources ===
vol-0def456  (EBS, 500 GB gp2, unattached 34 days)  → $50/mo
eipalloc-0789  (Elastic IP, no association)  → $3.60/mo

=== Monthly Savings Potential ===
Total identified: $1,240/mo  ($14,880/yr)
```

## Running tests

```bash
pip install pytest pytest-mock
pytest tests/ -v
```

## Required IAM permissions

```json
{
  "Effect": "Allow",
  "Action": [
    "ec2:Describe*",
    "cloudwatch:GetMetricStatistics",
    "cloudwatch:ListMetrics",
    "ce:GetCostAndUsage",
    "ce:GetSavingsPlansCoverage"
  ],
  "Resource": "*"
}
```

## License

MIT
