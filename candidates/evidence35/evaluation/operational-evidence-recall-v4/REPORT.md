# Corroborated recall pilot

The revised offline pilot narrowed the historical synthetic recall gap to 35 findings. It added 37 correct findings and one incorrect category on a description labeled as containing a violation. Across the three replay cohorts, all 54 clear and 56 abstention descriptions received zero actions.

| Cohort | Prior → revised recall | Prior → revised precision | Prior → revised exact multi-violation sets |
| --- | ---: | ---: | ---: |
| Synthetic validation, 804 descriptions | 76.10% → 78.92% | 99.68% → 99.69% | 41/60 → 44/60 |
| Historical synthetic regression, 804 descriptions | 63.48% → 68.01% | 98.67% → 98.58% | 33/60 → 34/60 |
| Challenge regression, 49 descriptions | 73.85% → 73.85% | 100% → 100% | 18/30 → 18/30 |

Frozen 3.3 reaches 72.30% recall, 95.47% precision, and 36/60 exact multi-violation sets on the historical synthetic cohort. The revision did not fully close the recall gap or meet the prior pilot's precision there. It remains an offline experiment.

## Recovery changes

The new classifier paths use the score and evidence from the same incident and retain the previous eligibility checks. The agreement path requires a matching finding from frozen 3.3, an incident category score at or above its frozen threshold and at least 0.75, a lead of at least 0.20 over the next category, and learned support of at least 0.75. The other path requires the same category score floor and threshold, a leading category, and learned support of at least 0.999999.

The additional explicit evidence paths cover vendor placement directly across or in front of an exit, a failed shared light tied to the specific stallholder's duty, selling during a stated active suspension, and an observed retail length shortfall in compatible units. They reject blocked or uncertain observations. These changes were selected using synthetic validation and frozen before the historical replay. A separate category-specific follow-up found no rule with at least four additional correct findings across at least two validation scenarios and zero incorrect additions.

The three cohorts are previously inspected development regressions. The market data used in fit were excluded. The 25 baseline and nine candidate tests passed. Frozen 3.3 and its model artifacts match their recorded hashes. A final test on new independently labeled operational descriptions is pending.
