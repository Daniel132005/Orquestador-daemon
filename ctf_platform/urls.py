from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from ctf import views as ctf_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="ctf/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    path("api/", include("ctf.urls")),
    path("", ctf_views.terminal_page, name="terminal-page"),
]
