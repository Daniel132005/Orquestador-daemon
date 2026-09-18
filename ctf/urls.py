from django.urls import path

from . import views

urlpatterns = [
    path("challenges/", views.challenge_list, name="challenge-list"),
    path("challenges/submit/", views.submit_flag, name="challenge-submit"),
    path("instance/status/", views.instance_status, name="instance-status"),
    path("instance/start/", views.start_instance, name="instance-start"),
    path("instance/stop/", views.stop_instance, name="instance-stop"),
]
