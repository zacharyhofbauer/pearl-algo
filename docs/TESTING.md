# Testing & Lint

## Local
```bash
source .venv/bin/activate
pip install -e .[dev]
pytest
ruff check .
```

## CI
- GitHub Actions workflow `.github/workflows/ci.yml` runs lint + pytest on push/PR.

## Notes
- Tests mock minimal risk logic; broker/ib_insync integrations are not covered without live connectivity.
- Add fixtures/mocks for ib_insync when extending broker/provider tests.
