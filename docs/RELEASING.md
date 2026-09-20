# Releasing

This controller opens valves and runs pumps on unattended crops. A bug that reaches a production room is not an error report, it is a dry or flooded bench found the next morning. The rule this document exists to enforce:

> **Nothing reaches a production room that has not run, unchanged, on real hardware first.**

CI is necessary and nowhere near sufficient. On one day in September 2026 this repository published four releases in under ten hours. 2.17.1 shipped nineteen minutes after 2.17.0 because "the room on/off control did nothing on a fresh 2.17.0 install", which its changelog records as "Found on the first live install". 2.18.0 was published one minute after its pull request merged. Every one of those builds was green. Four defects that survived all of them, including one that stopped the integration loading at all on Home Assistant older than 2026.5, are written up in [audits/2026-09-21-first-run-review.md](audits/2026-09-21-first-run-review.md). Production was the test environment. This process moves that job to a staging room.

## How an update actually reaches a box

Read this first. The two halves are delivered by different mechanisms, and only one of them has any gate at all today.

| Half | Delivered by | What triggers an update on a box |
| --- | --- | --- |
| Integration (`custom_components/`) | HACS | A **GitHub Release** on the repository the box tracks. A release marked *pre-release* is offered only where **Show beta versions** is switched on for this repository. HACS never installs by itself: someone presses Update. |
| Controller (`addons/f2_control/`) | Supervisor add-on store | `config.yaml` has no `image:` key, so Supervisor **builds the add-on on the box from the git branch it tracks**. An update is offered as soon as `version:` on that branch changes. With auto-update on, it installs itself. |

Three things follow, each checked against the Supervisor source (`supervisor/validate.py`, `supervisor/store/utils.py`, `supervisor/store/repository.py`):

1. **For the controller, the tracked branch *is* production.** `release.yml` runs *after* a release exists and cannot stop one. A push to a branch that production tracks, bumping `version:`, is a release of the part that drives the pump, with no tag, no review and no soak.
2. **A box can track a branch.** A repository URL may end in `#branch` (`https://github.com/<owner>/HA-Irrigation-Strategy#stable`).
3. **The repository string is the add-on's identity.** Supervisor names an add-on `<hash>_f2_control`, where the hash is taken from the repository string *exactly as entered, `#branch` included*. The same add-on installed from a different owner, or from the same repository with a different `#branch`, is a **different add-on with its own empty `/data`**: phase, daily counters, water history, learned peaks and the adopted setup all start again. Choose what a production box tracks **once, when it is installed**. Moving an existing box is a migration (below), never a casual edit.

## Channels

| Branch | Who tracks it | What may land on it |
| --- | --- | --- |
| `main` | Staging rooms only (`…#main`, HACS **Show beta versions** on) | Pull requests with every required check green. Never a direct push. |
| `stable` | Every production room (`…#stable`, beta versions off, **add-on auto-update off**) | Only a fast-forward to a commit that has passed the whole gate below. Never a commit of its own, never a force-push. |

A production room therefore cannot receive anything that was not first on `main`, built and run on a staging room, and deliberately promoted.

If you deploy from a fork of someone else's repository, the fork is your `stable`. Upstream's `main` and upstream's releases are *candidates*: pull them into your `main` on your schedule (see *Taking upstream changes*), never point a production room at them.

## Versions

- **A version number is never reused for different code.** If a candidate fails its soak, the fix gets the next patch number. Skipped numbers cost nothing; "which code is on this box?" having one answer is worth a great deal.
- A release is **born a pre-release and promoted by flipping it**, so the commit that ships is byte-for-byte the commit that soaked. Nothing is re-tagged or rebuilt at promotion.
- The integration and controller are released as a **pair**, named together in both changelogs. `tests/test_version_consistency.py` keeps `manifest.json`, `CHANGELOG.md` and the README badge in step, and the controller's `config.yaml` in step with its own changelog.
- Every release leads its changelog entry with **🌱 In plain English**, then **🔧 Technical notes**.

## The gate

### 1. Classify the change

The class sets the minimum soak. When in doubt, it is the higher class.

| Class | Touches | Minimum soak on staging |
| --- | --- | --- |
| **C0** | Docs, screenshots, tests only | None. CI green. |
| **C1** | Dashboard, translations, tooltips: nothing the controller reads | One photoperiod, visual check of every changed screen |
| **C2** | Integration behaviour: config flow, entities, setup rules, fused sensors | **2 full photoperiods** + the fresh-install drill |
| **C3** | The controller, the engine, the state file, setup adoption, the descriptor, entity ids, add-on options | **7 days** + every fault drill + a seeded upgrade fixture |

### 2. Automated checks, green on the exact commit

`bash tests/run_ci.sh` locally, and on GitHub every job of `Validate`: ruff, black, yamllint, vendored engine identical, the stub suite, the controller suite, the engine suite, **the real-Home-Assistant tier (`tests_ha/`)**, hassfest, HACS validation, the add-on image build, the dashboard build and browser checks, MCP.

A C2 or C3 change is not reviewable without:

- a `tests_ha/` test that fails without the change (the stubs in `tests/` cannot see a schema Home Assistant rejects, an API missing from an older Home Assistant, or an entity id Home Assistant assigns, and all three have shipped green);
- for anything touching persisted state, add-on options or entities, a **seeded snapshot of an old install** in `tests_ha/fixtures/` proving it still loads and nothing moves (see [TESTING.md](TESTING.md)).

### 3. Cut the candidate

```bash
git checkout main && git pull --ff-only          # the commit CI just passed
gh release create v2.19.0 --prerelease --target main \
  --title "2.19.0 (candidate)" \
  --notes "Candidate. Staging rooms only. Pair: controller 0.16.0."
```

Staging rooms now see it: HACS offers the pre-release, Supervisor offers the new controller version from `#main`. Production rooms see nothing.

### 4. Soak on a staging room, on real plumbing

A staging room is a real room you can afford to get wrong: real switch, real pump or valve, real probes, water going into a bucket or a sacrificial plant. Record what you did in `docs/audits/<date>-release-<version>.md` (the repository already keeps these; say what was exercised live and, just as plainly, what was not).

**Upgrade, engine off**

- [ ] Take a Supervisor backup of the controller add-on (it holds `/data`) and a Home Assistant backup.
- [ ] Snapshot every `number.`, `select.` and `switch.crop_steering_*` state before updating.
- [ ] Update both halves **in place from the current stable**. Never a fresh install standing in for an upgrade.
- [ ] Confirm the installed versions, the running module hashes and a current controller heartbeat. A copied file or a clean restart proves nothing.
- [ ] Diff the snapshot: **nothing the operator set has moved**, no entity has changed id, no repair issue has appeared.
- [ ] The controller log reads `setup revision N resumed after restart`, not `Setup changed; disarm…`. An update must never need the kill switch cycled unless the changelog says so in bold.

**Run**

- [ ] Dry run: kill switch OFF for one photoperiod. It decides and logs; no switch moves.
- [ ] Armed: the full grow-day, P0 → P1 → P2 → P3 → P0, including the counter reset at lights-on.
- [ ] Catch test: delivered volume against counted volume, within your tolerance. Pump or valve ON history is an electrical state; only caught water proves delivery.

**Fault drills (C3 always; C2 when the change is near them)**

- [ ] Restart Home Assistant core mid-day. Nothing opens while entities read unavailable; a room that was off stays off.
- [ ] Restart the controller with the kill switch ON. It resumes; irrigation is not stranded behind a disarm cycle.
- [ ] Reboot the host.
- [ ] Take the switch's device offline (pull its power or Wi-Fi). Fail closed: no shot, a clear reason.
- [ ] Turn the kill switch off mid-shot. The valve closes at once and only the delivered part is counted.
- [ ] Make a valve fail to close (or fake its read-back). The hardware hold latches and alerts.

**Fresh install drill (C2, C3)**

- [ ] On a blank Home Assistant, go through the wizard as a newcomer would, including one deliberate mistake (a switch left on). The controller must find, adopt and water the room with no YAML and no add-on `hardware` option.

**Rollback rehearsal (C3, and any release that changes the state file)**

- [ ] Restore the backup taken above and confirm the room resumes with its counters and phase intact. Rehearse this on staging; do not discover how rollback behaves on a production room.

### 5. Promote

Only when every box above is ticked and written down:

```bash
git checkout stable && git merge --ff-only v2.19.0 && git push origin stable
gh release edit v2.19.0 --prerelease=false --title "2.19.0"
```

`stable` now points at the exact commit that soaked. Production rooms are offered the pair. Update **one production room first**, watch it through a photoperiod, then the rest.

### 6. If the candidate fails

It stays a pre-release forever. Fix on `main` through a pull request, take the next version number, cut a new candidate, and **start the soak clock again**. A candidate that needed a fix has not soaked.

## Hotfixes

There is no path that skips staging. A hotfix is a C-class change like any other, with the shortest soak that class allows and no less than **one full photoperiod** for anything the controller reads.

If a production room is being harmed *now*, the response is not a forward fix:

1. **Kill switch OFF.** That is what it is for.
2. Roll that room back to the previous stable.
3. Then fix it properly, through the gate.

A fix written in a hurry and pushed straight to the branch production tracks is how the second bug gets there.

## Rolling back

- **Integration:** HACS → the repository → *Redownload* → choose the previous version → restart Home Assistant.
- **Controller:** restore the add-on backup taken before the update. For an add-on that is built on the box, Supervisor's backup holds the **built image as well as `/data`** (`export_image` / `import_image` in its source), so the old code *and* its counters and phase come back together. That is the reason the backup in step 4 is not optional.
- A release that changes the state file format must say in its changelog whether the previous controller can read the new file. `Controller._load_state` tolerates unknown keys precisely so that it can; keep it that way.

## Moving an existing box onto a different channel

Because the repository string is the add-on's identity, pointing an existing room at `…#stable`, or at a fork, installs a **second, empty** controller beside the first. To carry a room across without losing its state:

1. Kill switch OFF. Wait for any shot to finish. Stop the old controller.
2. Back up the old add-on and copy `state.json` out of its `/data`.
3. Add the new repository string, install the controller from it, **do not start it yet**.
4. Put `state.json` into the new add-on's `/data`, copy the add-on options across, then start it.
5. Confirm it logs `resumed after restart` with the right setup revision, and that the daily counters are the ones you copied.
6. Only then uninstall the old controller. Two controllers on one room is two things opening the same valve.

Do this on the staging room first.

## Taking upstream changes (when you deploy from a fork)

```bash
git fetch upstream
git checkout -b intake/upstream-$(date +%F) main
git merge upstream/main                  # resolve, run bash tests/run_ci.sh
```

Open it as a pull request into your `main` like any other change, classify it by what it touches (an upstream release that touches the controller is **C3**, whatever upstream called it), and take it through the gate. Upstream publishing a release is not evidence that it has run on hardware.

## Make the rules mechanical

People skip checklists at 11 pm. Repository settings do not.

- **Branch protection on `main` and `stable`:** require a pull request, require every `Validate` job, block force-pushes and deletion. On `stable`, restrict who can push to the people allowed to promote.
- **Required checks must include** *Real Home Assistant* and *Build f2-control add-on image*, not only lint.
- **Production boxes:** add-on auto-update OFF, HACS beta versions OFF, repository string ending `#stable`.
- **Worth building next:** a `promote` workflow (manual trigger) that refuses unless the tag's commit has a green `Validate` run and an audit file for that version exists, then fast-forwards `stable` and flips the pre-release. Until it exists, promotion is the two commands in step 5 and the discipline to run them last.
