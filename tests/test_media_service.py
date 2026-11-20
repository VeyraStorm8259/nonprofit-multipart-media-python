from src.media_service import MediaPurpose, MediaUploadRequest, object_key


def test_campaign_report_is_stored_under_campaign_namespace():
    request = MediaUploadRequest("spring-drive", MediaPurpose.CAMPAIGN_REPORT, "results.csv", "text/csv", 1200)

    assert object_key(request) == "spring-drive/campaign_report/results.csv"


def test_upload_sends_file_bytes_and_completes_with_upload_etag(tmp_path):
    from src.media_service import upload_media
    from src.infrai_client import MultipartPart

    media = tmp_path / "results.csv"
    media.write_bytes(b"campaign,total\nspring,42\n")
    request = MediaUploadRequest("spring-drive", MediaPurpose.CAMPAIGN_REPORT, media.name, "text/csv", media.stat().st_size)

    class Client:
        def create_multipart(self, bucket, key, content_type, idempotency_key):
            return {"upload_id": "upload-1"}

        def presign_part(self, upload_id, number, idempotency_key):
            assert number == 1
            return {"url": "https://storage.example/part"}

        def upload_part(self, signed, data):
            assert data == media.read_bytes()
            return '"uploaded-etag"'

        def complete_multipart(self, upload_id, parts, idempotency_key):
            assert parts == [MultipartPart(1, '"uploaded-etag"')]
            return {"key": "stored"}

        def abort_multipart(self, upload_id):
            raise AssertionError("Unexpected abort")

    assert upload_media(Client(), "bucket", request, media)["object"] == {"key": "stored"}
