from config.network import client_address
from config.schemas import ErrorSchema
from identity.attribution import AccountActorMismatch
from identity.auth import installation_auth, session_auth
from ninja import Header, Router, Status

from submissions.rate_limits import SubmissionRateLimited
from submissions.schemas import CoverSubmissionSchema, SubmissionReceiptSchema
from submissions.services import (
    IdempotencyConflict,
    InvalidInstallationActor,
    UnknownVenue,
    accept_cover_submission,
)

router = Router(tags=["Reporting"])


@router.post(
    "/cover-submissions",
    auth=installation_auth,
    response={
        201: SubmissionReceiptSchema,
        401: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
        429: ErrorSchema,
    },
    operation_id="createCoverSubmission",
    by_alias=True,
)
def create_cover_submission(
    request,
    payload: CoverSubmissionSchema,
    x_session_token: str | None = Header(None, alias="X-Session-Token"),
):
    session_account = (
        session_auth.authenticate(request, x_session_token) if x_session_token else None
    )
    try:
        receipt = accept_cover_submission(
            request.auth,
            payload,
            remote_address=client_address(request),
            session_account=session_account,
        )
    except IdempotencyConflict:
        return Status(
            409,
            {
                "code": "idempotency_conflict",
                "message": "That submission ID was already used for different content.",
                "request_id": request.request_id,
            },
        )
    except UnknownVenue:
        return Status(
            422,
            {
                "code": "unknown_venue",
                "message": "The venue is not active or does not exist.",
                "request_id": request.request_id,
            },
        )
    except InvalidInstallationActor:
        return Status(
            401,
            {
                "code": "invalid_installation_token",
                "message": "The installation credential is invalid or expired.",
                "request_id": request.request_id,
            },
        )
    except AccountActorMismatch:
        return Status(
            409,
            {
                "code": "installation_account_mismatch",
                "message": "This installation belongs to another account.",
                "request_id": request.request_id,
            },
        )
    except SubmissionRateLimited:
        return Status(
            429,
            {
                "code": "rate_limited",
                "message": "Too many reports were submitted.",
                "request_id": request.request_id,
            },
        )
    return Status(201, receipt)
