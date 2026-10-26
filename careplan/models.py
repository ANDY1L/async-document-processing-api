from django.db import models


class Provider(models.Model):
    name = models.CharField(max_length=200)
    npi = models.CharField(max_length=10, unique=True)  # 10 digits, kept as string

    def __str__(self):
        return f"{self.name} ({self.npi})"


class Patient(models.Model):
    mrn = models.CharField(max_length=6, unique=True)  # 6 digits, keep leading zeros
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    dob = models.DateField()

    def __str__(self):
        return f"{self.last_name}, {self.first_name} ({self.mrn})"


class Order(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="orders")
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name="orders")
    medication_name = models.CharField(max_length=200)
    primary_diagnosis = models.CharField(max_length=10)  # ICD-10, e.g. G70.00
    additional_diagnoses = models.JSONField(default=list, blank=True)
    medication_history = models.JSONField(default=list, blank=True)
    patient_records = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    # pharmacy-local calendar day of the order; backs the R1 uniqueness rule
    created_date = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["patient", "medication_name", "created_date"],
                name="uniq_patient_medication_day",  # R1
            ),
        ]


class CarePlan(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        PROCESSING = "processing"
        COMPLETED = "completed"
        FAILED = "failed"

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="careplan")
    content = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    attempts = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
