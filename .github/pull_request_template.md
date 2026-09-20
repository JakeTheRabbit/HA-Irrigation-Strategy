<!--
One change per pull request, into `testing` (never `main`). See CONTRIBUTING.md.
If describing it needs the word "and", it is two pull requests.
-->

## 🌱 In plain English

<!-- What changes for the person running a room, and why. No jargon. -->

## 🔧 Technical notes

<!-- What changed in the code and why this way. Anything a reviewer would otherwise have to work out. -->

## Change class

<!-- docs/RELEASING.md. When in doubt, the higher one. -->

- [ ] **C0** docs, tests, CI only
- [ ] **C1** dashboard, translations, tooltips: nothing the controller reads
- [ ] **C2** integration behaviour: config flow, entities, setup rules, fused sensors
- [ ] **C3** controller, engine, state file, setup adoption, descriptor, entity ids, add-on options

## How it was tested

<!-- Which suites, and the new tests that fail without this change. -->

- **On real hardware:** <!-- exactly what was run on real plumbing, or "not run on hardware" -->
- **Existing installs:** <!-- what happens to a box that updates in place; name the seeded fixture if state, options or entities are touched -->

## Checklist

- [ ] One change. No unrelated fixes, no drive-by reformatting.
- [ ] Targets `testing`.
- [ ] Does **not** change a version number (only a `release/x.y.z` pull request does).
- [ ] Generated files (dashboard bundle, vendored engine copy) changed only together with their source.
- [ ] Nothing under `.github/`, no dependency or Dockerfile change, unless that is the whole pull request.
- [ ] C2/C3: proven in `tests_ha/`, not only against the stubs.
