# Contributing

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

Do not commit `.env`, `state.vscdb`, tokens, or `*.log`.

## Rules

- Preserve ACP behavior unless the change is covered by a test.
- Never log `CURSOR_AUTH_TOKEN` or `--auth-token` values. Use `redacted_argv`.
- Never send a bare `cursor-grok-4.6` model id.
- `discover_project_dir()` must keep working from a cloned folder (no hardcoded `D:\`).
- Docs stay factual. No invented star counts, benchmarks, or “#1” claims.

## PR checklist

- [ ] `pytest` passes
- [ ] New user-facing command is in `cursor-crew help` and README
- [ ] If you touch ACP translation, add a unit test
