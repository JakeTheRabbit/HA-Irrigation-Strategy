# Releasing

This controller opens valves and runs pumps on unattended crops. A bug that reaches a production room is not an error report, it is a dry or flooded bench found the next morning. The rule this document exists to enforce:

> **`main` is what production rooms run. Nothing lands on `main` that has not run, unchanged, on real hardware first.**

CI is necessary and nowhere near sufficient. On one day in September 2026 this repository published four releases in under ten hours. 2.17.1 shipped nineteen minutes after 2.17.0 because "the room on/off control did nothing on a fresh 2.17.0 install", which its changelog records as "Found on the first live install". 2.18.0 was published one minute after its pull request merged. Every one of those builds was green. Four defects that survived all of them, including one that stopped the integration loading at all on Home Assistant older than 2026.5, are written up in [audits/2026-09-21-first-run-review.md](audits/2026-09-21-first-run-review.md). Production was the test environment. This process moves that job to a staging room.

How a change gets *in* (one change, one branch, one pull request) is in [CONTRIBUTING.md](../CONTRIBUTING.md). This document is how it gets *out*.

## How an update actually reaches a box

Read this first. The two halves are delivered by different mechanisms, and only one of them has any gate at all by default.

| Half | Delivered by | What triggers an update on a box |
| --- | --- | --- |
| Integration (`custom_components/`) | HACS | A **GitHub Release** on the repository the box tracks. A release marked *pre-release* is offered only where **Show beta versions** is switched on for this repository. While a repository has no releases at all, HACS follows its default branch instead. HACS never installs by itself: someone presses Update. |
| Controller (`addons/f2_control/`) | Supervisor add-on store | `config.yaml` has no `image:` key, so Supervisor **builds the add-on on the box from the git branch it tracks**. An update is offered as soon as `version:` on that branch changes. With auto-update on, it installs itself. |

Four things follow, each checked against the Supervisor source (`supervisor/validate.py`, `supervisor/store/utils.py`, `supervisor/store/repository.py`, `supervisor/store/git.py`):

1. **For the controller, the tracked branch *is* the release channel.** `release.yml` runs *after* a release exists and cannot stop one. A push that changes `version:` on a branch boxes track is a release of the part that drives the pump, with no tag, no review and no soak.
2. **A box added by the plain address follows `main`, for life.** With no `#branch` on the end, Supervisor clones the repository's default branch, and from then on keeps pulling *the branch it cloned*. Every box ever installed from `https://github.com/<owner>/HA-Irrigation-Strategy` is on `main` and will stay there. That is why `main` has to be the stable branch: it already is what production runs. Never rename or delete `main`, and never change the default branch expecting boxes to follow.
3. **A box can track another branch.** A repository address may end in `#branch` (`https://github.com/<owner>/HA-Irrigation-Strategy#testing`). That is how a staging room gets code before production does.
4. **The repository address is the add-on's identity.** Supervisor names an add-on `<hash>_f2_control`, where the hash is taken from the address *exactly as entered, `#branch` included*. The same add-on installed from a different owner, or from the same repository with a different `#branch`, is a **different add-on with its own empty `/data`**: phase, daily counters, water history, learned peaks and the adopted setup all start again. Choose what a box tracks **once, when it is installed**. Moving an existing box is a migration (below), never a casual edit.

## Branches

| Branch | Who installs from it | What may land on it |
| --- | --- | --- |
| `main` | **Every production room.** Plain repository address, HACS *Show beta versions* **off**, add-on auto-update **off**. | Only a fast-forward to a commit on `testing` that has passed the whole gate below. Never a commit of its own, never a pull request from a feature branch, never a force-push, never GitHub's **Sync fork** button. |
| `testing` | Staging rooms only. Address ending `#testing`, HACS *Show beta versions* **on**. | Pull requests, one change each, every required check green, merged by someone other than their author ([CONTRIBUTING.md](../CONTRIBUTING.md)). Never a direct push. |
| `feat/…` `fix/…` `docs/…` `ci/…` `intake/…` `release/…` | Nobody. (A bench box may install from one to try it: a separate, empty controller. Stop every other controller on that box first.) | Anything. They are proposals, and they are deleted once merged. |

A production room therefore cannot receive anything that was not first on `testing`, built and run on a staging room, and deliberately promoted.

If you deploy from a fork of someone else's repository, **your fork's `main` is your production channel** and upstream is a supplier. Upstream's `main` and upstream's releases are *candidates*: bring them into your `testing` on your schedule (see *Taking upstream changes*), never point a production room at them, and never press **Sync fork** on `main`: that fast-forwards `main` to whatever upstream pushed last, which is a release to every production room with no gate at all.

## Versions

- **A version number is never reused for different code.** If a candidate fails its soak, the fix gets the next patch number. Skipped numbers cost nothing; "which code is on this box?" having one answer is worth a great deal.
- **Only a release pull request changes a version.** A feature or fix branch never touches `manifest.json`, `const.py` or the add-on's `config.yaml` version: on a tracked branch that one line is the release. A `release/x.y.z` pull request contains the version numbers, both changelogs and nothing else.
- A release is **born a pre-release and promoted by flipping it**, so the commit that ships is byte-for-byte the commit that soaked. Nothing is re-tagged or rebuilt at promotion.
- The integration and controller are released as a **pair**, named together in both changelogs. `tests/test_version_consistency.py` keeps `manifest.json`, `CHANGELOG.md` and the README badge in step, and the controller's `config.yaml` in step with its own changelog.
- Every release leads its changelog entry with **🌱 In plain English**, then **🔧 Technical notes**.

## The gate

### 1. Classify the change

Every pull request states its class. The class sets the minimum soak. When in doubt, it is the higher class.

| Class | Touches | Minimum soak on staging |
| --- | --- | --- |
| **C0** | Docs, screenshots, tests, CI only | None. CI green. |
| **C1** | Dashboard, translations, tooltips: nothing the controller reads | One photoperiod, visual check of every changed screen |
| **C2** | Integration behaviour: config flow, entities, setup rules, fused sensors | **2 full photoperiods** + the fresh-install drill |
| **C3** | The controller, the engine, the state file, setup adoption, the descriptor, entity ids, add-on options | **7 days** + every fault drill + a seeded upgrade fixture |

### 2. Automated checks, green on the exact commit

`bash tests/run_ci.sh` locally, and on GitHub every job of `Validate`: ruff, black, yamllint, vendored engine identical, the stub suite, the controller suite, the engine suite, **the real-Home-Assistant tier (`tests_ha/`)**, hassfest, HACS validation, the add-on image build, the dashboard build (**and proof that the committed dashboard file is exactly what `frontend/src` builds**), the browser checks, MCP.

A C2 or C3 change is not reviewable without:

- a `tests_ha/` test that fails without the change (the stubs in `tests/` cannot see a schema Home Assistant rejects, an API missing from an older Home Assistant, or an entity id Home Assistant assigns, and all three have shipped green);
- for anything touching persisted state, add-on options or entities, a **seeded snapshot of an old install** in `tests_ha/fixtures/` proving it still loads and nothing moves (see [TESTING.md](TESTING.md)).

### 3. Cut the candidate

**One behaviour change per candidate.** Any number of C0 and C1 changes may ride along, but a candidate carries at most one C2 or C3 change. When a soak fails, the question "which change did that?" must already be answered. An upstream release taken into a fork counts as one C3 change and soaks alone.

Open a `release/2.19.0` pull request into `testing` holding only the version numbers and both changelogs. When it is merged:

```bash
git checkout testing && git pull --ff-only       # the commit CI just passed
gh release create v2.19.0 --prerelease --target testing \
  --title "2.19.0 (candidate)" \
  --notes "Candidate. Staging rooms only. Pair: controller 0.16.0."
```

Staging rooms now see it: HACS offers the pre-release, Supervisor offers the new controller version from `#testing`. Production rooms see nothing, because `main` has not moved.

**`testing` is now frozen.** From the moment the release pull request merges until the candidate is promoted or abandoned, nothing else merges into `testing`. The reason is mechanical, not tidy-minded: HACS installs the integration from the *tag*, but Supervisor builds the controller from the *tip of the branch at the moment the box updates*. A feature merged behind a candidate carries no version change, so no box is offered it, but a staging room that installs, rebuilds or is restored after that merge builds the newer code **under the candidate's version number**, and what soaks is no longer what was tagged. Pull requests can still be opened, reviewed and checked during a soak; they wait to merge. One staging room can only soak one candidate at a time anyway, so the freeze costs review latency and nothing else. Make it mechanical: switch on **Lock branch** for `testing` when you cut the candidate, and off when it is promoted or abandoned. The one thing that merges into a frozen `testing` is the fix for a failed candidate (step 6).

### 4. Soak on a staging room, on real plumbing

A staging room is a real room you can afford to get wrong: real switch, real pump or valve, real probes, water going into a bucket or a sacrificial plant. Record what you did in `docs/audits/<date>-release-<version>.md` (the repository already keeps these; say what was exercised live and, just as plainly, what was not).

**Upgrade, engine off**

- [ ] Take a Supervisor backup of the controller add-on (it holds `/data`) and a Home Assistant backup.
- [ ] Snapshot every `number.`, `select.` and `switch.crop_steering_*` state before updating.
- [ ] Update both halves **in place from the previous release**. Never a fresh install standing in for an upgrade.
- [ ] Confirm the installed versions and a current controller heartbeat. A copied file or a clean restart proves nothing.
- [ ] **Prove the box is running the tagged code**, not a later tip of the branch. On the box (host console, or the *Advanced SSH & Web Terminal* add-on with protection mode off): `docker exec $(docker ps -qf name=f2_control) sha256sum /app/controller.py`. On your machine: `git show v2.19.0:addons/f2_control/f2_control/controller.py | sha256sum`. They must match. Write both into the audit file. If they differ, the soak has not started.
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
git fetch origin
git checkout main && git merge --ff-only v2.19.0 && git push origin main
gh release edit v2.19.0 --prerelease=false --title "2.19.0"
```

`main` now points at the exact commit that soaked, and because it only ever fast-forwards, `main` is always a point in `testing`'s own history. Production rooms are offered the pair. Update **one production room first**, watch it through a photoperiod, then the rest.

Promotion is a fast-forward from the command line on purpose. GitHub's merge button cannot fast-forward: every option it offers creates a new commit, so `main` would stop being the commit that soaked and the two branches would drift apart.

### 6. If the candidate fails

It stays a pre-release forever (put "abandoned" in its title) and `main` never sees it. Fix on a branch, through a pull request into the still-frozen `testing`, take the next version number, cut a new candidate, and **start the soak clock again**. A candidate that needed a fix has not soaked.

## Hotfixes

There is no path that skips staging. A hotfix is a C-class change like any other, with the shortest soak that class allows and no less than **one full photoperiod** for anything the controller reads.

If a production room is being harmed *now*, the response is not a forward fix:

1. **Kill switch OFF.** That is what it is for.
2. Roll that room back to the previous release.
3. Then fix it properly, through the gate.

A fix written in a hurry and pushed straight to the branch production tracks is how the second bug gets there.

## Rolling back

- **Integration:** HACS → the repository → *Redownload* → choose the previous version → restart Home Assistant.
- **Controller:** restore the add-on backup taken before the update. For an add-on that is built on the box, Supervisor's backup holds the **built image as well as `/data`** (`export_image` / `import_image` in its source), so the old code *and* its counters and phase come back together. That is the reason the backup in step 4 is not optional.
- `main` itself is never moved backwards. Production boxes that have not updated yet are protected by not pressing Update; the next promoted release carries the fix.
- A release that changes the state file format must say in its changelog whether the previous controller can read the new file. `Controller._load_state` tolerates unknown keys precisely so that it can; keep it that way.

## Moving an existing box onto a different address

Because the repository address is the add-on's identity, pointing an existing room at a fork, or adding `#testing` to a room that was installed without it, installs a **second, empty** controller beside the first. To carry a room across without losing its state:

1. Kill switch OFF. Wait for any shot to finish. Stop the old controller and switch off its *Start on boot*.
2. Back up the old add-on and copy `state.json` out of its `/data`.
3. Add the new repository address, install the controller from it, **do not start it yet**.
4. Put `state.json` into the new add-on's `/data`, copy the add-on options across, then start it.
5. Confirm it logs `resumed after restart` with the right setup revision, and that the daily counters are the ones you copied.
6. Only then uninstall the old controller. Two controllers on one room is two things opening the same valve.

Do this on the staging room first. A production room that was installed from *upstream's* address follows upstream's `main`, at upstream's pace, whatever this repository does: it is protected by this process only once it has been moved.

## Taking upstream changes (when you deploy from a fork)

```bash
git fetch https://github.com/<upstream-owner>/HA-Irrigation-Strategy.git main
git checkout -b intake/upstream-$(date +%F) origin/testing
git merge FETCH_HEAD                     # resolve, run bash tests/run_ci.sh
```

Open it as a pull request into `testing` like any other change. You cannot split someone else's release into small pull requests, so make up for it: read it commit by commit, classify it by what it touches (an upstream release that touches the controller is **C3**, whatever upstream called it), and soak it alone. Upstream publishing a release is not evidence that it has run on hardware.

## Make the rules mechanical

People skip checklists at 11 pm. Repository settings do not.

- **Protect `testing`:** require a pull request, require an approval from someone other than the author, require every `Validate` job (they must include *Real Home Assistant*, *Build f2-control add-on image* and *Dashboard build and browser workflows*, not only lint), require the branch to be up to date before merging, block force-pushes and deletion.
- **Protect `main`:** block force-pushes and deletion. It takes no pull requests at all: the only thing that ever arrives is a fast-forward, pushed by whoever is allowed to promote. On an organisation's repository, restrict pushes to those people. On a personal repository classic branch protection cannot do that (the *Restrict who can push* option exists only for organisations): anyone with write access can push, so keep write access to yourself, or use a ruleset with *Restrict updates* and yourself as the only bypass. (Not checked against GitHub's current settings pages; confirm when you set it up.)
- **Freeze `testing` during a soak** with *Lock branch* (step 3).
- **Production boxes:** plain repository address, add-on auto-update OFF, HACS beta versions OFF.
- **In place: the *Release guards* workflow** (`.github/scripts/release_guards.py`). On every pull request it fails a version change from a branch not named `release/<that version>` (an `intake/…` branch may carry upstream's), a release pull request that carries code, a version that goes down or reuses a tag, and any pull request into `main`. On every push to `main` it fails loudly unless the new tip is a fast-forward to the commit tagged `v<version>` that is already on `testing`; that one cannot prevent the push, it makes sure you hear about it at once. GitHub reads this workflow from **`main`**, so a pull request cannot switch it off, and a change to the guard itself only takes effect after a promotion.
- **Worth building next, each as its own pull request:**
  - a `promote` workflow (manual trigger) that refuses unless the tag's commit has a green `Validate` run and an audit file for that version exists, then fast-forwards `main` and flips the pre-release;
  - third-party GitHub Actions pinned to commit SHAs (`hassfest@master` and `hacs/action@main` float today, and a workflow runs with the repository's token).

  Until the `promote` workflow exists, promotion is the three commands in step 5 and the discipline to run them last.
