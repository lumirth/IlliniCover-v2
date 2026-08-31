from billing.api import router as billing_router
from covers.api import router as cover_router
from deals.api import router as deal_router
from handbook.api import router as handbook_router
from identity.api import router as identity_router
from ninja import NinjaAPI, Schema
from ninja.errors import AuthenticationError, HttpError, ValidationError
from submissions.api import router as submission_router


class StatusSchema(Schema):
    status: str


api = NinjaAPI(
    title="IlliniCover",
    description="Product-shaped API for the native IlliniCover clients.",
    urls_namespace="api",
    docs_url="/docs",
)


def error_response(request, code: str, message: str, status: int):
    return api.create_response(
        request,
        {
            "code": code,
            "message": message,
            "requestId": getattr(request, "request_id", "unknown"),
        },
        status=status,
    )


@api.exception_handler(AuthenticationError)
def authentication_error(request, _error):
    return error_response(request, "authentication_required", "Authentication is required.", 401)


@api.exception_handler(ValidationError)
def validation_error(request, _error):
    return error_response(request, "invalid_request", "The request was not valid.", 422)


@api.exception_handler(HttpError)
def http_error(request, error):
    return error_response(request, "request_failed", str(error), error.status_code)


@api.get("/status", response=StatusSchema, operation_id="getStatus", tags=["Operations"])
def status(request):
    return {"status": "ok"}


api.add_router("", identity_router)
api.add_router("", cover_router)
api.add_router("", submission_router)
api.add_router("", deal_router)
api.add_router("", handbook_router)
api.add_router("", billing_router)
