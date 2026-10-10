"""Sync source documents from backend/data/dataset into Supabase Storage.

Usage:
    python backend/scripts/sync_storage.py

The script does not touch the documents/chunks tables. It only ensures the
configured Storage bucket exists and uploads the original source files using
the document_id already stored in Supabase.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
BUCKET = os.environ.get("SUPABASE_BUCKET", "chanakya-docs")
DATASET = ROOT / "backend" / "data" / "dataset"

if not SUPABASE_URL or not SERVICE_KEY:
    raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
}


def request(method: str, path: str, **kwargs) -> requests.Response:
    response = requests.request(
        method,
        f"{SUPABASE_URL}{path}",
        headers={**HEADERS, **kwargs.pop("headers", {})},
        timeout=120,
        **kwargs,
    )
    return response


def ensure_bucket() -> None:
    response = request(
        "POST",
        "/storage/v1/bucket",
        json={"id": BUCKET, "name": BUCKET, "public": False},
        headers={"Content-Type": "application/json"},
    )
    if response.status_code in (200, 201):
        print(f"[OK] Created Storage bucket: {BUCKET}")
        return
    if response.status_code in (400, 409) and (
        "already exists" in response.text.lower()
        or "duplicate" in response.text.lower()
        or "id" in response.text.lower()
    ):
        print(f"[OK] Storage bucket already exists: {BUCKET}")
        return
    raise RuntimeError(
        f"Could not create/check bucket {BUCKET}: "
        f"HTTP {response.status_code} {response.text[:500]}"
    )


def get_documents() -> list[dict]:
    response = request(
        "GET",
        "/rest/v1/documents?select=document_id,name,department,status&order=name",
    )
    if not response.ok:
        raise RuntimeError(
            f"Could not read documents: HTTP {response.status_code} "
            f"{response.text[:500]}"
        )
    return response.json()


def upload_document(document: dict) -> bool:
    name = document["name"]
    source = DATASET / name
    if not source.is_file():
        print(f"[SKIP] Missing local source: {source}")
        return False

    object_path = f'{document["document_id"]}_{name}'
    encoded_path = quote(object_path, safe="/")
    suffix = source.suffix.lower()
    content_type = {
        ".pdf": "application/pdf",
        ".csv": "text/csv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(suffix, "application/octet-stream")

    with source.open("rb") as handle:
        response = request(
            "POST",
            f"/storage/v1/object/{quote(BUCKET, safe='')}/{encoded_path}",
            data=handle,
            headers={
                "Content-Type": content_type,
                "x-upsert": "true",
            },
        )

    if response.ok:
        print(f"[OK] {name} -> {object_path} ({source.stat().st_size:,} bytes)")
        return True

    print(f"[FAIL] {name}: HTTP {response.status_code} {response.text[:500]}")
    return False


def main() -> None:
    print(f"Supabase: {SUPABASE_URL}")
    print(f"Bucket:   {BUCKET}")
    print(f"Dataset:  {DATASET}")
    print()

    if not DATASET.is_dir():
        raise SystemExit(f"Dataset directory does not exist: {DATASET}")

    ensure_bucket()
    documents = get_documents()
    print(f"[INFO] Supabase documents: {len(documents)}")

    uploaded = 0
    skipped = 0
    failed = 0

    for document in documents:
        if upload_document(document):
            uploaded += 1
        elif (DATASET / document["name"]).is_file():
            failed += 1
        else:
            skipped += 1

    print()
    print(f"Done. Uploaded/updated: {uploaded}, missing: {skipped}, failed: {failed}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
