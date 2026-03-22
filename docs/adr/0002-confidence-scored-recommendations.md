# 2. Attach a confidence score and risk tier to every recommendation

Date: 2025-01-10

## Status

Accepted

## Context

A rightsizing recommendation with no risk signal makes the human do the risk
assessment again before acting, which is the work the tool was supposed to do. In
practice that means recommendations get either rubber-stamped (and occasionally
cause an incident) or ignored wholesale (and the savings never land). Either way
the tool failed.

AWS Compute Optimizer attaches a confidence rating, but the model behind it is
opaque. An engineer cannot see why a recommendation is rated low, so they cannot
judge whether the reason applies to their service.

## Decision

Score each recommendation from 0 to 1 as a weighted blend of five factors, each
normalized so that 1 means low risk:

- data coverage (more history is more trustworthy)
- headroom margin (how much slack the recommended size leaves above the peak)
- burstiness (peak-to-mean ratio, since bursty load is risky to shrink)
- volatility (coefficient of variation)
- trend (utilization climbing means the headroom may be needed soon)

Headroom and burstiness carry the most weight because they are the two factors
most likely to turn a downsize into an incident. Map the score to a tier: safe
(>= 0.75), moderate, risky. Only safe recommendations are marked actionable.

The factor breakdown and a list of plain-language reasons are part of the output.
The number is never presented on its own.

## Consequences

- Safe wins can be actioned in bulk, and risky ones are held for review, which is
  the workflow that actually captures savings without causing incidents.
- The reasons make the score auditable. "Held back: bursty workload (peak/mean
  6.5x), only 2 days of data" is a sentence an engineer can act on.
- The weights are a judgment call, documented here so they can be challenged and
  tuned rather than hidden in code.
