"""Pluggable file storage. ``local`` for dev / Railway volume, ``s3`` for anything S3-compatible.

The :meth:`Storage.put` and :meth:`Storage.open` methods both stream — neither
backend buffers an entire file in memory. The upload route passes the
underlying ``UploadFile.file`` (a :class:`SpooledTemporaryFile` that spills to
disk above ~1 MB) straight to ``put``; the download route wraps ``open`` in a
``StreamingResponse``.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from app.config import settings


class Storage(ABC):
    @abstractmethod
    def put(self, key: str, fileobj: BinaryIO, content_type: str) -> None: ...

    @abstractmethod
    def open(self, key: str) -> BinaryIO:
        """Open a readable stream for the object. Caller is responsible for
        closing. Enables chunked ``StreamingResponse`` without loading the
        whole object into memory."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Materialize the whole object. Prefer ``open`` for large files."""

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def presigned_url(self, key: str, expires_seconds: int = 900) -> str | None: ...

    def iter_chunks(self, key: str, chunk_size: int = 1 << 20) -> Iterator[bytes]:
        """Yield the object as byte chunks. Closes the underlying stream."""
        stream = self.open(key)
        try:
            while chunk := stream.read(chunk_size):
                yield chunk
        finally:
            stream.close()


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = key.replace("..", "").lstrip("/")
        p = self.root / safe
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def put(self, key: str, fileobj: BinaryIO, content_type: str) -> None:
        with open(self._path(key), "wb") as f:
            while chunk := fileobj.read(1 << 20):
                f.write(chunk)

    def open(self, key: str) -> BinaryIO:
        return open(self._path(key), "rb")

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            os.remove(p)

    def presigned_url(self, key: str, expires_seconds: int = 900) -> str | None:
        return None  # no direct URL; served through API


class S3Storage(Storage):
    def __init__(self):
        import boto3

        self._client = boto3.client(
            "s3",
            region_name=settings.S3_REGION,
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            aws_access_key_id=settings.S3_ACCESS_KEY or None,
            aws_secret_access_key=settings.S3_SECRET_KEY or None,
        )
        self.bucket = settings.S3_BUCKET

    def put(self, key: str, fileobj: BinaryIO, content_type: str) -> None:
        self._client.upload_fileobj(
            fileobj,
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

    def open(self, key: str) -> BinaryIO:
        obj = self._client.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"]  # StreamingBody implements .read() and .close()

    def get(self, key: str) -> bytes:
        obj = self._client.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read()

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def presigned_url(self, key: str, expires_seconds: int = 900) -> str | None:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )


def get_storage() -> Storage:
    if settings.STORAGE_BACKEND == "s3":
        return S3Storage()
    return LocalStorage(settings.STORAGE_LOCAL_PATH)
