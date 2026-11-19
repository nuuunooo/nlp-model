# Incident-level recall recovery pilot

The revised pilot recovered 66 additional correct findings on the historical synthetic regression. Recall rose from 55.39% to 63.48%, precision rose from 98.47% to 98.67%, and exact multi-violation matches rose from 25 to 33 of 60. The seven prior incorrect category findings were unchanged. The revised pilot still trails frozen 3.3 on historical synthetic recall and exact multi-violation matches, so 3.3 remains the default.

## Method and controls

The replay preserves the prior pilot's accepted findings and adds candidates one incident at a time. The original category classifier and trained verifier were reused. All prior scope, compliance, uncertainty, and numeric vetoes apply before the new checks. `WeightMeasures` continues to use the deterministic path in this replay.

Both recovery paths use the category score for the same incident and require it to reach at least 75% of that category's existing threshold.

- If the existing breach verifier supplies corroborating evidence, the learned support score must be at least 0.90.
- Otherwise the learned support score must be at least 0.9999, and that category must lead the next category by at least 0.05 after dividing each category score by its own threshold.

Thresholds and the lead margin were selected on synthetic validation. The selection required more correct findings, no added incorrect category findings, zero actions on clear and abstention cases, and no decrease in exact multi-violation matches. The resulting configuration and scoring code hashes were saved before replaying the historical synthetic and challenge regressions. The market cohort that contributed training descriptions was excluded.

## Results

| Cohort | Prior → revised precision | Prior → revised recall | Prior → revised exact multi-label | Additional correct findings |
| --- | ---: | ---: | ---: | ---: |
| Synthetic validation, 804 descriptions | 99.66% → 99.68% | 72.43% → 76.10% | 38/60 → 41/60 | 30 |
| Historical synthetic test regression, 804 descriptions | 98.47% → 98.67% | 55.39% → 63.48% | 25/60 → 33/60 | 66 |
| Challenge regression, 49 descriptions | 100% → 100% | 73.85% → 73.85% | 18/30 → 18/30 | 0 |

The revised pilot introduced zero incorrect category findings across these cohorts. It produced zero actions on 54 clear and 56 abstention descriptions. Frozen 3.3 achieved 72.30% recall and 36 of 60 exact multi-violation matches on the historical synthetic regression.

The 25 baseline tests and five candidate data tests passed. The frozen runtime, category weights, head and thresholds match their recorded hashes. These cohorts are development regressions. The final independent operational test is pending. The revised pilot is isolated from the application.
