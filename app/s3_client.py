"""Async S3-compatible client for Cloudflare R2 storage."""

from typing import Optional

import aioboto3

from app.config import get_settings


class S3Client:
    """Async S3 client for Cloudflare R2."""

    def __init__(self):
        settings = get_settings()
        self.account_id = settings.r2_account_id
        self.access_key_id = settings.r2_access_key_id
        self.secret_access_key = settings.r2_secret_access_key
        self.bucket_name = settings.r2_bucket_name
        self.public_url = (settings.r2_public_url or "").rstrip("/")
        self.endpoint_url = (
            f"https://{self.account_id}.r2.cloudflarestorage.com"
            if self.account_id
            else None
        )
        self._session = aioboto3.Session()

    def _get_client_kwargs(self) -> dict:
        return {
            "service_name": "s3",
            "endpoint_url": self.endpoint_url,
            "aws_access_key_id": self.access_key_id,
            "aws_secret_access_key": self.secret_access_key,
            "region_name": "auto",
        }

    async def upload_bytes(self, key: str, data: bytes, content_type: str = "audio/mpeg") -> str:
        """Upload bytes to R2 and return the public URL."""
        async with self._session.client(**self._get_client_kwargs()) as client:
            await client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        return self.get_public_url(key)

    def get_public_url(self, key: str) -> str:
        """Get the public URL for an object."""
        return f"{self.public_url}/{key}"


_s3_client: Optional[S3Client] = None


def get_s3_client() -> S3Client:
    global _s3_client
    if _s3_client is None:
        _s3_client = S3Client()
    return _s3_client
