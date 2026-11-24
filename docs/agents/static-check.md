# Static Check (`POST /static/prescriptions/status`)

An external system checks or unchecks a prescription. The caller is a service integrator (`SERVICE_INTEGRATOR`, permission `RUN_AS` only), and `prescription_check_service.static_check` runs the regular check (`check_prescription`) as someone:

- **With `idOriginUser`** (the user's external id, `usuario.fkusuario`): the check is that user's. The origin user must be active, in the integrator's schema, hold `WRITE_PRESCRIPTION` and be authorized on the prescription's segment; otherwise 400 (401 for the segment)
- **Without `idOriginUser`** (missing, null or blank): an automatic check on the client's side, no person behind it. The check is the integrator user's own (prescription user, audit `createdBy`, `checkedindex`, presmed event), in any segment of its schema (`skip_segment_authorization`, set only here). Any integrator may do it, no feature flag
- A blank `idOriginUser` is never looked up: `external == None` is `external IS NULL` and would match any user without an external id
- The audit's `extra.serviceUser` is `true` in both cases
- Don't give `SERVICE_INTEGRATOR` the `CHECK_STATIC` permission to skip segments: combined with another role it would skip segments in every service
- In a schema with return integration, the checker needs an external id, the integrator too
- Tests: `tests/integration/test_static_prescription_status.py`
