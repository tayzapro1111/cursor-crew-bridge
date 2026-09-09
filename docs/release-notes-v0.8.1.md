GitHub Actions pytest is green. 0.8.0 wheels still do the Crew ACP work; this tag is the test isolation that made the public CI badge honest.

## 0.8.1

Unit tests no longer read gitignored `KiroCrew-0.5.0/` or `~/.kiro`. The Crew-validator check skips when those sources are not in the checkout. `cursor-crew gateway` creates missing `config.json` instead of no-op.

Install: `pip install` the `.whl` on this release, or clone and `setup.bat` / `./setup.sh`.

Details: [CHANGELOG.md](https://github.com/Chumbayoumba/cursor-crew-bridge/blob/main/CHANGELOG.md)
