from django.urls import path

from careplan import views

urlpatterns = [
    path("", views.index),
    path("api/careplans/", views.create_careplan),
    path("api/careplans/<int:careplan_id>/", views.get_careplan),
]
