# The package, file by file

Number the files. Keep the same numbers in the cover letter, Email 1 and the folder.
`SUBMIT/` holds only what goes to the MCA. Working copies go in `_build/`.

| File | Document | Must contain | Data file sections |
| --- | --- | --- | --- |
| 00 | READ ME FIRST (internal, never sent) | Bottom line, cost, what each file is and its status, "confirm before signing" list, must-do list, how to send, after-lodging table, risks | all `confirm:` lists |
| 01 | Cover letter | What we ask for; the location in brief (future tense for unbuilt items); timing and inspection; renewal sequencing; fees; enclosed list; OIA confidentiality request; contact and consultant authority; signature | meta, applicant, licence, site, timeline |
| 02 | Form LA (amendment) or Form A Section A (new) | Signed and sworn before a JP. Send the signed scan only | applicant, licence |
| 02a | Copy of the current licence (amendment/renewal) | Every page | licence |
| 03 | Form A Section B for each location | Matches every attachment: areas, purposes, buyer and licence number, record system | site, cultivation, supply, records |
| 03a | Section A3 responsible person declaration | Signed, either/or choices completed truthfully | applicant.director |
| 04 | Attachment 1: site location plan, GPS, legal description | Locality map, aerial, licensed area outlined in red, excluded areas hatched grey, every structure and entrance labelled, north arrow, scale | site, layout |
| 05 | Attachment 2: facility layout plans and photographs | Figure 1 site plan, Figure 2 unit plans, photo schedule (each photo: which building, date, what it shows) | layout, photos |
| 06 | Attachment 3: owner/landlord consent and plan of the licensed area | Signed by every registered owner (or the owner's authorised signatory), names the licence and the site, plan initialled | site.owner, site.landlord |
| 07 | Attachment 4: site security plan | Layers from outside in; Annex A device schedule; Annex B "existing / upgrade / to install" with supplier and date; emergency egress; response times; monitoring company legal name | security, equipment |
| 08 | Attachment 5: odour control plan | Sources, negative pressure, carbon filters (fitted or "will be fitted"), boundary checks, complaints process, neighbours and distances | odour, planning |
| 09 | Attachment 6A: site procedures | Which document controls; adopted SOP suite and every site variation; opening and closing; visitors; receipts; transport; waste and destruction; incidents; lone worker; signed approval table | staff, records, security |
| 10-12 | Attachments 6B-6D: adopted SOP suite | Unmodified, licence attribution, signed adoption sheet | - |
| 13 | Attachment 7: record-keeping, stocktake and reporting | Bound register, named electronic system (product, version, host, owner, audit log, export), monthly returns, 31 Dec stocktake, example records | records |
| 14 | Attachment 8: supply agreement | Signed agreement or letter of intent naming the applicant, the site and the buyer's licence number | supply |
| 15 | Attachment 9: research plan (if research) | Purpose, quantities as upper limits, breeding and quarantine locations, cultivar list matching the register | research, genetics |
| Videos | Site walkthrough | Muted; shot list; only what the application covers | - |
| LATER | Renewal kit | Form RA, one Form RB per location, fresh owner letters, ID scan | renewal |

## Build discipline

- All facts live in `application_data.yaml`. Rebuild after each change.
- The readiness check exits with an error while a blocker is open. Confirm items are warnings.
- Never stamp "draft" on a document in SUBMIT. Put version and date in the footer.
- Use A4 page size. Set the PDF title. Caption every photo. Blur number plates.
