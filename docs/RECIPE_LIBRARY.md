# Reusable plan library

The library stores copies of plans you author. It starts empty and does not contain publisher-endorsed or guide-derived numerical recipes.

Open **Grow plan → Recipe library** to save a named copy of the current plan, inspect stored copies, or load one into the local draft. Loading a recipe retains the current zone start dates and requires compatible zone assignments. Existing unsaved work requires an explicit replacement review. Active plans remain protected by the normal draft/arm workflow.

Library storage belongs to this browser and this site, separated by room and demo/live mode. It is not an HA backup or shared multi-user database. Export important plans using the existing JSON export; use Import to bring an exported plan into the reviewed workflow. Clearing browser storage can remove local library entries. An unavailable or malformed library must be recovered explicitly rather than silently overwritten.

Loading or saving a local library item never calls an irrigation service. The normal **Review & save** action persists the draft in HA, and arming remains a separate action. Inspect the graph, assignments, dates and parameter validation before using a loaded draft.

## Reference sources

These links identify the requested publications. They do not establish endorsement, numerical equivalence or a validated controller configuration.

| Reference | Publisher link | Verification on 8 September 2026 |
| --- | --- | --- |
| Athena, *Precision Irrigation Strategy* | [Official support article](https://support.athenaag.com/hc/en-us/articles/25975395644315-Precision-Irrigation-Strategy) | Article identifies Taylor Rauls and a 22 May 2024 update. Its publisher PDF is accessible; a numbered edition was not verified. |
| CCI Black Book / *Crop Steering Super System E-Book* | [Official CCI publisher](https://ccibook.com/pages/crop-steering-super-system-e-book) | The free e-book offer is distinct from the physical Black Book and its download form requests contact details. No form was submitted; no ungated publisher PDF or numbered edition was verified. |
| *@DANKEMSHUNTER Feed Program* | [Indexed Athena publisher asset](https://store.athenaag.com/SSP%20Applications/NetSuite%20Inc.%20-%20SCS/SuiteCommerce%20Standard/athena/assets/Dankemshunter%20Feed%20Program.pdf) | The original publisher URL was identified, but a fresh request returned HTTP403. Current direct access and edition remain unverified. |

The application does not infer undocumented settings from a publication name. Its validator checks supported fields, bounds and plan structure; that is software validation, not agronomic validation.
