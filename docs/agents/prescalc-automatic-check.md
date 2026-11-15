# Prescalc Automatic Check

- Prescalc (`prescription_agg_service.create_agg_prescription_by_prescription`, non-CPOE) checks an individual prescription with nothing to validate, per schema feature: `AUTOMATIC_CHECK_DIET_ONLY` (only diets) and `AUTOMATIC_CHECK_WHITELIST_ONLY` (every drug, solution and procedure is `whiteList`); materials and diets may come along, any other item leaves it to the pharmacist
- The patient-day status is kept (a checked one is not made pending again); a new patient-day is checked when all its prescriptions are. When an item to validate arrives later, the regular flow unchecks both
- The check sets only status and audit (`extra.automaticCheck` names the feature): no `checkedindex`, no presmed marking
- CPOE has its own: `AUTOMATIC_CHECK_IF_NOT_VALIDATED_ITENS` checks the patient-day with no item to validate (`_automatic_check`)
- Tests: `tests/integration/test_prescalc_automatic_check.py`
