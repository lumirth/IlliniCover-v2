import pytest
from allauth.mfa.models import Authenticator
from billing.models import AccountEntitlement, ProviderDeletionRequest, RevenueCatEvent
from django.contrib import admin
from django.contrib.staticfiles import finders
from django.test import Client, RequestFactory
from identity.models import (
    Account,
    AccountDeletionReceipt,
    ActorAccountLink,
    ActorAccountLinkReceipt,
    IdentityRateBucket,
    InstallationActor,
    InstallationOperationReceipt,
)


@pytest.mark.django_db
def test_admin_login_uses_allauth_and_unenrolled_staff_are_sent_to_totp_enrollment():
    staff = Account.objects.create_superuser("admin@example.com", "correct-horse")
    client = Client()

    anonymous = client.get("/admin/login/")
    client.force_login(staff)
    unenrolled = client.get("/admin/")
    Authenticator.objects.create(user=staff, type=Authenticator.Type.TOTP, data={"secret": "x"})
    enrolled = client.get("/admin/")

    assert anonymous.status_code == 302
    assert "/admin-auth/login/" in anonymous.headers["Location"]
    assert unenrolled.status_code == 302
    assert "/admin-auth/2fa/totp/activate/" in unenrolled.headers["Location"]
    assert enrolled.status_code == 200


def test_admin_css_is_collected_for_self_contained_runtime():
    assert finders.find("admin/css/base.css") is not None


@pytest.mark.django_db
def test_account_admin_cannot_bypass_privacy_erasure_service():
    staff = Account.objects.create_superuser("privacy-admin@example.com", "correct-horse")
    request = RequestFactory().get("/admin/identity/account/")
    request.user = staff
    model_admin = admin.site._registry[Account]

    assert model_admin.has_delete_permission(request) is False
    assert "delete_selected" not in model_admin.get_actions(request)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model",
    [
        InstallationActor,
        InstallationOperationReceipt,
        AccountDeletionReceipt,
        IdentityRateBucket,
        ActorAccountLink,
        ActorAccountLinkReceipt,
        AccountEntitlement,
        RevenueCatEvent,
        ProviderDeletionRequest,
    ],
)
def test_identity_and_provider_receipts_have_no_admin_mutation_path(model):
    staff = Account.objects.create_superuser(f"{model._meta.model_name}@example.com", "secret")
    request = RequestFactory().get(f"/admin/{model._meta.app_label}/{model._meta.model_name}/")
    request.user = staff
    model_admin = admin.site._registry[model]

    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False
    assert "delete_selected" not in model_admin.get_actions(request)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "/accounts/login/",
        "/accounts/signup/",
        "/accounts/password/reset/",
        "/accounts/password/change/",
        "/accounts/2fa/",
    ],
)
def test_public_headed_account_and_password_routes_are_not_exposed(path):
    assert Client().get(path).status_code == 404
