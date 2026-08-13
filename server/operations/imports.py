import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.core.management.base import CommandError
from django.utils import timezone

from operations.models import DatasetImportRun, DatasetRelease


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_release(
    manifest_path: str | Path, dataset_path: str | Path
) -> tuple[DatasetRelease, Path]:
    manifest_file = Path(manifest_path).resolve()
    dataset_file = Path(dataset_path).resolve()
    if not manifest_file.is_file() or not dataset_file.is_file():
        raise CommandError("Manifest and dataset paths must identify files")
    manifest = json.loads(manifest_file.read_text())
    relative_dataset = dataset_file.relative_to(manifest_file.parent).as_posix()
    artifact = next(
        (item for item in manifest.get("artifacts", []) if item["path"] == relative_dataset), None
    )
    if artifact is None:
        raise CommandError(f"Manifest does not declare {relative_dataset}")
    content_hash = sha256_file(dataset_file)
    if content_hash != artifact["sha256"]:
        raise CommandError(f"Hash mismatch for {dataset_file}")
    release, _ = DatasetRelease.objects.get_or_create(
        name=manifest["dataset_release"],
        content_hash=content_hash,
        defaults={
            "schema_version": str(manifest["schema_version"]),
            "importer_version": "django-import-v1",
            "source_manifest": manifest,
        },
    )
    return release, dataset_file


@contextmanager
def import_run(release: DatasetRelease):
    run = DatasetImportRun.objects.create(
        release=release, code_revision=getattr(settings, "CODE_REVISION", "development")
    )
    try:
        yield run
    except Exception:
        run.result = "failed"
        run.completed_at = timezone.now()
        run.save(update_fields=["result", "completed_at"])
        raise
    else:
        run.result = "succeeded"
        run.completed_at = timezone.now()
        run.save(
            update_fields=[
                "rows_seen",
                "rows_accepted",
                "rows_rejected",
                "result",
                "completed_at",
            ]
        )


def jsonl_rows(path: Path):
    with path.open() as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as error:
                    raise CommandError(f"Invalid JSON at {path}:{line_number}") from error
