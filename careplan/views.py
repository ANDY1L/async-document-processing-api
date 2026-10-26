import json
import logging
import os
import re

import redis
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from careplan.models import CarePlan, Order, Patient, Provider

logger = logging.getLogger(__name__)

redis_client = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
QUEUE_KEY = "careplan:queue"  # Redis list; a worker will pop ids from here later



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

    # 1) Save the order + a care plan (status "queued") and commit.
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
            careplan = CarePlan.objects.create(order=order, status=CarePlan.Status.QUEUED)
    except IntegrityError:
        # R1: same patient + same medication + same day
        return JsonResponse(
            {"careplan": "Duplicate order: this patient already has an order for this medication today."},
            status=409,
        )

    # 2) Put the care plan id on the Redis queue (only the id, not the data).
    #    Done after the transaction committed, so a worker will always find the row.
    try:
        redis_client.rpush(QUEUE_KEY, careplan.id)
    except redis.RedisError:
        # The order is safely stored with status "queued"; a later recovery
        # stage can re-enqueue it. Don't lose the user's request over this.
        logger.exception("Could not enqueue careplan %s", careplan.id)

    # 3) Return immediately: "received", not "done".
    return JsonResponse({"id": careplan.id, "status": careplan.status, "message": "Received"}, status=202)


def get_careplan(request, careplan_id):
    try:
        careplan = CarePlan.objects.select_related("order__patient", "order__provider").get(pk=careplan_id)
    except CarePlan.DoesNotExist:
        raise Http404
    return JsonResponse(_serialize(careplan))
