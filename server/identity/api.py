from config.network import client_address
from config.schemas import ErrorSchema
from ninja import Header, Router, Status

from identity.auth import session_auth
from identity.rate_limits import InstallationIssuanceRateLimited
from identity.schemas import (
    AccountSchema,
    InstallationIssuedSchema,
    InstallationRequestSchema,
    LinkedInstallationSchema,
    LinkInstallationSchema,
    RotateInstallationSchema,
)
from identity.services import (
    IdentityIdempotencyConflict,
    InstallationAlreadyLinked,
    InvalidInstallationCredential,
    create_installation,
    delete_account,
    link_installation,
    rotate_installation,
)

router = Router(tags=["Identity"])


def error(request, status, code, message):
    return Status(status, {"code": code, "message": message, "request_id": request.request_id})


@router.post(
    "/installations",
    response={201: InstallationIssuedSchema, 409: ErrorSchema, 429: ErrorSchema},
    operation_id="createInstallation",
    by_alias=True,
)
def create_installation_endpoint(request, payload: InstallationRequestSchema):
    try:
        actor = create_installation(payload.installation_token, client_address(request))
    except IdentityIdempotencyConflict:
        return error(request, 409, "credential_conflict", "That credential is already in use.")
    except InstallationIssuanceRateLimited:
        return error(request, 429, "rate_limited", "Too many credentials were requested.")
    return Status(201, {"actor_id": actor.pk})


@router.post(
    "/installations/rotate",
    response={201: InstallationIssuedSchema, 409: ErrorSchema, 422: ErrorSchema, 429: ErrorSchema},
    operation_id="rotateInstallation",
    by_alias=True,
)
def rotate_current_installation(
    request,
    payload: RotateInstallationSchema,
    x_installation_token: str | None = Header(None, alias="X-Installation-Token"),
):
    try:
        actor = rotate_installation(
            payload.replacement_installation_token,
            x_installation_token,
            client_address(request),
        )
    except IdentityIdempotencyConflict:
        return error(request, 409, "credential_conflict", "That credential is already in use.")
    except InvalidInstallationCredential:
        return error(request, 422, "invalid_installation_token", "The credential is invalid.")
    except InstallationIssuanceRateLimited:
        return error(request, 429, "rate_limited", "Too many credentials were requested.")
    return Status(201, {"actor_id": actor.pk})


@router.get(
    "/me",
    auth=session_auth,
    response={200: AccountSchema, 401: ErrorSchema},
    operation_id="getCurrentAccount",
    by_alias=True,
)
def get_me(request):
    return request.auth


@router.delete(
    "/me",
    auth=session_auth,
    response={204: None, 401: ErrorSchema},
    operation_id="deleteCurrentAccount",
)
def delete_me(request):
    delete_account(request.auth)
    return Status(204, None)


@router.post(
    "/me/link-installation",
    auth=session_auth,
    response={
        200: LinkedInstallationSchema,
        401: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
    },
    operation_id="linkCurrentInstallation",
    by_alias=True,
)
def link_current_installation(request, payload: LinkInstallationSchema):
    try:
        actor = link_installation(request.auth, payload.installation_token)
    except InstallationAlreadyLinked:
        return error(
            request,
            409,
            "installation_already_linked",
            "This installation belongs to another account.",
        )
    if actor is None:
        return error(request, 422, "invalid_installation_token", "The credential is invalid.")
    return {"actor_id": actor.pk, "account_id": request.auth.pk}
