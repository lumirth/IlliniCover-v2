from allauth.mfa.utils import is_mfa_enabled
from django.shortcuts import redirect


class AdminMfaEnrollmentMiddleware:
    """Keep every authenticated staff account out of Admin until TOTP is enrolled."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            request.path.startswith("/admin/")
            and request.path != "/admin/logout/"
            and user.is_authenticated
            and user.is_staff
            and not is_mfa_enabled(user, types=["totp"])
        ):
            return redirect("mfa_activate_totp")
        return self.get_response(request)
