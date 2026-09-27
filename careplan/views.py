import json

import anthropic
from django.http import JsonResponse
from django.shortcuts import render

# The "database": just an in-process dict. Restart the container and all data is gone.
CAREPLANS = {}
NEXT_ID = 1

client = anthropic.Anthropic()  # reads the key from the ANTHROPIC_API_KEY env var

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


def index(request):
    return render(request, "careplan/index.html")


def create_careplan(request):
    global NEXT_ID
    data = json.loads(request.body)

    # Synchronous LLM call: this HTTP request blocks here until Claude finishes
    message = client.messages.create(
        model="claude-opus-5",
        max_tokens=16000,
        messages=[{"role": "user", "content": PROMPT.format(**data)}],
    )
    text = "".join(block.text for block in message.content if block.type == "text")

    careplan_id = NEXT_ID
    NEXT_ID += 1
    CAREPLANS[careplan_id] = {"id": careplan_id, "input": data, "careplan": text}
    return JsonResponse(CAREPLANS[careplan_id])


def get_careplan(request, careplan_id):
    return JsonResponse(CAREPLANS[careplan_id])
