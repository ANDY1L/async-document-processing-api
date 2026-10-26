import json
from unittest.mock import patch

import redis
from django.test import TestCase

from careplan.models import CarePlan, Order, Patient, Provider

PAYLOAD = {
    "patient_first_name": "Test", "patient_last_name": "Patient", "patient_mrn": "999001",
    "patient_dob": "1980-01-01", "provider_name": "Dr. Test", "provider_npi": "1234567893",
    "primary_diagnosis": "G70.00", "additional_diagnoses": "I10, E11.9",
    "medication_name": "IVIG", "medication_history": "Drug A\nDrug B", "patient_records": "notes",
}


@patch("careplan.views.redis_client")  # no real Redis in tests
class CarePlanViewTests(TestCase):
    def post(self, data=PAYLOAD):
        return self.client.post("/api/careplans/", json.dumps(data), content_type="application/json")

    def test_create_saves_rows_enqueues_and_returns_202(self, mock_redis):
        resp = self.post()
        self.assertEqual(resp.status_code, 202)
        body = resp.json()
        self.assertEqual(body["status"], "queued")
        self.assertEqual((Provider.objects.count(), Patient.objects.count(), Order.objects.count()), (1, 1, 1))
        cp = CarePlan.objects.get()
        self.assertEqual((cp.status, cp.attempts, cp.content), ("queued", 0, ""))
        mock_redis.rpush.assert_called_once_with("careplan:queue", cp.id)
        self.assertEqual(body["id"], cp.id)
        self.assertEqual(Order.objects.get().additional_diagnoses, ["I10", "E11.9"])
        self.assertEqual(Order.objects.get().medication_history, ["Drug A", "Drug B"])

    def test_get_reads_from_database(self, _):
        cid = self.post().json()["id"]
        resp = self.client.get(f"/api/careplans/{cid}/")
        self.assertEqual(resp.json()["input"]["patient_mrn"], "999001")
        self.assertEqual(resp.json()["status"], "queued")
        self.assertEqual(self.client.get("/api/careplans/9999/").status_code, 404)

    def test_same_day_duplicate_is_rejected_and_not_enqueued(self, mock_redis):
        self.post()
        self.assertEqual(self.post().status_code, 409)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(mock_redis.rpush.call_count, 1)

    def test_redis_down_still_keeps_order_as_queued(self, mock_redis):
        mock_redis.rpush.side_effect = redis.ConnectionError("down")
        resp = self.post()
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(CarePlan.objects.get().status, "queued")
