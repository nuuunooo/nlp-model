# Next inspection batch for verifier development

Collect **55 additional distinct, anonymized market inspection descriptions**. At least **21** should describe both a supported violation and a separate incident that is compliant or insufficiently documented. This brings the working targets to 300 distinct descriptions and 50 mixed descriptions. The existing data already meet the target for descriptions with multiple incidents.

## What to look for

The current set is short by 200 incident annotations against the target of five per category and state. Most are compliant or insufficient observations. The 55-description target and the coverage target are tracked separately because one description can contain several incident annotations.

| Priority | Categories | Observations to include |
| --- | --- | --- |
| No compliant or insufficient examples yet | Lighting & Energy, Illegal Vendor, Promotions, Entertainment Activities, Market Rules, Resisting Authority | Inspections that document the relevant condition being met, or describe the issue and identify which required fact was unverified. Look for five of each state per category. |
| Few supported examples | Advertising, Liquor | Three more clearly documented advertising breaches and one more observed liquor breach, plus explicitly compliant checks in both categories. |
| Next largest compliance and uncertainty gaps | Stall Construction, Utilities, Market Conduct, General Penalties, Price Monitoring | Look for an approval or authorization checked against the activity, a verified comparison, or the precise condition the inspector could not verify. |

Use the [per-category coverage audit](coverage_and_provenance.json) to see the remaining counts. Prefer records that document the same kind of check under different outcomes. For example, collect price checks where the price charged exceeds the posted price, matches it, or cannot be verified because the amount charged was never established. Keep the original wording and the recorded outcome for every case.

## What to send

- Provide the natural inspection text in UTF-8 CSV under `description`. Include an anonymous `record_id` and a stable anonymous `group_id` when available. Use the same group for records about the same stall or inspection event. Preserve quantities, units, dates that establish whether an approval was current, and uncertainty wording. Remove names and other identifying details.
- Keep these 55 records for offline development. The project can add incident labels, exact evidence quotes and missing-fact notes after intake. Count repeated descriptions once, and flag closely repeated wording or related events before any split.
- Collect the final operational test as a separate batch. Keep its descriptions and labels out of training, threshold selection and rule changes. The final batch needs independent review against the current 29-category catalog and disjoint inspection groups.

## Source check

The local Downloads, workspace, and related project packet were checked for additional records with documented operational provenance. The legacy packet contains supplied unverified descriptions and synthetic additions under a 23-category catalog. The starter pipeline export is synthetic. The revised weight files lack a crosswalk that establishes which observations are distinct from the earlier batch. No additional qualifying descriptions were found in these sources.
