# cloud-cost-analyzer

AWS cost analysis with a focus on the rightsizing decision that naive tools get
wrong: **a service with a low average but a sharp recurring peak.** It also covers
the cost basics (unused resources, Savings Plans coverage), but the rightsizing
is where the real work is.

## The problem

Rightsizing tools size an instance from a summary of its CPU utilization, and the
two common choices both fail on the same workload:

- **Average hides the peak.** A service at 13% average CPU can spike to 85% every
  morning at 9am. Size it from the average and the daily peak throttles it.
- **A single overall percentile throws the peak away.** p95 is sold as "robust to
  outliers," but if the daily spike is under 5% of the day, the overall p95 sits
  at baseline. The tool recommends a downsize the peak will not fit into, and
  calls it safe.

On top of that, most tools hand back a yes/no with no sense of how risky the
change is, so recommendations get either rubber-stamped or ignored.

## The approach

Model the temporal shape of the load, size from the recurring peak, and score the
risk.

1. **Recurring peak, not average.** Utilization is bucketed by hour of day and the
   75th percentile is taken within each hour. The recurring peak is the max of
   those. This keeps a peak that shows up day after day and rejects a one-off
   spike. See [ADR 0001](docs/adr/0001-size-from-recurring-peak.md).
2. **Headroom policy.** The recommended instance is sized so the recurring peak
   occupies at most a target fraction of it (default 65%), leaving room for spikes
   above the model and for growth.
3. **Confidence score and risk tier.** Each recommendation is scored from five
   transparent factors (data coverage, headroom margin, burstiness, volatility,
   trend) and sorted into safe, moderate, or risky. Only safe recommendations are
   marked actionable, and the reasons are spelled out. See [ADR 0002](docs/adr/0002-confidence-scored-recommendations.md).

## The case that matters

From [`benchmarks/naive_vs_temporal.py`](benchmarks/naive_vs_temporal.py), two
services with nearly the same low average:

```
=== steady service (safe to downsize) ===
  mean util 15%, overall p95 15%, recurring daily peak 15%
  naive (p95-based):  downsize to m5.large  -> daily peak lands at 60%
  temporal:           downsize to m5.large [safe, score 1.00], peak lands at 60%

=== spiky service, low average but daily 85% peak ===
  mean util 13%, overall p95 10%, recurring daily peak 85%
  naive (p95-based):  downsize to m5.large  -> WOULD THROTTLE on the daily peak
  temporal:           no downsize (recurring peak needs current capacity)
```

Both approaches agree the steady service is a safe downsize. They disagree on the
spiky one, and the naive answer is the one that causes a 9am incident. Reproduce:

```bash
PYTHONPATH=. python benchmarks/naive_vs_temporal.py
```

## Usage

```bash
pip install -r requirements.txt

# Temporal, confidence-scored rightsizing. Sizes from the recurring peak and
# shows the risk tier and the reasons behind each recommendation.
python -m cloud_cost_analyzer.cli rightsize-temporal --region us-east-1

# Only the recommendations scored safe to act on
python -m cloud_cost_analyzer.cli rightsize-temporal --safe-only

# The cost basics
python -m cloud_cost_analyzer.cli unused --region us-east-1
python -m cloud_cost_analyzer.cli coverage --period 30
```

AWS credentials come from the environment, `~/.aws/credentials`, or an instance
profile. The temporal command needs `cloudwatch:GetMetricStatistics` and
`ec2:DescribeInstances`.

## Layout

```
cloud_cost_analyzer/
  workload.py              temporal profiling: recurring peak, volatility, trend
  confidence.py            five-factor confidence model and risk tiers
  temporal_rightsizing.py  the recommender that ties them together
  instance_catalog.py      shared vCPU counts
  cloudwatch.py            pages the CPU series and builds a profile
  ec2_rightsizing.py       the legacy average-based analyzer, kept for comparison
  unused_resources.py      unattached EBS, idle EIPs, old snapshots
  savings_plans.py         coverage and purchase recommendations
docs/adr/                  why recurring peak, why confidence scoring
benchmarks/                naive vs temporal, reproducible
```

## Tests

```bash
pip install pytest pytest-mock
PYTHONPATH=. pytest tests/ -v
```

The core modeling (`workload.py`, `confidence.py`, `temporal_rightsizing.py`) has
no AWS dependency and is fully unit tested. The CloudWatch fetch takes a client as
an argument so it can be tested with a mock.

## Limitations

- Hour-of-day bucketing assumes a daily cycle. A workload whose pattern is weekly
  (a Monday batch job) is captured only at the resolution of its daily footprint.
  Day-of-week bucketing is a natural extension.
- Cost figures are approximate on-demand us-east-1 Linux prices, kept in a static
  table. They are good enough to rank recommendations, not to quote a bill.
- Memory and network are not yet modeled. CPU is the most common rightsizing
  constraint but not the only one.

## License

MIT
