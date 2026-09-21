# PR 47 final review and release preparation

This audit records review of the 2.19.2 integration / 0.16.2 controller candidate.
It does not claim a hardware soak or measured water delivery. The release's attached
`release-audit-v2.19.2.md` binds the final candidate SHA to completed validation and
the owner-authorized deployment scope.

## Reviewed changes

PR 47 separates its runtime improvements from PR 48's release-channel policy.
The original four review findings are addressed: MCP proposals carry declared
plumbing, native parameter forms use the number entities' bounds, version-only
guards inspect changed content, and controller-only candidates use an integration
tag that agrees with the manifest.

Final review of the additional controller changes reproduced and fixed three
upgrade regressions before publication:

- A partial HA startup could permanently shrink a legacy three-zone room to one
  zone. The descriptor now owns the zone inventory; sensor-only discovery remains
  provisional until authoritative configuration arrives.
- Zero daily counters and missing/expired history could erase a genuine older
  irrigation timestamp. Only an explicit saved anchor flag marks a timestamp as
  switch-on; ambiguous old timestamps retain their previous meaning.
- A raw comparison against legacy string or malformed excluded-volume values
  could abort controller startup. Migration retains the existing tolerant loading.

Each regression was reproduced against the reviewed code and covered by a test.
The final controller suite passed 308 tests; state migration passed 16 tests.

## Validation before final candidate assembly

The reviewed PR head passed 77 real Home Assistant tests, 365 frontend tests,
24 MCP tests and 338 lean integration tests (one Windows symlink test skipped).
Seven browser suites passed 65 workflow groups and 26 accessibility audits without
reported violations or runtime errors. A fresh frontend build reproduced all 33
packaged HTML files, including all three dashboard copies, byte-for-byte. Ruff,
Black and YAML validation passed. Final candidate checks and the private F1/F2
upgrade rehearsal are recorded in the SHA-bound release evidence.

## Production baseline and preservation requirements

A read-only inspection found two configured rooms, F1 and F2, each with three
zones. Live integration 2.18.0 and controller 0.15.1 matched the production source;
only old backup files were additional. Before deployment, snapshots captured both
config entries, entity identities, restored values, controller runtime state,
recipes, current code and the running controller image. These private snapshots
are excluded from Git.

The installed controller tracks the separate `JakeTheRabbit/f2-control` repository.
Its release must be published from the reviewed monorepo artifact and updated in
place, preserving the existing app identity and `/data`. Installing another app
from a staging URL would create a separate installation and is not this upgrade.

Verification requires unchanged room/zone mappings and numeric settings, preserved
runtime counters/timestamps, both rooms loaded, current controller heartbeats and
matching running code. F1 was disabled; F2 was enabled. Deployment must restore
those observed enable states after checking the upgraded installation.

## Release channel

`main` remains production. `testing` is the stable staging branch. Promotion checks
the exact candidate's successful Validate workflow, tag/version agreement,
fast-forward ancestry, frozen staging tip and explicit SHA-bound approval before
moving production. See [the release procedure](../RELEASING.md).

An isolated upgrade rehearsal checks software migration using copied live data;
it does not replace a physical catch test, a full grow-day soak or fault drills on
real plumbing. Those remain explicitly separate evidence requirements.
