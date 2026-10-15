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

## 3.11.1 - 2026-10-06

- The re-water point and the rescue floor now always stay in the right order under field capacity, even when they all move down together.
- After an update, the targets wait for the next lights-on before they follow the highest reading.
- Bug fixes and improvements.

## 3.11.0 - 2026-10-06

- Each morning a zone's P1 target is its highest reading of the day before, with no limit on how far it moves.
- The morning ramp now goes to the target, gives one more shot, and stops only when a shot no longer raises the reading.
- Field capacity, the re-water point and the rescue floor move together with the highest reading.
- Bug fixes and improvements.

## 3.10.0 - 2026-10-06

- A zone whose pore EC runs high is now flushed whenever its table drains, even when its probe reads very wet.
- Field capacity now follows what the probe reads, and goes up the same day the probe reads higher.
- When it moves, the P1 target, the re-water point and the rescue floor move with it, so the dryback stays the same.
- Bug fixes and improvements.

## 3.9.0 - 2026-10-05

- Each zone's P1 target and field capacity are kept up to date again, rising at most 2 points a day and only after a morning ramp reached them.
- Jev answers more often: it retries, asks another way when the first fails, and takes a second look when it is unsure.
- A stock tank linked to a dosing pump now goes down by what the pump pumps. After updating, read each tank's level and press Set level once.
- Tank & pump has a chart of the tank level over a day, 3 days or a week, with every shot, pump run and fill. Tap the zone chart's key to hide a line.
- Bug fixes and improvements.

## 3.8.0 - 2026-09-30

- A critical alert when a zone's moisture rises with no water going in: its table isn't draining.
- A critical alert when the sump pump hasn't run for three hours, once its power sensor is set in the controller app.
- A zone whose table isn't draining gets no daily minimum until it has drained.
- Bug fixes and improvements.

## 3.7.0 - 2026-09-30

- A zone's minimum water per plant per day is now spread evenly through the day, instead of all at lights-on.
- It waits out the morning dryback, catches up in the ramp, and is all in three hours before lights-off.
- Bug fixes and improvements.

## 3.6.0 - 2026-09-30

- Choose who gets which alerts: a row of checkboxes for each phone, and the rooms it covers, on Settings & help › Notifications.
- New pushes to tick: a room that has watered nothing for a few hours with its lights on, a zone changing phase, and Jev moving a setting.
- Tapping a push opens Crop Steering, and an emergency always reaches a phone, even when nobody ticked it for that room.
- Bug fixes and improvements.

## 3.5.0 - 2026-09-28

- Dose a nutrient pump or make a whole batch from the new Dosing page, one per room's tank.
- Stock tanks now follow what was actually dosed, and each pump shows how much is left.
- A batch holds watering, and Stop works at any step.
- Bug fixes and improvements.

## 3.4.2 - 2026-09-28

- A pump plug that is slow to report it has switched off no longer stops the room's watering.
- Bug fixes and improvements.

## 3.4.1 - 2026-09-28

- The README explains the Jev edition from scratch, with a screenshot of every page where Jev shows.
- The demo shows the range Jev may move the re-water point in, as the controller sets it.
- Bug fixes and improvements.

## 3.4.0 - 2026-09-28

- The dashboard is simpler: Today, Plan, History and Equipment, plus a page for each zone.
- Today fits one screen and flags a zone only when it needs you, with the reason.
- Every decision Jev makes now sits in one timeline, with a tick or cross when its result is known.
- Bug fixes and improvements.

## 3.3.0 - 2026-09-28

- Today's grow day is redrawn in the style of Athena's charts: one clear chart per zone, its numbers above it, the stage's targets on top.
- Jev's decisions now show live: what it answered, what it asked for, and what the controller did about it.
- Jev also knows Athena's crop-steering guide now, alongside your own doctrine, which still leads.
- Bug fixes and improvements.

## 3.2.0 - 2026-09-28

- With Auto setpoints on, Jev may nudge each zone's maintenance shot size or re-water point one small step a night.
- It stays close to your own values, your edits always win, and a change that needs a rescue shot is undone.
- Bug fixes and improvements.

## 3.1.0 - 2026-09-28

- Every decision Jev makes is now recorded with what the controller did about it, ready for a live log on the dashboard.
- Bug fixes and improvements.

## 3.0.1 - 2026-09-27

- When one zone gets far more water than the others, only that zone is flagged now; its neighbours no longer hear of a fault they don't have.
- Bug fixes and improvements.

## 3.0.0 - 2026-09-27

- Jev now judges what the controller decided by fixed rules: when the ramp starts and ends, when watering stops, why pore EC moved, and probe trust.
- Your own crop-steering doctrine is part of every judgement, and each zone is checked against today's stage of flower.
- Every judgement shows on its zone with how sure Jev was. Without a Jev key the controller runs exactly as before.
- Bug fixes and improvements.

## 2.25.1 - 2026-09-27

- A zone with more than one moisture probe reads the middle one, and no longer jumps when a probe drops out or stops reporting.
- Bug fixes and improvements.

## 2.25.0 - 2026-09-27

- Each zone shows what it is waiting for next: the moisture or EC level that starts its next shot or phase.
- One switch in the zones heading turns every zone on or off, and switching a zone off now stops a shot already running.
- Water today can show per plant instead of per zone, on the dashboard and in the vitals notification: choose it in Settings.
- One watering switch per room: two older switches that did the same job are retired.
- Bug fixes and improvements.

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
