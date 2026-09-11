## What

<!-- Short description of the change. -->

## Checks

Nothing merges to `main` without a green `ci` job. Run the same gate locally:

```bash
./scripts/check.sh
```

- [ ] `./scripts/check.sh` passes (ruff, self-test, pytest+coverage, Node tests, `tsc`)
- [ ] CI `python` (3.10 + 3.12) + `node` + aggregate `ci` are green
- [ ] Behaviour is covered by a unit test or a row in `hub/tests/fixtures/ha-commands.json`
