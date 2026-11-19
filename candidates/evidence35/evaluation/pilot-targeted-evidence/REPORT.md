# Targeted evidence additions to the v4 pilot

The corroborated v4 pilot remains the main offline candidate. Its predictions were preserved as the base of both experiments. The shared learned verifier supplied no action decisions. The new comparisons and observed-breach checks are development candidates. Frozen 3.3 remains the default runtime.

## Validation-selected additions

An addition needed at least two distinct validation scenarios and zero incorrect added categories. The seven qualifying checks recovered 33 correct validation findings, including seven for obstruction and five for interference with inspection. Validation recall rose from 78.92% to 82.97%, with 48 of 60 complete multi-violation sets versus 44 for v4. The 33 additions produced zero new incorrect categories.

The fixed selection added no findings on either replay cohort. The structured checks reused from the shared verifier, including scale tests, expiry, equipment, lease consent and occupancy, produced no incremental findings on these three cohorts. Their eligibility remains unproven for broader use in the pilot.

## Liquor diagnostic

Review of previously inspected historical misses identified sales with a documented buyer age or sale time and an explicit local restriction. The checker compares those facts within the same incident. It abstains when the buyer's age lacks identity evidence, a reported time belongs to a different event, or the description does not establish a sale. The checks apply the limits stated in the description.

| Historical synthetic regression | Precision | Recall | Complete multi-violation sets |
|---|---:|---:|---:|
| v4 pilot | 98.58% | 68.01% | 34/60 |
| v4 with liquor checks | 98.62% | 69.98% | 37/60 |

The age and time checks each recovered eight historical findings, with zero additional incorrect categories and zero actions on clear or abstention records. Historical examples informed implementation, so this gain measures coverage of inspected development cases. Validation and the separate synthetic challenge produced no additional liquor findings. Independent operational evidence is still needed before promotion.

All 25 baseline and 28 candidate unit tests passed. The focused tests cover compliant and unverified buyer ages, overnight sale windows, times belonging to a different event, ambiguous follow-ups and shared checks that require both a category nomination and a supported comparison.

[Validation selection](validation_verified.json) · [Historical replay](test_regression_verified.json) · [Challenge replay](challenge_verified.json) · [Liquor diagnostic](liquor-diagnostic.json)
