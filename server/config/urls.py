from allauth.account import views as account_views
from allauth.account.decorators import secure_admin_login
from django.contrib import admin
from django.urls import include, path
from identity.views import email_verification_sent_placeholder

from config.api import api
from config.health import live, ready
from config.public import privacy_policy

admin.autodiscover()
admin.site.login = secure_admin_login(admin.site.login)  # type: ignore[method-assign]

urlpatterns = [
    path("health/live", live, name="health-live"),
    path("health/ready", ready, name="health-ready"),
    path("privacy", privacy_policy, name="privacy-policy"),
    path("api/v2/", api.urls),
    path("_allauth/", include("identity.headless_urls")),
    path("admin-auth/login/", account_views.login, name="account_login"),
    path("admin-auth/logout/", account_views.logout, name="account_logout"),
    path(
        "admin-auth/email-verification-sent/",
        email_verification_sent_placeholder,
        name="account_email_verification_sent",
    ),
    path("admin-auth/2fa/", include("allauth.mfa.urls")),
    path("admin/", admin.site.urls),
]
