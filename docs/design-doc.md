# Async Document Processing API — Design Doc

**First document type:** Pharmacist care plans

## 1. Background

The client is a specialty pharmacy (CVS). Pharmacists need to manually write a care plan for every patient order. These care plans serve two primary purposes: satisfying compliance requirements and supporting reimbursement from Medicare and pharmaceutical companies.

- **Pain Point:** Each care plan takes approximately 20–40 minutes to complete. The pharmacy is severely understaffed and has accumulated a significant backlog of work.
- **Goal:** After a healthcare worker enters the patient's information, an LLM automatically generates a care plan, significantly reducing the amount of manual time required per patient.

### Why Async

LLM generation takes tens of seconds and can fail because of timeouts, rate limits, or refusals. Holding an HTTP request open for that long gives a poor user experience and risks gateway timeouts. The system is therefore built as an **async document-processing API**: requests are accepted and persisted immediately, and generation happens in a background worker whose progress the client polls. The care plan is the first document type. The pipeline (submit → queue → worker → LLM → quality check → store) is independent of the document type.

---

## 2. Users and Use Cases

| Item | Description |
| --- | --- |
| Users | CVS healthcare workers, including medical assistants and pharmacists |
| Non-users | Patients do not directly interact with the system |
| When Used | A care plan is required when a medication order is placed |
| Output | The care plan can be printed for the patient or downloaded and uploaded into the pharmacy's existing system |

### Main Workflow

```
Form Input
    ↓
Validation
    ↓
Duplicate Detection
    │
    ├── ERROR → Block submission
    │
    └── WARNING → Require user confirmation
                     ↓
          Save Order + CarePlan (queued)
                     ↓
        Enqueue Job → Return 202 + Order ID
                     ↓
     Worker Generates Care Plan with LLM
                     ↓
      Frontend Polls Status → Display on Page
                     ↓
              Download as .txt
                     │
                     └── Export report for pharma
```

---

## 3. Scope

### In Scope — All Required

1. Web-based form input with validation for every field.
2. Patient duplicate detection and order duplicate detection.
3. Provider duplicate detection so that the same provider is only entered once in the system.
4. Asynchronous LLM-based care plan generation, with status tracking and retry.
5. Downloading the generated care plan as a text file.
6. Exporting reports for pharmaceutical companies.

### Out of Scope for Now

- Patient-facing interface.
- Authentication and authorization, since they are not mentioned in the current requirements. See Section 10.
- Integration with external EHR systems.

---

## 4. Input Fields and Validation Rules

| Field | Type | Validation Rule |
| --- | --- | --- |
| Patient First Name | string | Required; cannot contain only whitespace |
| Patient Last Name | string | Required; cannot contain only whitespace |
| Patient DOB | date | Required; cannot be later than today. DOB is not included in the original field list but is required for duplicate detection. See Section 10. |
| Patient MRN | string | Required; exactly 6 digits. Store as a string to preserve leading zeros. |
| Referring Provider | string | Required |
| Referring Provider NPI | string | Required; exactly 10 digits. A Luhn/check-digit validation may optionally be added. |
| Primary Diagnosis | ICD-10 code | Required; must follow ICD-10 format, e.g. `G70.00` |
| Additional Diagnoses | list of ICD-10 codes | Optional; every provided item must follow ICD-10 format |
| Medication Name | string | Required |
| Medication History | list of strings | Optional |
| Patient Records | string or PDF | Required; exactly one of the supported input forms must be provided. PDF content must first be converted to text. |

Validation must be enforced on the backend. Frontend validation may be provided for a better user experience, but it must not replace backend validation.

---

## 5. Duplicate Detection Rules

| # | Scenario | Level | Handling | Reason |
| --- | --- | --- | --- | --- |
| R1 | Same patient + same medication + same day | **ERROR** | Block submission | Definitely a duplicate submission |
| R2 | Same patient + same medication + different day | **WARNING** | Allow after user confirmation | May represent a refill |
| R3 | Same MRN, but different name or DOB | **WARNING** | Allow after user confirmation | May indicate a data-entry error |
| R4 | Same name and DOB, but different MRN | **WARNING** | Allow after user confirmation | May represent the same patient |
| R5 | Same NPI, but different provider name | **ERROR** | Must be corrected | NPI is the provider's unique identifier |

### Implementation Details

- "Same patient" is determined using the MRN.
- Before comparing names, leading and trailing whitespace should be removed and comparisons should be case-insensitive.
- "Same day" should be calculated using the pharmacy's local timezone.
- **WARNING confirmation flow:** On the first submission, the backend returns all warnings without creating the order. The frontend displays the warnings to the user. If the user confirms, the frontend submits the request again with `confirm=true`.
- ERROR conditions must reject the request regardless of whether `confirm=true` is provided.
- R1 and R5 should be enforced both at the application layer and, where appropriate, at the database layer using uniqueness constraints to protect against race conditions in which two concurrent requests both pass the application-level checks.

---

## 6. Data Model

```
Provider (1) ──< Order >── (1) Patient
                   │
                   └── (1) CarePlan
```

| Entity | Key Fields | Constraints |
| --- | --- | --- |
| **Provider** | id, name, npi | `npi` is unique |
| **Patient** | id, mrn, first_name, last_name, dob | `mrn` is unique |
| **Order** | id, patient_id, provider_id, medication_name, primary_diagnosis, additional_diagnoses, medication_history, patient_records, created_at | (patient, medication, created_date) is unique, corresponding to R1 |
| **CarePlan** | id, order_id, content, status, attempts, error_message, created_at, updated_at | One-to-one relationship with Order. `status` is one of `queued`, `processing`, `completed`, `failed`. |

### Design Notes

- One care plan corresponds to one order, and each order contains exactly one medication.
- A Provider should only be stored once. When an order is submitted, the system first looks up the Provider by NPI. If the Provider already exists, that record is reused. If the submitted provider name does not match the existing record, R5 is triggered.
- Diagnosis information, medication history, and related clinical information represent a clinical snapshot for a specific order. Therefore, they are stored on the Order rather than the Patient.

---

## 7. Care Plan Generation

### Input

The LLM receives all relevant fields from the Order, together with the patient's clinical records.

If the patient records are provided as a PDF, the text must first be extracted before being passed to the LLM.

### Required Output

Every generated Care Plan must contain the following four sections:

1. Problem List / Drug Therapy Problems (DTPs)
2. Goals (SMART)
3. Pharmacist Interventions / Plan
4. Monitoring Plan & Lab Schedule

### Quality Check

After generation, the system checks whether all four required sections are present.

If one or more required sections are missing, the generation should either:

- Be marked as failed, or
- Be retried.

The exact retry strategy is TBD.

### Error Handling

If the LLM:

- Times out,
- Is rate limited,
- Refuses to answer, or
- Otherwise fails,

the system should return a clear error message to the user.

The already-created Order must be preserved.

The user should be able to retry Care Plan generation without re-entering the entire order.

The system should not simply return an unhandled HTTP 500 error.

---

### Asynchronous Processing

Generation runs in a background worker, never inside the HTTP request.

```
Request
   ↓
Validate + Duplicate Detection
   ↓
Create Order + CarePlan (status = queued)   ← same DB transaction
   ↓
Enqueue Generation Job (after commit)
   ↓
Return 202 + Order ID
   ↓
Worker: status = processing → call LLM → quality check
   ↓
status = completed (content saved) | failed (error_message saved)
   ↓
Frontend polls GET /api/orders/<id>/
```

State machine:

```
queued ──> processing ──> completed
                │
                └──> failed ──(regenerate)──> queued
```

Rules:

- The job is enqueued only after the database transaction commits, so a worker never picks up a job whose Order is not yet visible.
- The worker is idempotent: it only processes a CarePlan in `queued` state and moves it to `processing` atomically, so a duplicated job does not produce two LLM calls.
- Transient failures (timeouts, rate limits) are retried automatically with exponential backoff up to a bounded number of attempts. Permanent failures (refusal, missing sections after retries) move the CarePlan to `failed`.
- A CarePlan stuck in `processing` beyond a timeout (e.g. the worker crashed) is treated as failed and can be regenerated.
- Proposed stack: Celery with Redis as the broker. The choice is revisited in v2 if a simpler DB-backed queue is enough.

---

## 8. API Design — Draft

| Method | Path | Description |
| --- | --- | --- |
| GET | `/` | Display the order input form |
| POST | `/api/orders/` | Validate → duplicate detection → create order → enqueue Care Plan generation. Returns `202 Accepted` with the order ID and `status: queued`. Request body may include `confirm: true`. |
| GET | `/api/orders/<id>/` | Retrieve the Order and its Care Plan status; includes content once `completed` and `error_message` if `failed` |
| GET | `/api/orders/<id>/careplan.txt` | Download the Care Plan as a text file |
| POST | `/api/orders/<id>/regenerate/` | Re-enqueue a Care Plan whose generation `failed`. Returns `202`; returns `409` if it is not in `failed` state. |
| GET | `/api/reports/export.csv?from=&to=` | Export a pharma report for the specified date range |

### Standard Error and Warning Format

```json
{
  "errors": [
    {
      "code": "DUPLICATE_ORDER_SAME_DAY",
      "field": null,
      "message": "..."
    }
  ],
  "warnings": [
    {
      "code": "MRN_NAME_MISMATCH",
      "message": "..."
    }
  ]
}
```

### Initial Pharma Report Columns

The initial export format should include:

- order_id
- Date
- Patient MRN
- Patient Name
- Provider Name
- Provider NPI
- Medication
- Primary Diagnosis
- Additional Diagnoses
- Care Plan Status

The exact report requirements still need to be confirmed with the client.

---

## 9. Production-Ready Requirements

| Requirement | Proposed Solution |
| --- | --- |
| Every input is validated | Use Django Forms or serializers to enforce all validation rules defined in Section 4 on the backend |
| Integrity rules are always enforced | Application-level checks plus database uniqueness constraints for NPI, MRN, and same-day duplicate orders |
| Errors are safe, clear, and bounded | Use a standardized error format; never expose stack traces to users; LLM failures must not destroy already-saved data |
| Code is modular and easy to navigate | Separate responsibilities for validation, duplicate detection, LLM integration, and report export |
| Critical logic has automated tests | Cover validation rules, duplicate rules R1–R5, and report export; mock the LLM during tests |
| Runs out of the box | A single `docker compose up` should start the required services, including the web application, worker, queue broker, and database, with sample data available |
| Long-running work never blocks requests | LLM calls run only in the background worker; the API responds within milliseconds with `202` |

---

## 10. Open Questions

### 1. MRN Length Inconsistency

The requirements state that the MRN should contain exactly 6 digits, but the example data contains:

```
00012345
```

which contains 8 digits.

For now, the implementation assumes 6 digits, but this needs to be confirmed with the client.

### 2. DOB Is Missing From the Original Input Field List

DOB is not included in the original input fields.

However, duplicate detection rules R3 and R4 require DOB.

For now, DOB will be added as a required field, but this should be confirmed with the client.

### 3. PDF Processing

The requirements do not specify the exact level of PDF support.

Questions include:

- Should the system only support PDFs with extractable text?
- Should scanned PDFs also be supported?
- If scanned PDFs are supported, is OCR required?
- What is the maximum allowed file size?

### 4. Pharma Report Format

The exact reporting requirements are unclear.

Questions include:

- Which columns does pharma require?
- Is CSV sufficient?
- Is another format required?

### 5. Authentication and Audit Logging

The system processes healthcare-related information and may therefore be subject to HIPAA-related security and privacy requirements.

Questions include:

- Is authentication required?
- Are different user roles required?
- Is audit logging required?
- Which actions must be recorded?

Authentication and auditing are out of scope for the current version, but they should be documented as risks and clarified before production deployment.

### 6. Status Updates: Polling vs. Push

The design uses polling for simplicity. Questions include:

- Is a polling interval of a few seconds acceptable to users?
- Is server push (SSE or WebSockets) worth the extra infrastructure later?

The decision to generate asynchronously itself is settled. See Section 7, Asynchronous Processing.

---

## 11. Iteration Plan

Each iteration adds one major capability on top of the previous version. This allows us to first experience the limitations of the simpler implementation before introducing additional infrastructure to solve those problems.

| Stage | Implementation | Problem Being Addressed |
| --- | --- | --- |
| **v0 — Current MVP** | Django + in-memory dictionary + synchronous LLM call | First make the entire end-to-end workflow work |
| v1 | Introduce PostgreSQL and implement the data model from Section 6, including CarePlan `status` | In-memory data disappears after restart and cannot be shared between the web process and a worker |
| v2 | Introduce asynchronous generation using a queue + worker (Celery + Redis), `202` responses, and frontend status polling | LLM generation blocks HTTP requests for tens of seconds and can cause request timeouts |
| v3 | Add form validation and standardized error responses | Invalid input may currently result in unexpected failures or HTTP 500 responses |
| v4 | Implement duplicate detection R1–R5 and the WARNING confirmation workflow | Prevent duplicate patients/orders and enforce business rules |
| v5 | Add reliability: automatic retries with backoff, section quality check, stuck-job recovery, and the regenerate endpoint | LLM calls fail in several ways, and failures must not lose orders |
| v6 | Add Care Plan text download and CSV report export | Complete the required business functionality |
| v7 | Add PDF upload and text extraction as a pipeline step in the worker | Support patient records provided as PDF documents |

Automated tests are written alongside each stage rather than as a separate stage, with the LLM mocked.
