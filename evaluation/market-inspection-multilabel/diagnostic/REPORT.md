# Diagnosis of the frozen 150-record evaluation

The first implementation priority is to require evidence of an actual breach within the relevant incident. The current model filter often accepts a category merely because its topic is mentioned. Incident scoring helps recall substantially, but it amplifies this precision problem and cannot be adopted on its own.

The runtime remains `3.3.0-description-only`. Model weights, saved thresholds, rules, taxonomy, lexicon and the original evaluation report are unchanged. The diagnostic script exactly reproduced all 150 original decisions and their finding sources before running the experiment. Only descriptions entered inference; gold labels and `label_evidence` stayed offline.

## Missing labels

The baseline missed 192 of the 244 supplied positive labels.

| Failure path | Missing labels | Interpretation |
|---|---:|---|
| Model score below cutoff; text gate passes | 147 | The whole-description classifier did not nominate the category. |
| Model score below cutoff; text gate also rejects | 26 | Both category nomination and evidence coverage need attention. |
| Model score meets cutoff; text gate rejects | 16 | Lowering thresholds would not recover these labels. |
| Weight parser does not establish a violation | 3 | Weight acceptance requires described facts regardless of model confidence. |
| Total | 192 | Every missing label has one primary trace classification. |

Across those paths, 176 labels had whole-description model scores below their saved cutoffs, including the three weight-parser failures. The 42 text-gate failures include narrow vocabulary and category exclusions, not just legitimate abstentions. These are mechanical traces against supplied gold, not independent proof that every gold label is correct.

Examples:

- `SYN-MI-006`: Porter Regulation rises from 0.209 for the whole description to 0.969 for its fragment, above the unchanged 0.686 cutoff. Whole-description scoring loses a clearly stated porter incident.
- `SYN-MI-008`: Public Order scores 0.552 against a 0.482 cutoff but is rejected because the topic pattern misses “fistfight.”
- `SYN-MI-059`: Lighting & Energy scores 0.961 against a 0.877 cutoff, but the topic pattern does not match the plural lamps/bulbs in this description.
- `SYN-MI-066` and `SYN-MI-140`: The parser misses “no City Treasury registration seal.”
- `SYN-MI-092`: A magnet under the scale pan and a positive empty-pan reading are described, but the current fault patterns do not recognize that wording. Even a fragment model score of 0.980 cannot bypass the weight requirement.
- `SYN-MI-001`: General Penalties remains far below its 0.969 cutoff even when isolated. Segmentation does not resolve every model vocabulary or generalization gap.

## False actions

There were 23 extra category actions on the 135 records with known label sets, plus four actions on the 15 abstention records. All 27 came from model predictions accepted by the text gate. All 27 have individual review notes in `review.json`.

| Reviewed cause | Actions | Example |
|---|---:|---|
| Compliant statement accepted as a violation | 16 | A current permit, paid fees, paid rent, an authorized occupant, or knives in a locked box. |
| Incident mapped to a different category than supplied gold | 8 | An illegal water jumper becomes Illegal Vendor; construction approval becomes business licensing. |
| Unverified rumor accepted as fact | 2 | “Tsismis” and “hindi na-verify” are not recognized by current uncertainty patterns. |
| Required vendor duty not established | 1 | A flickering light produces an action although maintenance duty is explicitly unknown. |

Some category mismatches also expose a contract issue between gold and the working catalog, particularly dwelling versus occupancy and sidewalk authorization versus general licensing. These mappings need an explicit internal policy; the audit does not independently adjudicate the cited ordinance sections.

The existing check is simultaneously too permissive about whether a breach occurred and too restrictive about vocabulary. Increasing or decreasing one confidence threshold cannot solve both problems.

## Exploratory segmentation experiment

The experiment scored 344 fragments with the same model and thresholds, ran each through the unchanged engine, and combined those findings with the baseline whole-description findings. It used existing incident separators plus explicit “also”/“tapos” connectors. No candidate was installed in the worker.

| Measure | Frozen baseline | Whole description plus fragments |
|---|---:|---:|
| Correct positive labels | 52 | 134 |
| Extra labels on known records | 23 | 55 |
| Missing positive labels | 192 | 110 |
| Precision on known label sets | 69.3% | 70.9% |
| Recall on known label sets | 21.3% | 54.9% |
| F1 on known label sets | 32.6% | 61.9% |
| Exact label sets among 100 multi-label records | 4 | 25 |
| Compliant records receiving actions, out of 20 | 11 | 19 |
| Abstention records receiving actions, out of 15 | 4 | 6 |

Fragment scoring recovered 82 labels, all from the group whose only baseline blocker was a low model score. It also added 32 extra labels on known records. The increased aggregate precision does not make the alternative acceptable: it generated actions for 95% of compliant records. This experiment is development evidence, not a new untouched evaluation.

Splitting can also detach a restriction, actor, pronoun or follow-up qualification from its observation. The current separator can split abbreviations such as street initials. A future implementation needs to preserve those relationships rather than treating every fragment as a self-contained fact.

## Gold-label context

The review flags 44 label occurrences across 38 records where acceptance depends on an internally established rule or category mapping that is not fully stated in the description. Examples include alcohol restrictions, required attire, blade storage, grease traps, dwelling/animal/children rules and the meaning of a missing mobile vendor ID. Offline `label_evidence` supplies section citations or the missing policy assertion.

These are 44 policy-context checks, not 44 proven annotation errors. The supplied gold and all baseline metrics remain unchanged. The section citations have not been independently verified. Any fixed requirements should be represented in the system's reviewed policy catalog, with observations extracted from the description. This does not require extra fields, confirmations or steps from system users.

## Selected implementation order

1. Replace topic-only acceptance with incident-level breach verification. Require the relevant actor/activity, the observed failure and any applicable duty or restriction. Preserve exact supporting text. Distinguish an absent required item from an absent violation, and localize compliance, uncertainty and follow-up qualifiers to the incident they qualify. Apply the same evidence contract to every finding source.
2. Make category boundaries explicit in the internal catalog. Separate construction approval, scale registration, vending authorization, business licensing and operating rules. Resolve the policy-context checks offline without changing the user-facing workflow.
3. Add context-preserving incident scoring behind that verifier. Keep whole-description context where needed, compare quantities within the correct incident, and combine accepted findings once per category. Include the concrete scale-seal and empty-pan cases in weight-parser development.
4. Assess remaining classifier misses on representative development descriptions. If retraining is needed, group reused observations, near duplicates and vendor-related records before splitting. Fit only on the designated fit split and select thresholds only on a separate validation split. Do not lower thresholds to fit this evaluation CSV.
5. Freeze the completed candidate and evaluate once on a new untouched set. Retain compliant and uncertain descriptions alongside multi-violation records, and report category precision, recall, exact label sets and false actions separately.

The 150 records have now been inspected in detail. They may serve as development/regression data for future changes, but cannot be reused as an untouched release test for those changes. The original frozen-version evaluation remains the baseline.

## Artifacts and verification

- `diagnosis.json`: per-record predictions, every missing-label score and gate trace, experimental predictions, aggregate counts and hashes.
- `review.json`: individual notes for all 27 false actions and the 44 policy-context checks.
- `diagnostic_scores.npz`: locally cached whole-description and fragment probabilities with input/model provenance.
- `scripts/diagnose_market_evaluation.py`: reproducible baseline replay and experiment; rerun with `.venv/Scripts/python.exe scripts/diagnose_market_evaluation.py` from the workspace root.

Verification reproduced every baseline label set and source, checked model/rule/threshold hashes before and after inference, reconciled all 192 missing labels, and matched every false action to exactly one review note. All 44 policy-context entries were checked against the supplied gold codes. No production behavior changed.
