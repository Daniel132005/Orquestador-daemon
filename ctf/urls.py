from django.urls import path

from . import views

urlpatterns = [
    path("challenges/", views.challenge_list, name="challenge-list"),
    path("challenges/submit/", views.submit_flag, name="challenge-submit"),
    path("instance/status/", views.instance_status, name="instance-status"),
    path("instance/start/", views.start_instance, name="instance-start"),
    path("instance/stop/", views.stop_instance, name="instance-stop"),
    path("platform-settings/", views.platform_settings_view, name="platform-settings"),
    path("platform-settings/instances/", views.live_instances_view, name="platform-instances"),
    path("platform-settings/instances/destroy/", views.destroy_container_view, name="platform-instance-destroy"),
    path("platform-settings/users/", views.manage_users_view, name="platform-users"),
    path("platform-settings/users/<int:user_id>/", views.manage_user_detail_view, name="platform-user-detail"),
    path("tutorial-visto/", views.tutorial_visto_view, name="tutorial-visto"),
]
