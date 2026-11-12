# Prescription View, Interactions and Allergy

## Prescription View (`GET /prescriptions/<id>`)
- The most used endpoint (`prescription_view_service._internal_get_prescription`); prescalc runs the same pipeline (`static_get_prescription`), so a cost added here is paid on every load of the screen and on every prescalc
- **What was read once is passed along, not read again**: the prescription's segment (joined in `_get_prescription_data`, passed to `_get_configs`), the tenant features (read with the other memory items, kept for the request by `feature_service.set_features`), the feature flags (one read per request, also when none is set), the patient's allergy records (alerts, notes and cross reactivity) and the columns the models defer but the view shows (`undefer` in `_get_prescription_data`). `tests/integration/test_prescription_view_queries.py` fails when one of these becomes a query of its own again
- A new read on this path: join it to a query that already runs or reuse what was read; a check per item or per pair of items must not query, nor look things up in a list (the interaction check compares every pair of items)

## Drug Interaction Checking
- Service: `services/alert_interaction_service.py`
- Checks drug-drug interactions
- Multiple severity levels
- Every pair of items is compared (the work grows with the square of the items), so the pairs are deduplicated in a dict and the pairs without a relation are skipped with one lookup. The relations of the substance pairs are read in one statement that is the same for every prescription: the pairs go as two array parameters (`_get_active_relations`), not written into the SQL

## Allergy Alert
- Rule: `alert_service.is_allergic`, used by the allergy alert and by the item's `allergy` flag in the drug list (`utils/drug_list.py`)
- The flag on `presmed.alergia` is set when the item arrives; the prescription view confirms it with the patient's `alergia` records (`repository/allergy_repository.py`): an active record of the item raises the alert, only inactive ones drop it, and with no record of the item the flag stands (some clients have no `alergia` records)
- A record is of the item when its `fkmedicamento` is the same drug (even if its `sctid` is stale), or by substance: `alergia.sctid` when present (filled by a separate job and trusted, since `fkmedicamento` does not always reference a `medicamento` record), otherwise the substance of its `fkmedicamento`. The cross reactivity check (`alert_interaction_service._get_allergies`) resolves the substance from the same records (`get_allergy_records` joins it that way), which the prescription view passes to it
- The prescription view reads the records once (`_internal_get_prescription`) and passes them to the alerts, to the cross reactivity and to the clinical notes, which list the active ones (source `pep`, one per name, cut at `_ALLERGY_RECORDS_LIMIT`: only information)
- Each drug list item carries why, for the maintainers (drug popover in the frontend): `allergyFlag` (`presmed.alergia` as it arrived) and `allergyRecord` (`active`/`inactive` from `alert_service.get_allergy_record_status`, `None` when no record of the item decided and the flag stood)
- Tests: `tests/unit/test_alerts_allergy.py` and `tests/integration/test_prescription_allergy.py`
