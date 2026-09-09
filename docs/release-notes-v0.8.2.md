GitHub Actions pytest on a clean checkout. 0.8.1 still skipped the Crew-validator test but two handler tests read the operator’s prompt files.

## 0.8.2

`test_live_handlers_load_usage_and_stage_steer` and `test_stage6_isolated_child_compact_usage_steer_and_plan` now use fixture prompts, so CI does not depend on gitignored `KiroCrew-0.5.0/` or `~/.kiro`.

Install: `pip install` the `.whl` on this release, or clone and `setup.bat` / `./setup.sh`.

Details: [CHANGELOG.md](https://github.com/Chumbayoumba/cursor-crew-bridge/blob/main/CHANGELOG.md)
