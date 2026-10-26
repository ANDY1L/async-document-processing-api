"""Load mock providers / patients / orders / care plans.

    python manage.py seed_mock_data           # add mock data (safe to re-run)
    python manage.py seed_mock_data --reset   # wipe the 4 tables first
"""
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from careplan.models import CarePlan, Order, Patient, Provider

PROVIDERS = [
    {"name": "Dr. Emily Carter", "npi": "1234567893"},
    {"name": "Dr. Raj Patel", "npi": "1245319599"},
    {"name": "Dr. Maria Gonzalez", "npi": "1679576722"},
    {"name": "Dr. Kevin Brooks", "npi": "1003000126"},
]

PATIENTS = [
    {"mrn": "000101", "first_name": "Alice", "last_name": "Johnson", "dob": date(1958, 3, 14)},
    {"mrn": "000102", "first_name": "Bob", "last_name": "Smith", "dob": date(1972, 11, 2)},
    {"mrn": "000103", "first_name": "Carol", "last_name": "Nguyen", "dob": date(1985, 7, 29)},
    {"mrn": "000104", "first_name": "David", "last_name": "Lee", "dob": date(1949, 1, 8)},
    {"mrn": "000105", "first_name": "Eva", "last_name": "Martinez", "dob": date(1991, 5, 21)},
    {"mrn": "000106", "first_name": "Frank", "last_name": "Wilson", "dob": date(1966, 9, 30)},
]

# mrn, provider npi, medication, primary dx, additional dx, history, records, status, days_ago
ORDERS = [
    ("000101", "1234567893", "IVIG", "G70.00", ["I10", "E11.9"],
     ["Pyridostigmine 60 mg TID", "Prednisone 20 mg daily"],
     "68F with generalized myasthenia gravis, worsening proximal weakness and ptosis over 3 weeks. "
     "Hypertension controlled on lisinopril. Type 2 diabetes, A1c 7.2%. No prior IVIG exposure.",
     "completed", 10),
    ("000102", "1245319599", "Humira (adalimumab)", "K50.90", ["D50.9"],
     ["Mesalamine 2.4 g daily", "Azathioprine 150 mg daily"],
     "52M with Crohn's disease, inadequate response to azathioprine. Mild iron-deficiency anemia. "
     "TB screen negative, hepatitis B surface antigen negative.",
     "completed", 7),
    ("000103", "1679576722", "Ocrevus (ocrelizumab)", "G35", [], [],
     "39F relapsing-remitting multiple sclerosis, 2 relapses in the last 12 months, new T2 lesions on MRI. "
     "Treatment-naive. Planning pregnancy in 2-3 years.",
     "processing", 0),
    ("000104", "1003000126", "Eliquis (apixaban)", "I48.91", ["N18.3", "I10", "E78.5"],
     ["Warfarin 5 mg daily (stopped 2026-08)", "Metoprolol 50 mg BID", "Atorvastatin 40 mg"],
     "77M atrial fibrillation, CHA2DS2-VASc 5. CKD stage 3 (eGFR 48). Labile INR on warfarin. "
     "Weight 72 kg, age >=75, dose review needed.",
     "queued", 0),
    ("000105", "1234567893", "Dupixent (dupilumab)", "L20.9", ["J45.909"],
     ["Triamcinolone 0.1% cream", "Cetirizine 10 mg daily"],
     "35F moderate-to-severe atopic dermatitis with comorbid asthma. Failed topical steroids and "
     "calcineurin inhibitors. EASI score 24.",
     "failed", 3),
    ("000106", "1245319599", "Ozempic (semaglutide)", "E11.65", ["E66.9", "I10"],
     ["Metformin 1000 mg BID"],
     "59M type 2 diabetes with hyperglycemia, BMI 33. A1c 8.6% on metformin alone. "
     "No personal/family history of MTC or MEN2.",
     "completed", 14),
    # same patient, different medication (for duplicate-detection testing later)
    ("000101", "1234567893", "Soliris (eculizumab)", "G70.00", ["I10"],
     ["IVIG 2 g/kg"],
     "68F gMG, refractory to IVIG. Meningococcal vaccination up to date.",
     "queued", 1),
]

SAMPLE_CAREPLAN = """## 1. Problem list / Drug therapy problems
- Response to {med} needs monitoring; interactions and adherence risks reviewed.

## 2. Goals (SMART)
- Clinical improvement documented at follow-up within 12 weeks.

## 3. Pharmacist interventions / plan
- Counsel on administration, adverse effects and when to call.

## 4. Monitoring plan
- Labs and symptom review at weeks 2, 6 and 12.

(mock data)"""


class Command(BaseCommand):
    help = "Insert mock providers, patients, orders and care plans."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing rows first")

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts["reset"]:
            CarePlan.objects.all().delete()
            Order.objects.all().delete()
            Patient.objects.all().delete()
            Provider.objects.all().delete()
            self.stdout.write("Existing data deleted.")

        providers = {p["npi"]: Provider.objects.get_or_create(npi=p["npi"], defaults=p)[0] for p in PROVIDERS}
        patients = {p["mrn"]: Patient.objects.get_or_create(mrn=p["mrn"], defaults=p)[0] for p in PATIENTS}

        new = 0
        for mrn, npi, med, dx, extra, history, records, status, days_ago in ORDERS:
            patient = patients[mrn]
            if Order.objects.filter(patient=patient, medication_name=med).exists():
                continue
            when = timezone.now() - timedelta(days=days_ago)
            order = Order.objects.create(
                patient=patient, provider=providers[npi], medication_name=med,
                primary_diagnosis=dx, additional_diagnoses=extra, medication_history=history,
                patient_records=records, created_date=timezone.localdate(when),
            )
            Order.objects.filter(pk=order.pk).update(created_at=when)  # backdate
            CarePlan.objects.create(
                order=order, status=status,
                content=SAMPLE_CAREPLAN.format(med=med) if status == "completed" else "",
                attempts={"completed": 1, "processing": 1, "failed": 3}.get(status, 0),
                error_message="LLM request timed out after 3 attempts" if status == "failed" else "",
            )
            new += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. providers={Provider.objects.count()} patients={Patient.objects.count()} "
            f"orders={Order.objects.count()} careplans={CarePlan.objects.count()} (new orders: {new})"
        ))
