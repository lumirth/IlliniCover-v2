import uuid

from config.network import client_address
from config.schemas import ErrorSchema
from ninja import Header, Router, Status

from identity.auth import read_only_installation_auth, session_auth
from identity.rate_limits import InstallationIssuanceRateLimited
from identity.schemas import (
    AccountDeletionRequestSchema,
    AccountSchema,
    CurrentInstallationSchema,
    DeletedSchema,
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
    account_deletion_receipt,
    create_installation,
    delete_account,
    link_installation,
    rotate_installation,
)

router = Router(tags=["Identity"])


@router.post(
    "/installations",
    response={201: InstallationIssuedSchema, 409: ErrorSchema, 429: ErrorSchema},
    operation_id="createInstallation",
    by_alias=True,
)
def create_installation_endpoint(request, payload: InstallationRequestSchema):
    try:
        receipt = create_installation(
            request_id=payload.request_id,
            raw_token=payload.installation_token,
            remote_address=client_address(request),
        )
    except IdentityIdempotencyConflict:
        return _error(
            request,
            409,
            "idempotency_conflict",
            "This request UUID was already used with different installation data.",
        )
    except InstallationIssuanceRateLimited:
        return _error(
            request,
            429,
            "rate_limited",
            "Too many installation credentials were requested from this network.",
        )
    return Status(
        201,
        {
            "request_id": receipt.request_id,
            "actor_id": receipt.actor_id,
            "token": payload.installation_token,
        },
    )


@router.get(
    "/installations/current",
    auth=read_only_installation_auth,
    response=CurrentInstallationSchema,
    operation_id="getCurrentInstallation",
    by_alias=True,
)
def get_current_installation(request):
    """Validate one installation credential without mutating actor state."""

    return {"actor_id": request.auth.pk}


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
        receipt = rotate_installation(
            request_id=payload.request_id,
            replacement_token=payload.replacement_installation_token,
            presented_token=x_installation_token,
            remote_address=client_address(request),
        )
    except IdentityIdempotencyConflict:
        return _error(
            request,
            409,
            "idempotency_conflict",
            "This request UUID or replacement credential conflicts with an earlier request.",
        )
    except InvalidInstallationCredential:
        return _error(
            request,
            422,
            "invalid_installation_token",
            "The installation credential is invalid or expired.",
        )
    except InstallationIssuanceRateLimited:
        return _error(
            request,
            429,
            "rate_limited",
            "Too many installation credentials were requested from this network.",
        )
    return Status(
        201,
        {
            "request_id": receipt.request_id,
            "actor_id": receipt.actor_id,
            "token": payload.replacement_installation_token,
        },
    )


@router.get(
    "/me",
    auth=session_auth,
    response=AccountSchema,
    operation_id="getCurrentAccount",
    by_alias=True,
)
def get_me(request):
    return request.auth


@router.delete(
    "/me",
    auth=session_auth,
    response={200: DeletedSchema, 409: ErrorSchema},
    operation_id="deleteCurrentAccount",
    by_alias=True,
)
def delete_me(request, payload: AccountDeletionRequestSchema):
    try:
        receipt = delete_account(request.auth, request_id=payload.request_id)
    except IdentityIdempotencyConflict:
        return _error(
            request,
            409,
            "idempotency_conflict",
            "This deletion request UUID was already completed.",
        )
    return {
        "request_id": receipt.request_id,
        "deleted": True,
        "completed_at": receipt.completed_at,
    }


@router.get(
    "/account-deletions/{request_id}",
    response={200: DeletedSchema, 404: ErrorSchema},
    operation_id="getAccountDeletionStatus",
    by_alias=True,
)
def get_account_deletion_status(request, request_id: uuid.UUID):
    receipt = account_deletion_receipt(request_id)
    if receipt is None:
        return _error(
            request,
            404,
            "deletion_not_found",
            "No completed account deletion was found for this request UUID.",
        )
    return {
        "request_id": receipt.request_id,
        "deleted": True,
        "completed_at": receipt.completed_at,
    }


@router.post(
    "/me/link-installation",
    auth=session_auth,
    response={200: LinkedInstallationSchema, 409: ErrorSchema, 422: ErrorSchema},
    operation_id="linkCurrentInstallation",
    by_alias=True,
)
def link_current_installation(request, payload: LinkInstallationSchema):
    try:
        link = link_installation(
            request.auth,
            payload.request_id,
            payload.installation_token,
        )
    except InstallationAlreadyLinked:
        return Status(
            409,
            {
                "code": "installation_already_linked",
                "message": "This installation belongs to another account.",
                "request_id": request.request_id,
            },
        )
    except IdentityIdempotencyConflict:
        return Status(
            409,
            {
                "code": "idempotency_conflict",
                "message": "This request UUID was already used for another installation link.",
                "request_id": request.request_id,
            },
        )
    if link is None:
        return Status(
            422,
            {
                "code": "invalid_installation_token",
                "message": "The installation credential is invalid or expired.",
                "request_id": request.request_id,
            },
        )
    return {
        "request_id": payload.request_id,
        "actor_id": link.actor_id,
        "account_id": link.account_id,
    }


def _error(request, status: int, code: str, message: str):
    return Status(
        status,
        {
            "code": code,
            "message": message,
            "request_id": request.request_id,
        },
    )
