# Prompt template for care plan generation. Not used yet: the worker (later stage) will call it.
PROMPT = """You are a clinical pharmacist. Write a pharmacist care plan for the patient below.

Include these sections:
1. Problem list / Drug therapy problems (DTPs)
2. Goals (SMART)
3. Pharmacist interventions / plan
4. Monitoring plan

Patient: {patient_first_name} {patient_last_name}
MRN: {patient_mrn}
DOB: {patient_dob}
Referring provider: {provider_name} (NPI: {provider_npi})
Primary diagnosis (ICD-10): {primary_diagnosis}
Additional diagnoses: {additional_diagnoses}
Medication: {medication_name}
Medication history: {medication_history}

Patient records:
{patient_records}
"""
