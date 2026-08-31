from config.schemas import ErrorSchema
from ninja import Router, Status
from product.models import HandbookPage

from handbook.schemas import HandbookListSchema, HandbookPageSchema

router = Router(tags=["Handbook"])


def summary(page):
    return {
        "id": page.pk,
        "slug": page.slug,
        "title": page.title,
        "summary": page.summary,
        "updated_at": page.updated_at,
    }


@router.get("/handbook", response=HandbookListSchema, operation_id="getHandbook", by_alias=True)
def get_handbook(request):
    return {"pages": [summary(page) for page in HandbookPage.objects.filter(published=True)]}


@router.get(
    "/handbook/{slug}",
    response={200: HandbookPageSchema, 404: ErrorSchema},
    operation_id="getHandbookPage",
    by_alias=True,
)
def get_handbook_page(request, slug: str):
    page = HandbookPage.objects.filter(slug=slug, published=True).first()
    if page is None:
        return Status(
            404,
            {
                "code": "handbook_page_not_found",
                "message": "That handbook page was not found.",
                "request_id": request.request_id,
            },
        )
    return {**summary(page), "body_markdown": page.body_markdown, "published_at": page.published_at}
