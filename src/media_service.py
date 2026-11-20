"""Application workflow for nonprofit media uploads."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .infrai_client import InfraiStorage, MultipartPart


class MediaPurpose(str, Enum):
    DONOR_RECEIPT = "donor_receipt"
    VOLUNTEER_REMINDER = "volunteer_reminder"
    CAMPAIGN_REPORT = "campaign_report"


@dataclass(frozen=True)
class MediaUploadRequest:
    campaign: str
    purpose: MediaPurpose
    filename: str
    content_type: str
    size_bytes: int


def object_key(request: MediaUploadRequest) -> str:
    return f"{request.campaign}/{request.purpose.value}/{request.filename}"


def upload_media(client: InfraiStorage, bucket: str, request: MediaUploadRequest, media: Path) -> dict[str, object]:
    key = object_key(request)
    request_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    created = client.create_multipart(bucket, key, request.content_type, request_id)
    upload_id = created["upload_id"]
    try:
        parts = []
        with media.open("rb") as source:
            part_number = 1
            while True:
                chunk = source.read(10_000_000)
                if not chunk and parts:
                    break
                signed = client.presign_part(upload_id, part_number, f"{request_id}-part-{part_number}")
                etag = client.upload_part(signed, chunk)
                parts.append(MultipartPart(part_number, etag))
                part_number += 1
                if not chunk:
                    break
        result = client.complete_multipart(upload_id, parts, f"{request_id}-complete")
    except Exception:
        client.abort_multipart(upload_id)
        raise
    return {"campaign": request.campaign, "purpose": request.purpose.value, "key": key, "object": result}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a large nonprofit media upload.")
    parser.add_argument("media", type=Path)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--purpose", choices=[p.value for p in MediaPurpose], required=True)
    parser.add_argument("--content-type", default="video/mp4")
    parser.add_argument("--bucket", default="nonprofit-media")
    args = parser.parse_args()
    request = MediaUploadRequest(args.campaign, MediaPurpose(args.purpose), args.media.name, args.content_type, args.media.stat().st_size)
    client = InfraiStorage()
    client.create_bucket(args.bucket)
    try:
        result = upload_media(client, args.bucket, request, args.media)
    except Exception:
        client.delete_bucket(args.bucket)
        raise
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
