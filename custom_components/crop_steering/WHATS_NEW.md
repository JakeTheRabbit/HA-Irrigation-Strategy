# What's new

The dashboard's **What's new** window shows these to the first person who opens the dashboard after
an update: every release since the last one it showed there, newest first, at most five. A new
installation has nothing to catch up on and shows none. **Help & tools → What's new** opens it
again at any time.

Every release adds its section at the top, in its release pull request. Write it for growers, not
for the people who build the system:

- **Two to five short lines**, one for each change a grower would notice: what they can now do or
  see, in plain words, not how it was built.
- **No entity ids, error codes, file names, pull request numbers or code.** The release notes and
  the changelog keep the detail, and the window links to them.
- **Put the small things together** as one last line: `Bug fixes and improvements.` A release with
  nothing a grower would notice has only that line.
- The heading is `## <version> - <release date, YYYY-MM-DD>`, and each line starts with `- `.

`tests/test_whats_new.py` checks the shape and the plain words, and that the newest section is the
version being released.

## 2.24.0 - 2026-09-26

- Nothing is watered while the pump, main line or a zone's valve is offline: the zone waits, and says which switch is missing.
- A room switched back on within a day carries on where it left off.
- Move a zone to any phase by hand, from its details.
- Every irrigation setting has a plain name, and a ? that explains it.
- Bug fixes and improvements.

## 2.23.0 - 2026-09-25

- The grow-day chart shows how today is tracking: each phase's target, yesterday or a typical day, and the rest of today.
- Repairs cards link straight to what their message means and what to do.
- Bug fixes and improvements.

## 2.22.0 - 2026-09-25

- A Stock tanks page counts your nutrient concentrates down batch by batch, and warns before they run low.
- The Overview reads at a glance: how fast each zone is drying, water against its daily limit, and valves in colour.
- Water use for each zone: today, this week and the whole grow.
- The tank card graphs its EC and pH.

## 2.21.0 - 2026-09-25

- The Overview opens on today's grow day: every zone's phases, shots and holds on one chart, with the next shot estimated.
- A calmer look, with bigger text, and colour only where it means something.
