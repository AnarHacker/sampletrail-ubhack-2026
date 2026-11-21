# Synthetic batch and rule specification

**SYNTHETIC DEMONSTRATION DATA — NOT REAL MINE OR LABORATORY DATA.**

Demo Ridge, batch SIM-BATCH-01, fictional Demo Lab, one method SIM-CU and Cu in percent by mass. The manifest has 15 routine core samples, one split-core duplicate, one field blank, one preparation duplicate and two reference materials. The historical Oyu Tolgoi report describes analogous controls and one or two reference materials depending on the material. All identifiers, values, dates, rules and certificates here are fictional. [Oyu Tolgoi 2020 report, §§11.5–11.6](https://www.sec.gov/Archives/edgar/data/1158041/000119312520235398/d943908dex992.htm) (accessed 21 November 2026).

## Files and relationships

- Manifest rows carry a stable submission slot, expected sample ID, control type, parent slot or CRM code as applicable, collection date, drillhole/from/to when meaningful, dispatch and receipt actors/times and the expected and observed seal. Reconcile both sides by stable slot without guessing IDs.
- Assay CSV rows carry slot, reported ID, optional drillhole/from/to, analyte, unit, method and result. Compare reported origin fields when present and validate manifest origin. Missing, unexpected or duplicated IDs, ambiguous slots and mismatches remain visible.
- V1 and V2 each have a distinctly identified synthetic lab PDF, issuer, issue time and a CSV. V2 explicitly references V1. The complete fixture dataset, including each CSV row, carries the synthetic label. PDF and CSV bytes are stored and hashed.
- Blank SIM-BLK-01 is 0.015% in V1 and 0.004% in V2. Slot S07 changes from SIM-ST-070 to the expected SIM-ST-007, with the result unchanged. Both V2 corrections are documented simulated transcription corrections. CRM SIM-CRM-B remains 0.524%, with reference 0.500%, pass deviation 0.020% and fail above 0.040%. The simulated geologist records HOLD on V1 and a V2 review requesting CRM follow-up before use.

## Rules and exact boundary behavior

| Check | Calculation | Demo settings |
| --- | --- | --- |
| CRM A/B | Absolute difference between measured and certificate reference in Cu percentage points | A reference 0.250, B 0.500. Both pass through 0.020 and warn through 0.040. Above the latter fails. |
| Blank | Compare result directly with one-sided thresholds | Pass through 0.005% Cu, warn through 0.010%, above 0.010% fails. |
| Duplicate | Pair by explicit parent slot. At or below the configured pair mean of 0.050% Cu, use absolute difference. Above it, use RPD = 100 × absolute difference ÷ pair mean. | For both demo pairs, pass/warn maxima are 0.003/0.006 percentage points at low mean and 10/20% RPD above the floor. Rules are editable per duplicate type. |

Expected examples are split core 0.300 versus 0.312% Cu (3.92% RPD, PASS) and preparation pair 0.010 versus 0.012% Cu (0.002 percentage points, PASS). Only valid, unambiguous results enter QC calculations. Missing input needed by a control or unhandled values such as a censored result generate findings for investigation. The duplicate rule is a fictional transparent screening approximation. Precision depends on concentration, method and sampling stage. [Smee et al., “Estimates of relative precision”](https://doi.org/10.1144/geochem2023-046) (accessed 21 November 2026).
