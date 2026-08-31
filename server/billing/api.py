from config.schemas import ErrorSchema
from identity.auth import session_auth
from ninja import Router, Status
from product.models import AccountEntitlement

from billing.entitlements import entitlement_is_active
from billing.revenuecat import RevenueCatRequestError
from billing.schemas import EntitlementsSchema, RevenueCatEnvelopeSchema, WebhookReceiptSchema
from billing.webhooks import accept_revenuecat_event, verify_revenuecat_request

router = Router(tags=["Billing"])


@router.get(
    "/me/entitlements",
    auth=session_auth,
    response={200: EntitlementsSchema, 401: ErrorSchema},
    operation_id="getCurrentEntitlements",
    by_alias=True,
)
def get_current_entitlements(request):
    entitlement = AccountEntitlement.objects.filter(account=request.auth).first()
    if entitlement is None:
        return {"entitlements": []}
    return {
        "entitlements": [
            {
                "identifier": "premium",
                "is_active": entitlement_is_active(entitlement),
                "expires_at": entitlement.expires_at,
                "updated_at": entitlement.updated_at,
            }
        ]
    }


@router.post(
    "/billing/revenuecat-webhook",
    response={200: WebhookReceiptSchema, 401: ErrorSchema, 503: ErrorSchema},
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
    try:
        _, duplicate = accept_revenuecat_event(payload)
    except RevenueCatRequestError:
        return Status(
            503,
            {
                "code": "provider_unavailable",
                "message": "The provider snapshot could not be read.",
                "request_id": request.request_id,
            },
        )
    return {"received": True, "duplicate": duplicate}
