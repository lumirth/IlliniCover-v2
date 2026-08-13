import json
import os

from django.core.exceptions import ImproperlyConfigured


def _load_secret_bundle() -> dict[str, str]:
    raw = os.environ.get("ILLINICOVER_SECRETS_JSON", "")
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ImproperlyConfigured("ILLINICOVER_SECRETS_JSON must be valid JSON") from error
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()
    ):
        raise ImproperlyConfigured("ILLINICOVER_SECRETS_JSON must be an object of string values")
    return value


SECRET_BUNDLE = _load_secret_bundle()


def secret_value(
    environment_name: str,
    *,
    bundle_name: str | None = None,
    default: str = "",
    required: bool = False,
) -> str:
    value = os.environ.get(environment_name)
    if value is None:
        value = SECRET_BUNDLE.get(bundle_name or environment_name, default)
    if required and not value:
        raise ImproperlyConfigured(f"{environment_name} is required")
    return value
