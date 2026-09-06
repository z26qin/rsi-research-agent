# Task 0 Report: Repair Apodex Probe Regex Mode

## Status

Complete.

## Change

Updated `scripts/probe_apodex_gap.py` to invoke `git grep -P` instead of `git grep -E`. The existing `SIGNALS` table uses Perl-compatible tokens such as `\\b` and `\\s`; PCRE mode makes those patterns behave as intended without rewriting the signal definitions.

## TDD evidence

Before the change, the required RED test failed:

```text
uv run pytest tests/test_apodex_gap_probe.py::test_head_still_has_task_board_scaffold -q
1 failed
AssertionError: assert 'disk_task_board' in []
```

After the change:

- Focused probe tests: `uv run pytest tests/test_apodex_gap_probe.py -q` — 4 passed.
- Full suite: `uv run pytest -q` — 96 passed.

## Scope and concerns

Only the regex mode in the production probe was changed. No signal definitions, feature-plan files, or policy-loop code were modified. This relies on the repository's Git supporting `grep -P`, which is the behavior established by the task brief and current environment.
