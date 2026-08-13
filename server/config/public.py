from __future__ import annotations

from html import escape

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET


def _policy_html(markdown: str) -> str:
    blocks: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{' '.join(paragraph)}</p>")
            paragraph.clear()

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            continue
        if line.startswith("# "):
            flush_paragraph()
            blocks.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("## "):
            flush_paragraph()
            blocks.append(f"<h2>{escape(line[3:])}</h2>")
        else:
            paragraph.append(escape(line))
    flush_paragraph()
    body = "\n".join(blocks)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IlliniCover privacy policy</title>
  <style>
    :root {{ color-scheme: light dark; font-family: ui-rounded, system-ui, sans-serif; }}
    body {{ margin: 0; background: #f7f3e8; color: #17253c; }}
    main {{ max-width: 44rem; margin: 0 auto; padding: 3rem 1.25rem 5rem; }}
    h1 {{ color: #cf4c1c; font-size: clamp(2rem, 8vw, 3.25rem); line-height: 1; }}
    h2 {{ margin-top: 2.25rem; font-size: 1.25rem; }}
    p {{ line-height: 1.65; }}
    @media (prefers-color-scheme: dark) {{
      body {{ background: #111827; color: #f8f3e7; }}
      h1 {{ color: #ff7a3d; }}
    }}
  </style>
</head>
<body><main>{body}</main></body>
</html>"""


@require_GET
@cache_control(public=True, max_age=3_600)
def privacy_policy(_request):
    policy_path = settings.REPOSITORY_DIR / "docs" / "privacy-policy.md"
    response = HttpResponse(
        _policy_html(policy_path.read_text(encoding="utf-8")),
        content_type="text/html; charset=utf-8",
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
