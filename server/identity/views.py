from django.http import HttpResponse


def email_verification_sent_placeholder(request):
    """Named flow target required internally by allauth Headless signup."""

    return HttpResponse(status=204)
