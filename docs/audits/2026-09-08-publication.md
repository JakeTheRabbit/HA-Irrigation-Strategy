# GitHub publication preparation — 8 September 2026

Target: existing feat/f2-two-room branch of JakeTheRabbit/HA-Irrigation-Strategy. Main is the verified repository default; no merge or live Home Assistant deployment is included in this publication task.

- Refreshed four compiled-app screenshots: native room overview, combined planning curve, room setup and mobile overview. README links a current screenshot gallery.
- Archived20 superseded screenshots and the completed one-off archive script with hashes. Removed six byte-identical archive payloads from the publication tree; duplicate-manifest.json identifies each retained original.
- Archived eight unused generated UI modules after checking the app import graph. Removed unused cn and next-themes dependencies; npm reports zero known vulnerabilities for the installed dependency graph at this check.
- Kept two independently modified, untracked AiGrow pages outside the commit. Added a Docker context exclusion so a local controller build cannot accidentally ship that unrelated page.
- Updated documentation links, image references, repository map and GitHub Pages build workflow. Published product names and stable entity identifiers remain distinct.
- Refreshed full Python, frontend, production-build and browser verification before commit. See the validation record for coverage and runtime limits.

The working branch is unreleased. HACS and the hosted Pages demo use main/release artifacts until the changes are merged and their publication workflows run. The original local audit records remain historical evidence of what was and was not live-tested.

Publication: implementation commit9b7fc76 was pushed successfully to origin/feat/f2-two-room. The active-source whitespace check excludes archive bytes intentionally: archived setpoints.html retains its original final blank line and recorded hash. Fresh verification passed225 Python tests,55 frontend unit tests and36 browser workflow groups. All four screenshot captures were refreshed after the final build.
