# NoHarm API Reference

All endpoints are JSON REST. Authenticated endpoints require a JWT Bearer token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

Tokens are obtained from `POST /authenticate`. Endpoints marked **[admin]** additionally require administrator privileges.

---

## Response envelope

**Success**
```json
{ "status": "success", "data": <payload> }
```

**Error**
```json
{ "status": "error", "message": "...", "code": "error.key" }
```

**Validation error**
```json
{ "status": "error", "message": "Parâmetros inválidos", "validations": [...] }
```

---

## Authentication

| Method | Path | Description |
|---|---|---|
| `POST` | `/authenticate` | Authenticate with email + password. Returns `access_token` and `refresh_token`. |
| `POST` | `/auth-provider` | Authenticate via OAuth provider. |
| `GET` | `/auth-provider/<schema>` | Get OAuth provider configuration for a schema. |
| `POST` | `/refresh-token` | Exchange a refresh token for a new access token. |
| `GET` | `/switch-schema` | Get available schemas for the current user. |
| `POST` | `/switch-schema` | Switch the active schema (multi-tenant). |

### POST /authenticate
```json
{
  "email": "pharmacist@hospital.br",
  "password": "...",
  "schema": null,
  "extraFeatures": []
}
```

---

## Prescriptions

| Method | Path | Description |
|---|---|---|
| `GET` | `/prescriptions` | List and prioritize prescriptions. See query params below. |
| `GET` | `/prescriptions/<idPrescription>` | Get a single prescription with all drugs and alerts. |
| `PUT` | `/prescriptions/<idPrescription>` | Update prescription fields. |
| `POST` | `/prescriptions/status` | Set prescription checked/unchecked status. |
| `POST` | `/prescriptions/review` | Mark prescription as reviewed. |
| `POST` | `/prescriptions/start-evaluation` | Start pharmacist evaluation session. |
| `GET` | `/prescriptions/search` | Search prescriptions by patient name/record (`?term=`). |
| `GET` | `/prescriptions/pep-link` | Get PEP system deep-link (`?idPrescription=`). |
| `GET` | `/prescriptions/<idPrescription>/update` | Get prescription updates since last load. |
| `GET` | `/prescriptions/drug/<idPrescriptionDrug>/period` | Get drug dosing period (`?future=true`). |
| `PUT` | `/prescriptions/drug/<idPrescriptionDrug>` | Update prescription drug note/annotation. |
| `PUT` | `/prescriptions/drug/form` | Update drug form fields. |
| `GET` | `/prescriptions/drug/<idPrescriptionDrug>/check-history` | Get drug check history. |

### GET /prescriptions — query parameters

| Param | Type | Description |
|---|---|---|
| `idSegment` | int | Filter by segment |
| `idSegment[]` | int[] | Filter by multiple segments |
| `idDept[]` | int[] | Filter by departments |
| `startDate` | date | Start date (default: today) |
| `endDate` | date | End date |
| `pending` | bool | Show only pending (default: false) |
| `agg` | bool | Aggregated view (default: false) |
| `concilia` | bool | Conciliation view |
| `allDrugs` | bool | Include all drugs |
| `alertLevel` | string | `low`, `medium`, `high` |
| `globalScoreMin` | int | Minimum risk score |
| `globalScoreMax` | int | Maximum risk score |
| `ageMin` | int | Minimum patient age |
| `ageMax` | int | Maximum patient age |
| `insurance` | string | Filter by insurance |
| `patientStatus` | string | Patient status filter |
| `prescriber` | string | Filter by prescriber name |
| `medical_record` | int | Filter by medical record number |

### Prescription CRUD (CPOE)

| Method | Path | Description |
|---|---|---|
| `POST` | `/editPrescription/drug` | Create a new prescription drug item. |
| `PUT` | `/editPrescription/drug/<idPrescriptionDrug>` | Update a prescription drug item. |
| `PUT` | `/editPrescription/drug/<idPrescriptionDrug>/suspend/<suspend>` | Suspend (`1`) or unsuspend (`0`) a drug. |
| `GET` | `/editPrescription/<idPrescription>/missing-drugs` | List drugs present in the previous prescription but missing from the current one. |
| `POST` | `/editPrescription/<idPrescription>/missing-drugs/copy` | Copy missing drugs from the previous prescription. |

---

## Patients

| Method | Path | Description |
|---|---|---|
| `POST` | `/patient/list` | List patients with filters (JSON body). |
| `GET` | `/patient` | List patients (legacy, query params). |
| `POST` | `/patient/<admissionNumber>` | Save/update patient data (weight, allergies, notes, etc.). |
| `GET` | `/patient/<admissionNumber>/observation-history` | Get patient observation history. |

---

## Interventions

| Method | Path | Description |
|---|---|---|
| `GET` | `/intervention/reasons` | List available intervention reason categories. |
| `PUT` | `/intervention` | Create or update a clinical intervention. |
| `POST` | `/intervention/search` | Search interventions with filters. |
| `GET` | `/intervention/outcome-data` | Get data needed to record an outcome (`?idIntervention=&edit=`). |
| `POST` | `/intervention/set-outcome` | Record the outcome of an intervention. |

### PUT /intervention — body
```json
{
  "idPrescriptionDrug": "12345",
  "idPrescription": "0",
  "idInterventionReason": 3,
  "error": false,
  "cost": null,
  "observation": "Dose adjustment recommended",
  "status": "s"
}
```

Set `idPrescriptionDrugList` (array of ints) to save the same intervention on multiple drugs at once.

---

## Drugs & Substances

### Drugs

| Method | Path | Description |
|---|---|---|
| `GET` | `/drugs` | List outlier drugs (`?idDrug[]&q=&group=`). |
| `GET` | `/drugs/<idSegment>` | List outlier drugs for a specific segment. |
| `GET` | `/drugs/summary/<idSegment>/<idDrug>` | Get drug scoring summary. |
| `GET` | `/drugs/frequencies` | List all available frequencies. |
| `GET` | `/drugs/attributes/<idSegment>/<idDrug>` | Get drug attributes for a segment. |
| `POST` | `/drugs/attributes` | Save drug attributes. |
| `POST` | `/drugs/substance` | Link a drug to a substance. |
| `GET` | `/drugs/unit-conversion/<idDrug>` | List unit conversions for a drug. |
| `POST` | `/drugs/unit-conversion/<idDrug>` | Save unit conversion for a drug. |
| `POST` | `/drugs/process-scores/<idDrug>` | Trigger score processing for a drug. |
| `GET` | `/drugs/dashboard/<idSegment>/<idDrug>` | Get drug dashboard data (`?dose=&frequency=`). |
| `GET` | `/drugs/resources/<idDrug>/<idSegment>` | Get drug resource summary. |

### Outliers

| Method | Path | Description |
|---|---|---|
| `PUT` | `/outliers/<idOutlier>` | Set a manual outlier value. |

### Substances

| Method | Path | Description |
|---|---|---|
| `GET` | `/substance` | List all substances. |
| `GET` | `/substance/find` | Find substance by name (`?term=`). |
| `GET` | `/substance/handling` | Get handling information (`?sctid=&alertType=`). |
| `GET` | `/substance/class` | List all substance classes. |
| `GET` | `/substance/class/find` | Find substance class by name (`?term=`). |

---

## Exams

| Method | Path | Description |
|---|---|---|
| `GET` | `/exams/<admissionNumber>` | Get exams for a patient (`?idSegment=`). |
| `GET` | `/exams/types/list` | List available exam types. |
| `POST` | `/exams/create-multiple` | Create multiple exam records. |
| `POST` | `/exams/delete` | Delete an exam record. |

---

## Segments & Departments

| Method | Path | Description |
|---|---|---|
| `GET` | `/segments` | List segments available to the current user. |
| `GET` | `/segments/departments` | List departments for the current schema. |

---

## Clinical Notes

| Method | Path | Description |
|---|---|---|
| `GET` | `/notes/<admissionNumber>/v2` | Get clinical notes for a patient (`?date=`). |
| `GET` | `/notes/single/<idClinicalNotes>` | Get a single clinical note. |
| `POST` | `/notes` | Create a clinical note. |
| `POST` | `/notes/<idNote>` | Update a clinical note. |
| `POST` | `/notes/remove-annotation` | Remove an annotation from a note. |
| `GET` | `/notes/get-user-last` | Get the current user's last notes (`?admissionNumber=`). |

---

## Patient Summary (AI)

| Method | Path | Description |
|---|---|---|
| `GET` | `/summary/<admissionNumber>` | Get structured patient summary (`?mock=true` for testing). |
| `POST` | `/summary/prompt` | Send a custom prompt to the LLM for a patient. |

---

## Conciliation

| Method | Path | Description |
|---|---|---|
| `GET` | `/conciliation/list-available` | List conciliations available for an admission (`?admissionNumber=`). |
| `POST` | `/conciliation/create` | Create a new conciliation. |
| `POST` | `/conciliation/copy` | Copy an existing conciliation. |

---

## Protocols

| Method | Path | Description |
|---|---|---|
| `GET` | `/protocol/list` | List and filter clinical protocols. |

---

## Regulation

| Method | Path | Description |
|---|---|---|
| `POST` | `/regulation/prioritization` | Get prioritized regulation solicitation list. |
| `GET` | `/regulation/view/<id>` | Get solicitation details. |
| `POST` | `/regulation/create` | Create a new solicitation. |
| `POST` | `/regulation/move` | Move solicitation to the next stage. |
| `GET` | `/regulation/types` | List regulation types. |
| `GET` | `/regulation/attribute/list` | List solicitation attributes. |
| `POST` | `/regulation/attribute/create` | Create a solicitation attribute. |
| `POST` | `/regulation/attribute/remove/<idAttribute>` | Remove a solicitation attribute. |

---

## Tags

| Method | Path | Description |
|---|---|---|
| `GET` | `/tag/list` | List and filter tags. |

---

## Memory (Configuration Records)

Schema-scoped key-value configuration records.

| Method | Path | Description |
|---|---|---|
| `GET` | `/memory` | List editable memory records. |
| `GET` | `/memory/<kind>` | Get memory by kind key. |
| `GET` | `/memory/id/<idMemory>` | Get memory by ID. |
| `PUT` | `/memory` | Create or update a memory record. |
| `PUT` | `/memory/<idMemory>` | Update a specific memory record. |
| `PUT` | `/memory/unique/<kind>` | Create or update a unique-keyed memory record. |
| `PUT` | `/memory/custom-forms` | Create or update custom forms memory. |

---

## Users

| Method | Path | Description |
|---|---|---|
| `PUT` | `/user` | Update current user's password. |
| `GET` | `/users/search` | Search users by name (`?term=`). |
| `GET` | `/user/forget` | Request password reset email (`?email=`). |
| `POST` | `/user/reset` | Reset password with token. |
| `GET` | `/user-admin/list` | List all schema users. |
| `POST` | `/user-admin/upsert` | Create or update a user. |
| `POST` | `/user-admin/reset-token` | Get a password reset token for a user. |

---

## Support & Knowledge Base

| Method | Path | Description |
|---|---|---|
| `GET` | `/support/list-tickets/v2` | List support tickets. |
| `GET` | `/support/list-pending` | List pending tickets. |
| `POST` | `/support/create-ticket` | Create a support ticket. |
| `POST` | `/support/create-closed-ticket` | Create a ticket answered by AI. |
| `POST` | `/support/attachment` | Add attachment to a ticket. |
| `POST` | `/support/ask-n0` | Ask the n0 AI agent. |
| `POST` | `/support/ask-n0-form` | Ask the n0 AI agent via form. |
| `POST` | `/support/knowledge-base-articles` | List knowledge base articles. |
| `POST` | `/support/related-articles` | Get KB articles related to a topic. |
| `GET` | `/support/list-requesters` | List ticket requesters. |

---

## Reports

| Method | Path | Description |
|---|---|---|
| `GET` | `/reports/config` | Get available reports configuration. |
| `GET` | `/reports/general/<report>` | Download a general report (`?id_report=&filename=`). |
| `GET` | `/reports/culture` | Get microbiology cultures for a patient (`?idPatient=`). |
| `GET` | `/reports/drug-attributes/history` | Get drug attribute change history (`?admissionNumber=&attribute=`). |
| `POST` | `/reports/regulation/indicators-panel` | Get regulation indicators panel data. |
| `POST` | `/reports/regulation/indicators-panel-csv` | Download regulation indicators as CSV. |
| `GET` | `/reports/regulation/indicators-summary` | Get regulation indicators summary. |

---

## Admin Endpoints

All endpoints in this section require administrator-level authorization.

### Drug Management

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/drug/attributes-list` | List all drug attributes across the schema. |
| `GET` | `/admin/drug/ref` | Get reference drug data by SNOMED CT (`?sctid=`). |
| `POST` | `/admin/drug/copy-attributes` | Copy drug attributes from reference. |
| `POST` | `/admin/drug/predict-substance` | AI-predict substance for unmapped drugs. |
| `GET` | `/admin/drug/get-missing-substance` | List drugs with no substance mapping. |
| `POST` | `/admin/drug/add-new-outlier` | Manually add an outlier entry. |
| `POST` | `/admin/drug/calculate-dosemax` | Bulk-calculate max dose for drugs. |

### Substance Management

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/substance/list` | List substances with filters. |
| `GET` | `/admin/substance/<id>` | Get substance detail. |
| `POST` | `/admin/substance` | Create or update a substance. |

### Frequency Management

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/frequency/list` | List frequencies. |
| `PUT` | `/admin/frequency` | Update a frequency. |
| `POST` | `/admin/frequency/infer` | AI-infer frequency from free text. |

### Unit & Conversion Management

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/unit/list` | List measurement units. |
| `PUT` | `/admin/unit` | Update a unit. |
| `POST` | `/admin/unit-conversion/list` | List unit conversions. |
| `POST` | `/admin/unit-conversion/predictions` | Get AI-predicted conversions. |
| `POST` | `/admin/unit-conversion/save` | Save unit conversions. |
| `POST` | `/admin/unit-conversion/add-default-units` | Add default units for a drug. |
| `POST` | `/admin/unit-conversion/copy-unit-conversion` | Copy unit conversions between drugs. |
| `POST` | `/admin/unit-conversion/llm-suggest` | Get LLM-suggested unit conversions. |

### Exam Management

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/exam/types` | List exam types. |
| `POST` | `/admin/exam/list` | List segment exams. |
| `POST` | `/admin/exam/get` | Get a specific segment exam. |
| `POST` | `/admin/exam/upsert` | Create or update a segment exam. |
| `POST` | `/admin/exam/order` | Set exam display order. |
| `GET` | `/admin/exam/list-global` | List global exam definitions. |
| `POST` | `/admin/exam/copy` | Copy exams between segments. |
| `GET` | `/admin/exam/most-frequent` | Get most frequently used exams. |
| `POST` | `/admin/exam/most-frequent/add` | Add an exam to the most-frequent list. |
| `POST` | `/admin/global-exam/list` | List global exam configurations. |
| `POST` | `/admin/global-exam/upsert` | Create or update a global exam configuration. |

### Segment & Department Management

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/segments` | Create or update a segment. |
| `GET` | `/admin/segments/departments/<idSegment>` | Get departments for a segment. |
| `POST` | `/admin/segments/departments` | Create or update a department. |

### Drug Relations (Interactions)

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/relation/list` | List drug relations/interactions. |
| `POST` | `/admin/relation` | Create or update a drug relation. |

### Protocol Management

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/protocol/list` | List clinical protocols. |
| `POST` | `/admin/protocol/upsert` | Create or update a protocol. |

### Intervention Reasons

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/intervention-reason` | List all intervention reasons. |
| `POST` | `/admin/intervention-reason` | Create or update an intervention reason. |

### Tags

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/tag/list` | List all tags. |
| `POST` | `/admin/tag/upsert` | Create or update a tag. |

### Memory & Configuration

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/memory/list` | List admin memory records. |
| `PUT` | `/admin/memory` | Create or update an admin memory record. |
| `POST` | `/admin/global-memory/list` | List global memory entries. |
| `POST` | `/admin/global-memory/update` | Update a global memory entry. |

### Knowledge Base

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/knowledge-base/list` | List knowledge base entries. |
| `POST` | `/admin/knowledge-base/upsert` | Create or update a knowledge base entry. |

### Custom Reports

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/report/list` | List custom reports. |
| `POST` | `/admin/report` | Create or update a custom report. |
| `PATCH` | `/admin/report/<idReport>/graphs` | Update report graph configuration. |
| `GET` | `/reports/integration/nifilint` | Download NiFi lint archive. |

### Integration & Schema Management

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/integration/list` | List schema integrations. |
| `GET` | `/admin/integration/status` | Get integration status. |
| `POST` | `/admin/integration/update` | Update integration configuration. |
| `POST` | `/admin/integration/create-schema` | Create a new client schema. |
| `POST` | `/admin/integration/refresh-prescription` | Force prescription refresh. |
| `POST` | `/admin/integration/init-intervention-reason` | Initialize default intervention reasons. |
| `GET` | `/admin/integration/template-list` | List integration templates. |
| `POST` | `/admin/integration/get-cloud-config` | Get cloud configuration. |
| `POST` | `/admin/integration/upsert-getname` | Configure patient name service. |
| `POST` | `/admin/integration/upsert-security-group` | Configure security group. |
| `POST` | `/admin/integration/update-user-security-group` | Update user security group assignment. |
| `POST` | `/admin/integration/create-return-logstream` | Create return log stream. |
| `GET` | `/admin/integration-remote/template` | Get remote integration template. |
| `GET` | `/admin/integration-remote/queue-status` | Get queue status (`?idQueueList[]=`). |
| `POST` | `/admin/integration-remote/push-queue-request` | Push a request to the integration queue. |
| `GET` | `/admin/integration-remote/get-errors` | Get integration errors. |

---

## Score Generation

Endpoints that trigger background outlier and scoring jobs.

| Method | Path | Description |
|---|---|---|
| `GET` | `/outliers/generate/refresh-agg` | Refresh aggregated prescription data. |
| `POST` | `/outliers/generate/segment` | Generate scores for an entire segment. |
| `POST` | `/outliers/generate/config/<idSegment>/<idDrug>` | Configure scoring parameters for a drug. |
| `POST` | `/outliers/generate/config/<idSegment>/<idDrug>/v2` | Configure scoring parameters (v2). |
| `POST` | `/outliers/generate/prepare/<idSegment>/<idDrug>` | Prepare data for scoring. |
| `POST` | `/outliers/generate/single/<idSegment>/<idDrug>` | Generate scores for a single drug. |
| `POST` | `/outliers/generate/add-history/<idSegment>/<idDrug>` | Add historical data. **[admin]** |
| `POST` | `/outliers/generate/remove-outlier/<idSegment>/<idDrug>` | Remove an outlier entry. **[admin]** |

---

## Queue

| Method | Path | Description |
|---|---|---|
| `GET` | `/queue/status/<requestId>` | Get async queue job status by request ID. |

---

## Navigation

| Method | Path | Description |
|---|---|---|
| `POST` | `/navigation/copy` | Copy a patient to the navigation module. |

---

## Names (Patient Name Proxy)

Proxy endpoints to the external patient name service.

| Method | Path | Description |
|---|---|---|
| `GET` | `/names/<idPatient>` | Get name for a single patient. |
| `POST` | `/names` | Get names for multiple patients (batch). |
| `GET` | `/names/auth-token` | Get internal service auth token. |
| `GET` | `/names/search/<term>` | Search patients by name. |
