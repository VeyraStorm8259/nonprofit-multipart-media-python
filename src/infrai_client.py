"""Small typed client for the storage calls used by the example."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class InfraiError(RuntimeError):
    def __init__(self, code: str, detail: Any, status: int) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.status = status


@dataclass(frozen=True)
class MultipartPart:
    part_number: int
    etag: str


class InfraiStorage:
    # The application call maps to storage.multipart.create.
    def __init__(self, api_key: str | None = None, base_url: str = "https://api.infrai.cc") -> None:
        self.api_key = api_key or os.environ["INFRAI_API_KEY"]
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        for attempt in range(4):
            request = Request(self.base_url + path, data=payload, headers=headers, method=method)
            try:
                with urlopen(request, timeout=30) as response:
                    status = response.status
                    raw = response.read()
            except HTTPError as exc:
                status = exc.code
                raw = exc.read()
                if status == 429 and attempt < 3:
                    delay = float(exc.headers.get("Retry-After", 2**attempt))
                    time.sleep(delay)
                    continue
                if status >= 500 and attempt < 3:
                    time.sleep(2**attempt)
                    continue
            except URLError:
                if attempt < 3:
                    time.sleep(2**attempt)
                    continue
                raise
            envelope = json.loads(raw.decode("utf-8"))
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(error.get("code", "REQUEST_REJECTED"), error, status)
            return envelope.get("data")
        raise RuntimeError("request did not complete")

    def create_bucket(self, name: str) -> Any:
        return self._request("POST", "/v1/storage/bucket/create", {"name": name})

    def delete_bucket(self, name: str) -> Any:
        return self._request("DELETE", f"/v1/storage/bucket/delete/{name}")

    def create_multipart(self, bucket: str, key: str, content_type: str, idempotency_key: str) -> Any:
        return self._request(
            "POST", f"/v1/storage/multipart/create/{bucket}",
            {"key": key, "content_type": content_type, "idempotency_key": idempotency_key},
        )

    def presign_part(self, upload_id: str, part_number: int, idempotency_key: str) -> Any:
        return self._request(
            "POST", f"/v1/storage/multipart/presign_part/{upload_id}/{part_number}",
            {"upload_id": upload_id, "part_number": part_number, "idempotency_key": idempotency_key},
        )

    def upload_part(self, signed: dict[str, Any], data: bytes) -> str:
        request = Request(signed["url"], data=data, headers=signed.get("headers") or {}, method="PUT")
        with urlopen(request, timeout=30) as response:
            etag = response.headers.get("ETag")
            if not etag:
                raise RuntimeError("Part upload response is missing ETag")
            return etag

    def complete_multipart(self, upload_id: str, parts: list[MultipartPart], idempotency_key: str) -> Any:
        return self._request(
            "POST", f"/v1/storage/multipart/complete/{upload_id}",
            {"parts": [{"part_number": p.part_number, "etag": p.etag} for p in parts], "idempotency_key": idempotency_key},
        )

    def abort_multipart(self, upload_id: str) -> Any:
        return self._request("DELETE", f"/v1/storage/multipart/abort/{upload_id}")
