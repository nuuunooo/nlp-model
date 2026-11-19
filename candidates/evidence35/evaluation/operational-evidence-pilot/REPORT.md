# Operational evidence verifier pilot

The pilot improved coverage over the strict 3.4 pipeline and remained below frozen version 3.3 on the broader recall and exact multi-violation gates. Version 3.3 remains the default. This run took place offline.

## Fit and cutoff

The run retained the original frozen multilingual E5 encoder, three-state logistic head recipe, 10,596 synthetic fit pairs, and 2,124 synthetic validation pairs. It added 427 operational incident pairs from 245 previously inspected descriptions to fit only. The operational labels are provisional and cover all three states in eight categories. The additional pairs used each incident's quoted description text and category. Evidence state served as the training target. The weighting grouped repeated category and state contexts into 194 families.

The selected cutoff was `0.9999997615814209`, chosen on synthetic validation to maximize supported recall at 98% precision or higher and zero compliant pairs accepted. It accepted 254 of 684 supported pairs, yielding **98.45% precision and 37.13% recall**. The four false accepts paired a description with an unrelated category. The 12 explicit compliant and 60 original insufficient pairs produced zero accepts. The synthetic-only frozen-encoder verifier found no qualifying cutoff under the same criterion. The previous separately fine-tuned encoder accepted one supported validation pair.

## Description-level results

The replay kept all strict 3.4 findings and applied the fixed verifier cutoff to additional category nominations. The incident scope, compliance, numeric, and uncertainty checks stayed in place. The market cohort was excluded because its descriptions contributed to fit. The other cohorts showed no exact overlap with the operational fit descriptions or their quoted incident contexts under the normalized text check. All three cohorts have been inspected during earlier development.

| Cohort | Frozen 3.3 precision / recall | Strict 3.4 precision / recall | Pilot precision / recall | Exact multi-label, 3.3 / 3.4 / pilot |
| --- | ---: | ---: | ---: | ---: |
| Synthetic validation, 804 descriptions | 98.32% / 78.80% | 100% / 65.07% | 99.66% / 72.43% | 42/60 / 30/60 / 38/60 |
| Historical synthetic test regression, 804 descriptions | 95.47% / 72.30% | 100% / 26.59% | 98.47% / 55.39% | 36/60 / 12/60 / 25/60 |
| Challenge regression, 49 descriptions | 97.96% / 73.85% | 100% / 72.31% | 100% / 73.85% | 19/30 / 17/30 / 18/30 |

On the historical synthetic regression, the pilot recovered 235 correct findings and introduced seven incorrect category findings relative to strict 3.4. There were zero actions across 54 clear and 56 abstention descriptions across the three cohorts. The seven incorrect categories appeared on descriptions with at least one expected violation.

On synthetic validation, 225 expected findings were still missed. The category classifier failed to nominate 64. Another 99 nominations had no incident eligible for the verifier after the scope and safety checks. The remaining 62 had an eligible incident whose score fell below the evidence cutoff. These counts describe the stages at which coverage was lost and do not justify relaxing a safety check.

The 25 baseline tests and five verifier data tests passed. Reloading the saved head with the verified validation embeddings reproduced all cutoff decisions. The frozen runtime, category model, and thresholds match their recorded hashes. A separate, independently labeled operational set under the current catalog is still needed for the final test.
