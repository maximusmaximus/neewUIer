## What

<!-- Short description of the change. -->

## Checks

Local gate must be green before this PR is reviewable:

```bash
./scripts/check.sh
```

- [ ] `./scripts/check.sh` passes
- [ ] CI `python` + `node` + `ci` are green
- [ ] BLE / MQTT behaviour covered by a unit test or the shared HA fixtures
