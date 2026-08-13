from config.schemas import ErrorSchema
from django.conf import settings
from identity.auth import session_auth
from ninja import Router, Status

from billing.entitlements import authorization_entitlements, entitlement_is_active
from billing.models import AccountEntitlement
from billing.schemas import (
    EntitlementsSchema,
    RevenueCatEnvelopeSchema,
    WebhookReceiptSchema,
)
from billing.webhooks import accept_revenuecat_event, verify_revenuecat_request

router = Router(tags=["Billing"])


@router.get(
    "/me/entitlements",
    auth=session_auth,
    response=EntitlementsSchema,
    operation_id="getCurrentEntitlements",
    by_alias=True,
)
def get_current_entitlements(request):
    # The environment remains visible in the durable provider mirror for
    # operations and reconciliation, while access is deliberately aggregated:
    # TestFlight uses the production app/backend with Apple sandbox purchases.
    entitlements = list(
        AccountEntitlement.objects.filter(
            account=request.auth,
            entitlement_identifier=settings.REVENUECAT_PREMIUM_ENTITLEMENT,
        )
    )
    if not entitlements:
        return {"entitlements": []}
    authoritative = authorization_entitlements(entitlements)
    active = [
        entitlement for entitlement in authoritative if entitlement_is_active(entitlement)
    ]
    selected = max(active or authoritative, key=lambda entitlement: entitlement.updated_at)
    return {
        "entitlements": [
            {
                "identifier": selected.entitlement_identifier,
                "is_active": bool(active),
                "expires_at": max(
                    (entitlement.expires_at for entitlement in active),
                    default=None,
                    key=lambda value: (value is not None, value),
                ),
                "updated_at": max(entitlement.updated_at for entitlement in entitlements),
            }
        ]
    }


@router.post(
    "/billing/revenuecat-webhook",
    response={200: WebhookReceiptSchema, 401: ErrorSchema},
    operation_id="receiveRevenueCatWebhook",
    by_alias=True,
)
def receive_revenuecat_webhook(request, payload: RevenueCatEnvelopeSchema):
    if not verify_revenuecat_request(request):
        return Status(
            401,
            {
                "code": "invalid_webhook_signature",
                "message": "The webhook could not be authenticated.",
                "request_id": request.request_id,
            },
        )
    _event, duplicate = accept_revenuecat_event(payload)
    return {"received": True, "duplicate": duplicate}
