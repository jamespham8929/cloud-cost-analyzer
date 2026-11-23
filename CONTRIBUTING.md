# Contributing

This project has the fullest test and CI setup in the portfolio, so the commands
below are the baseline the other projects follow.

## Setup

```bash
pip install -r requirements.txt
pip install pytest pytest-mock pytest-cov ruff==0.16.1
```

## Tests

Run the suite with coverage. CI enforces a 90% floor, so new code should keep the
total at or above that.

```bash
pytest tests/ -v --cov=cloud_cost_analyzer --cov-report=term-missing --cov-fail-under=90
```

The core modeling modules (`workload.py`, `confidence.py`,
`temporal_rightsizing.py`) have no AWS dependency and should stay fully unit
tested. Code that calls AWS takes its client as an argument, so tests pass a mock
instead of reaching the network.

## Lint

```bash
ruff check cloud_cost_analyzer/ tests/
```

Ruff is pinned in CI so a new release cannot change the rules underneath a green
build. Match that version locally when a lint result looks surprising.

## Before opening a pull request

- `pytest` passes and coverage stays at or above the floor.
- `ruff check` is clean.
- Each commit is focused and its message says what changed and why.

CI runs the same test and lint steps on Python 3.10 through 3.12. See
[.github/workflows/test.yml](.github/workflows/test.yml).
