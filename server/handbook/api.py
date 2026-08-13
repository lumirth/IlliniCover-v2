from config.schemas import ErrorSchema
from covers.api import CACHEABLE_OPENAPI, conditional_response
from django.http import HttpResponse
from ninja import Header, Router, Status

from handbook.models import HandbookPage
from handbook.schemas import HandbookListSchema, HandbookPageSchema

router = Router(tags=["Handbook"])


def summary(page: HandbookPage) -> dict:
    return {
        "id": page.id,
        "slug": page.slug,
        "title": page.title,
        "summary": page.summary,
        "updated_at": page.updated_at,
    }


@router.get(
    "/handbook",
    response={200: HandbookListSchema, 304: None},
    operation_id="getHandbook",
    by_alias=True,
    openapi_extra=CACHEABLE_OPENAPI,
)
def get_handbook(
    request, response: HttpResponse, if_none_match: str | None = Header(None, alias="If-None-Match")
):
    pages = HandbookPage.objects.filter(status=HandbookPage.Status.PUBLISHED)
    body = {"pages": [summary(page) for page in pages]}
    not_modified = conditional_response(response, body, if_none_match)
    if not_modified:
        return not_modified
    return body


@router.get(
    "/handbook/{slug}",
    response={200: HandbookPageSchema, 304: None, 404: ErrorSchema},
    operation_id="getHandbookPage",
    by_alias=True,
    openapi_extra=CACHEABLE_OPENAPI,
)
def get_handbook_page(
    request,
    slug: str,
    response: HttpResponse,
    if_none_match: str | None = Header(None, alias="If-None-Match"),
):
    page = HandbookPage.objects.filter(slug=slug, status=HandbookPage.Status.PUBLISHED).first()
    if page is None:
        return Status(
            404,
            {
                "code": "handbook_page_not_found",
                "message": "That handbook page was not found.",
                "request_id": request.request_id,
            },
        )
    body = {
        **summary(page),
        "body_markdown": page.body_markdown,
        "published_at": page.published_at,
    }
    not_modified = conditional_response(response, body, if_none_match)
    if not_modified:
        return not_modified
    return body
