import json
import os
import re

import anthropic
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from careplan.models import CarePlan, Order, Patient, Provider

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])  # set in .env, never in code

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


def _split(text):
    """'a, b\nc' -> ['a', 'b', 'c']  (form fields arrive as plain strings)."""
    return [x.strip() for x in re.split(r"[,\n]", text or "") if x.strip()]


def _serialize(careplan):
    order = careplan.order
    return {
        "id": careplan.id,
        "status": careplan.status,
        "careplan": careplan.content or careplan.error_message,
        "input": {
            "patient_first_name": order.patient.first_name,
            "patient_last_name": order.patient.last_name,
            "patient_mrn": order.patient.mrn,
            "patient_dob": order.patient.dob.isoformat(),
            "provider_name": order.provider.name,
            "provider_npi": order.provider.npi,
            "primary_diagnosis": order.primary_diagnosis,
            "additional_diagnoses": order.additional_diagnoses,
            "medication_name": order.medication_name,
            "medication_history": order.medication_history,
            "patient_records": order.patient_records,
        },
    }


def create_careplan(request):
    data = json.loads(request.body)

    # 1) Save the order + a care plan in "processing" state, then commit,
    #    so the data is in the database before the slow LLM call starts.
    try:
        with transaction.atomic():
            provider, _ = Provider.objects.get_or_create(
                npi=data["provider_npi"], defaults={"name": data["provider_name"]}
            )
            patient, _ = Patient.objects.get_or_create(
                mrn=data["patient_mrn"],
                defaults={
                    "first_name": data["patient_first_name"],
                    "last_name": data["patient_last_name"],
                    "dob": data["patient_dob"],
                },
            )
            order = Order.objects.create(
                patient=patient,
                provider=provider,
                medication_name=data["medication_name"],
                primary_diagnosis=data["primary_diagnosis"],
                additional_diagnoses=_split(data.get("additional_diagnoses")),
                medication_history=_split(data.get("medication_history")),
                patient_records=data["patient_records"],
                created_date=timezone.localdate(),
            )
            careplan = CarePlan.objects.create(order=order, status=CarePlan.Status.PROCESSING)
    except IntegrityError:
        # R1: same patient + same medication + same day
        return JsonResponse(
            {"careplan": "Duplicate order: this patient already has an order for this medication today."},
            status=409,
        )

    # 2) Synchronous LLM call: this HTTP request blocks here until Claude finishes
    careplan.attempts += 1
    try:
        message = client.messages.create(
            model="claude-opus-5",
            max_tokens=16000,
            messages=[{"role": "user", "content": PROMPT.format(**data)}],
        )
        careplan.content = "".join(b.text for b in message.content if b.type == "text")
        careplan.status = CarePlan.Status.COMPLETED
    except Exception as e:  # keep the order, record the failure
        careplan.status = CarePlan.Status.FAILED
        careplan.error_message = f"Generation failed: {e}"
    careplan.save()

    # re-read so fields come back as proper types (e.g. dob as a date)
    careplan = CarePlan.objects.select_related("order__patient", "order__provider").get(pk=careplan.pk)
    return JsonResponse(_serialize(careplan), status=200 if careplan.status == "completed" else 502)


def get_careplan(request, careplan_id):
    try:
        careplan = CarePlan.objects.select_related("order__patient", "order__provider").get(pk=careplan_id)
    except CarePlan.DoesNotExist:
        raise Http404
    return JsonResponse(_serialize(careplan))
