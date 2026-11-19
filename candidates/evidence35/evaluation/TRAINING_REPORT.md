# Incident evidence verifier development results

Both three-state verifiers were rejected. The neural verifier accepted 1 of 684 supported validation pairs and recovered zero missed findings when added to the strict 3.4 candidate. The default runtime is the frozen 3.3 description-only workflow. The experiments ran offline.

## Fit and validation data

The target is whether a description supports a violation in a nominated category, explicitly establishes compliance, or provides insufficient evidence. The model input is the description and internally nominated category. Structured source observations were used for annotation checks. Multi-incident source records were excluded from verifier fitting and calibration because their labels apply to whole records. The data audit also records category boundary and missing observation exclusions.

| Data | Supported | Compliant | Insufficient | Total |
| --- | ---: | ---: | ---: | ---: |
| Frozen multilingual E5 with a logistic head, fit | 2,076 | 2,112 | 6,408 | 10,596 |
| Separately fine-tuned multilingual E5 with a logistic head, fit | 2,076 | 65 | 528 | 2,669 |
| Shared validation | 684 | 12 | 1,428 | 2,124 |

The synthetic source separates fit and validation by evidence family. Fit includes generated compliance and uncertainty examples and sampled pairs that nominate unrelated categories. Validation includes 1,368 unrelated-category pairs and only 12 explicit compliance pairs across four families and four categories. The validation results measure synthetic development data. The supplied market descriptions were reserved for the development regression.

## Calibration

- The frozen encoder verifier had no cutoff with at least 98% precision on accepted pairs and zero accepted compliant pairs. Its highest-probability state was `supported` on 8 of 12 compliant pairs. The saved calibration represents the failed selection as no cutoff, which rejects all pairs, including scores rounded to one.
- The fine-tuned verifier completed 100 contrastive steps with seed 42. Its validation-only cutoff of `0.9792906045913696` accepted one supported English pair, zero compliant pairs and zero insufficient pairs. Supported recall was 0.15%, with zero accepted pairs in Filipino and Taglish. Its highest-probability state was `supported` on 6 of 12 compliant pairs and 1,212 of 1,368 unrelated-category pairs.

Reloading the saved verifier reproduced the validation probabilities and all acceptance decisions. The precision constraint was met on a single accepted example. The narrow compliance coverage and the number of unrelated categories given the highest support score make this verifier unsuitable for recovering missed violations.

## Description-level development regressions

The offline replay retained all strict 3.4 findings. It scored additional nominations from the frozen 29-category classifier only after incident scope, compliance, numeric and uncertainty checks. The neural cutoff was fixed before the replay. The candidate produced identical label sets to strict 3.4 on all 1,807 descriptions. The precision and recall below are micro-averaged. Exact multi-label counts require the complete correct label set.

| Previously inspected cohort | Frozen 3.3 precision / recall | Candidate precision / recall | Exact multi-label, frozen 3.3 → candidate | Extra pairs scored |
| --- | ---: | ---: | ---: | ---: |
| Synthetic validation, 804 descriptions | 98.32% / 78.80% | 100% / 65.07% | 42/60 → 30/60 | 153 |
| Historical synthetic test, 804 descriptions | 95.47% / 72.30% | 100% / 26.59% | 36/60 → 12/60 | 466 |
| Market development, 150 descriptions | 69.33% / 21.31% | 100% / 98.77% | 4/100 → 97/100 | 5 |
| Challenge, 49 descriptions | 97.96% / 73.85% | 100% / 72.31% | 19/30 → 17/30 | 7 |

The candidate produced zero actions on labeled clear and abstention cases in all four cohorts. Its market result came entirely from the previously developed strict 3.4 checks. Its broader recall regression still fails the release gate.

The 25 baseline tests and five verifier data tests passed. The 12 frozen runtime source files and the baseline model weights, head and thresholds match their recorded hashes. The evaluation scripts and artifacts are isolated under the evidence35 candidate.

## Remaining release requirement

Build incident-level development examples for the same category across all three states, including mixed records where one incident warrants an action and another is compliant or uncertain. Include real descriptions and separate evidence families between fit and validation. Keep an independently labeled operational set under the current 29-category catalog separate from development. The workspace audit found no qualifying untouched set, so the final test is pending. These labels are for offline evaluation and the product still takes the description as its input.
