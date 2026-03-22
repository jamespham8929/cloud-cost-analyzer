# Benchmarks

## naive_vs_temporal.py

Builds two synthetic 14-day workloads with nearly identical low averages, one
steady and one with a sharp daily peak, and runs both a p95-based rightsizer and
the temporal recommender against each.

```bash
PYTHONPATH=. python benchmarks/naive_vs_temporal.py
```

The point it makes: the two approaches agree on the steady service and disagree on
the spiky one. The naive recommendation for the spiky service is a downsize that
the daily peak would throttle, which the temporal recommender refuses because the
recurring peak needs the current capacity.

The workloads are constructed deterministically, so the output is stable across
runs. This is a demonstration of the decision logic, not a performance benchmark.
