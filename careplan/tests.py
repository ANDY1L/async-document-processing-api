import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from careplan.models import CarePlan, Order, Patient, Provider

PAYLOAD = {
    "patient_first_name": "Test", "patient_last_name": "Patient", "patient_mrn": "999001",
    "patient_dob": "1980-01-01", "provider_name": "Dr. Test", "provider_npi": "1234567893",
    "primary_diagnosis": "G70.00", "additional_diagnoses": "I10, E11.9",
    "medication_name": "IVIG", "medication_history": "Drug A\nDrug B", "patient_records": "notes",
}


def fake_llm(text="PLAN"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


class CarePlanViewTests(TestCase):
    def post(self, data=PAYLOAD):
        return self.client.post("/api/careplans/", json.dumps(data), content_type="application/json")

    @patch("careplan.views.client.messages.create", return_value=fake_llm())
    def test_create_saves_rows_and_completes(self, _):
        resp = self.post()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["careplan"], "PLAN")
        self.assertEqual((Provider.objects.count(), Patient.objects.count(), Order.objects.count()), (1, 1, 1))
        cp = CarePlan.objects.get()
        self.assertEqual((cp.status, cp.attempts, cp.content), ("completed", 1, "PLAN"))
        self.assertEqual(Order.objects.get().additional_diagnoses, ["I10", "E11.9"])
        self.assertEqual(Order.objects.get().medication_history, ["Drug A", "Drug B"])

    @patch("careplan.views.client.messages.create", return_value=fake_llm())
    def test_get_reads_from_database(self, _):
        cid = self.post().json()["id"]
        resp = self.client.get(f"/api/careplans/{cid}/")
        self.assertEqual(resp.json()["input"]["patient_mrn"], "999001")
        self.assertEqual(self.client.get("/api/careplans/9999/").status_code, 404)

    @patch("careplan.views.client.messages.create", return_value=fake_llm())
    def test_same_day_duplicate_is_rejected(self, _):
        self.post()
        self.assertEqual(self.post().status_code, 409)
        self.assertEqual(Order.objects.count(), 1)

    @patch("careplan.views.client.messages.create", side_effect=RuntimeError("boom"))
    def test_llm_failure_keeps_order_and_marks_failed(self, _):
        resp = self.post()
        self.assertEqual(resp.status_code, 502)
        cp = CarePlan.objects.get()
        self.assertEqual(cp.status, "failed")
        self.assertIn("boom", cp.error_message)
