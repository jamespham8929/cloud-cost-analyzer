# 1. Size from the recurring peak, not the average or a single percentile

Date: 2024-12-20

## Status

Accepted

## Context

Rightsizing tools size instances from a summary statistic of CPU utilization.
The two common choices both fail on the same workload:

- Average hides the daily spike. A service at 13% average can have a 9am peak of
  85%. Sizing from the average recommends an instance that gets throttled every
  morning.
- A single overall percentile (p95, p99) is sold as "robust to outliers," but on
  a spiky service it throws away the spike along with the outliers. If the daily
  peak occupies less than 5% of the day, the overall p95 sits down at baseline
  and the tool recommends a downsize that the peak will not fit into.

The benchmark in `benchmarks/naive_vs_temporal.py` reproduces this: a p95-based
sizer recommends m5.2xlarge -> m5.large on a service whose daily peak needs the
larger instance.

## Decision

Bucket utilization by hour of day and take the 75th percentile within each hour.
The recurring peak is the maximum of those per-hour values. This captures a peak
that recurs on most days while rejecting a one-off spike, which would have to
appear in more than a quarter of an hour's samples to move the number.

Size the instance so the recurring peak occupies at most a target fraction of its
capacity (default 65%), leaving headroom for spikes above the modeled peak and
for growth.

## Consequences

- A spiky service with a low average is no longer downsized into its own daily
  peak.
- A genuinely steady, underused service is still downsized, because its recurring
  peak is low.
- One-off spikes do not block a valid downsize, because the per-hour p75 absorbs
  them.
- The method needs the full time series, not a summary, so the CloudWatch fetch
  pages day by day to stay under the API's point limit. That is more API calls
  than reading a single average, a deliberate cost for a correct decision.
