# GitHub publication preparation — 8 September 2026

Target: existing feat/f2-two-room branch of JakeTheRabbit/HA-Irrigation-Strategy. Main is the verified repository default; no merge or live Home Assistant deployment is included in this publication task.

- Refreshed four compiled-app screenshots: native room overview, combined planning curve, room setup and mobile overview. README links a current screenshot gallery.
- Archived 20 superseded screenshots and the completed one-off archive script with hashes. Removed six byte-identical archive payloads from the publication tree; duplicate-manifest.json identifies each retained original.
- Archived eight unused generated UI modules after checking the app import graph. Removed unused cn and next-themes dependencies; npm reports zero known vulnerabilities for the installed dependency graph at this check.
- Kept two independently modified, untracked AiGrow pages outside the commit. Added a Docker context exclusion so a local controller build cannot accidentally ship that unrelated page.
- Updated documentation links, image references, repository map and GitHub Pages build workflow. Published product names and stable entity identifiers remain distinct.
- Refreshed full Python, frontend, production-build and browser verification before commit. See the validation record for coverage and runtime limits.

The working branch is unreleased. HACS and the hosted Pages demo use main/release artifacts until the changes are merged and their publication workflows run. The original local audit records remain historical evidence of what was and was not live-tested.

Publication: implementation commit 9b7fc76 was pushed successfully to origin/feat/f2-two-room. The active-source whitespace check excludes archive bytes intentionally: archived setpoints.html retains its original final blank line and recorded hash. Fresh verification passed 225 Python tests, 55 frontend unit tests and 36 browser workflow groups. All four screenshot captures were refreshed after the final build.


## CI follow-up

The initial GitHub run passed installation/package contracts, both Python versions, HACS/Hassfest and the controller image build. Its workspace browser suite exposed an environment dependency: the harness expected a developer preview server on port 5198. The harness now serves the checked-out compiled dashboard on its own ephemeral loopback port, closes that server after verification, and retains WORKSPACE_URL as an explicit override. All nine workspace groups passed locally using the owned server on port 49367, including fixture-only API traffic, native theme inheritance and refreshed screenshots. The other 27 browser groups had already passed in the initial Linux run.

GitHub Dependency Review is advisory in this repository and reported that its dependency graph API is unavailable. Its green job status is not evidence of a completed dependency review; the separate local npm audit reported zero known vulnerabilities at publication.
