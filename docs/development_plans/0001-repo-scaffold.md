# 0001 Repo Scaffold

## Goal

Create the initial AlphaBrief repository scaffold, project rules,
documentation shells, reference-source isolation, and minimal scaffold tests.

## Scope

This plan records the first development round required by the scaffold tests.
It is intentionally historical and does not introduce new runtime behavior.

## Expected Result

- Required root files exist.
- Required project directories exist.
- Reference sources remain isolated under `_reference_sources/` and ignored by Git.
- Live trading remains disabled by default.

## Validation

```bash
python3 -m pytest tests/test_project_scaffold.py
```
