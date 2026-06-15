"""Async S3-compatible client for Cloudflare R2 storage."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import aioboto3

from app.config import get_settings

logger = logging.getLogger(__name__)


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

    async def cleanup_old_files(self, prefix: str = "tts/", max_age_days: int = 7) -> dict:
        """
        Delete files older than max_age_days from bucket.
        
        Args:
            prefix: S3 key prefix to scan (default: "tts/")
            max_age_days: Delete files older than this many days
            
        Returns:
            Dict with deleted count and any errors
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        deleted = 0
        errors = []
        
        try:
            async with self._session.client(**self._get_client_kwargs()) as client:
                # List all objects with prefix
                paginator = client.get_paginator("list_objects_v2")
                
                keys_to_delete = []
                
                async for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                    contents = page.get("Contents", [])
                    
                    for obj in contents:
                        last_modified = obj.get("LastModified")
                        if last_modified and last_modified < cutoff:
                            keys_to_delete.append({"Key": obj["Key"]})
                            
                            # Delete in batches of 1000 (S3 limit)
                            if len(keys_to_delete) >= 1000:
                                result = await self._delete_batch(client, keys_to_delete)
                                deleted += result["deleted"]
                                errors.extend(result["errors"])
                                keys_to_delete = []
                
                # Delete remaining
                if keys_to_delete:
                    result = await self._delete_batch(client, keys_to_delete)
                    deleted += result["deleted"]
                    errors.extend(result["errors"])
                
                logger.info(f"Cleanup: deleted {deleted} files older than {max_age_days} days")
                
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            errors.append(str(e))
        
        return {"deleted": deleted, "errors": errors}
    
    async def _delete_batch(self, client, keys: list) -> dict:
        """Delete a batch of objects from S3."""
        deleted = 0
        errors = []
        
        try:
            response = await client.delete_objects(
                Bucket=self.bucket_name,
                Delete={"Objects": keys, "Quiet": True}
            )
            deleted = len(keys) - len(response.get("Errors", []))
            
            for err in response.get("Errors", []):
                errors.append(f"{err['Key']}: {err.get('Message', 'unknown')}")
                
        except Exception as e:
            errors.append(f"Batch delete failed: {e}")
        
        return {"deleted": deleted, "errors": errors}


_s3_client: Optional[S3Client] = None


def get_s3_client() -> S3Client:
    global _s3_client
    if _s3_client is None:
        _s3_client = S3Client()
    return _s3_client
