import unittest
from unittest.mock import patch

from infra import storage


class FakeS3:
    def __init__(self):
        self.calls = []

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.calls.append((operation, Params, ExpiresIn))
        return "https://storage.example/upload"

    def copy_object(self, **kwargs):
        self.calls.append(("copy", kwargs))

    def delete_object(self, **kwargs):
        self.calls.append(("delete", kwargs))

    def create_multipart_upload(self, **kwargs):
        self.calls.append(("create-multipart", kwargs))
        return {"UploadId": "upload-123"}

    def complete_multipart_upload(self, **kwargs):
        self.calls.append(("complete-multipart", kwargs))
        return {"ETag": "assembled"}

    def abort_multipart_upload(self, **kwargs):
        self.calls.append(("abort-multipart", kwargs))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeS3()

    def test_presigned_upload_is_scoped_to_quarantine_object(self):
        with patch.object(storage, "_client", return_value=self.client), \
             patch.object(storage.settings, "s3_bucket_quarantine", "quarantine"):
            url = storage.presign_upload("quarantine", "abc.stl")
        self.assertEqual(url, "https://storage.example/upload")
        operation, params, expiry = self.client.calls[0]
        self.assertEqual(operation, "put_object")
        self.assertEqual(params["Bucket"], "quarantine")
        self.assertEqual(params["Key"], "quarantine/abc.stl")
        self.assertEqual(expiry, 21600)

    def test_multipart_upload_urls_and_completion_are_scoped(self):
        with patch.object(storage, "_client", return_value=self.client), \
             patch.object(storage.settings, "s3_bucket_quarantine", "quarantine"):
            upload_id = storage.initiate_multipart_upload("quarantine", "abc.stl")
            url = storage.presign_upload_part(
                "quarantine", "abc.stl", upload_id, 2
            )
            storage.complete_multipart_upload(
                "quarantine", "abc.stl", upload_id,
                [{"PartNumber": 1, "ETag": '"abc"'}],
            )

        self.assertEqual(upload_id, "upload-123")
        self.assertEqual(url, "https://storage.example/upload")
        operation, params, expiry = self.client.calls[1]
        self.assertEqual(operation, "upload_part")
        self.assertEqual(params["UploadId"], "upload-123")
        self.assertEqual(params["PartNumber"], 2)
        self.assertEqual(expiry, 21600)
        self.assertEqual(self.client.calls[2][0], "complete-multipart")

    def test_abort_multipart_upload_is_retry_safe(self):
        with patch.object(storage, "_client", return_value=self.client), \
             patch.object(storage.settings, "s3_bucket_quarantine", "quarantine"):
            storage.abort_multipart_upload(
                "quarantine", "abc.stl", "upload-123"
            )
        self.assertEqual(self.client.calls[0][0], "abort-multipart")

    def test_promotion_copies_then_deletes_quarantine_object(self):
        with patch.object(storage, "_client", return_value=self.client), \
             patch.object(storage.settings, "s3_bucket_quarantine", "quarantine"), \
             patch.object(storage.settings, "s3_bucket_models", "models"):
            storage.promote("quarantine", "models", "abc.obj")
        self.assertEqual(self.client.calls[0][0], "copy")
        self.assertEqual(self.client.calls[0][1]["Bucket"], "models")
        self.assertEqual(self.client.calls[1][0], "delete")


if __name__ == "__main__":
    unittest.main()
