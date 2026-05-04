import io
import uuid
from datetime import timedelta

from minio import Minio

from app.config import settings


def get_minio_client() -> Minio:
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def upload_file(bucket: str, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    client = get_minio_client()
    ensure_bucket(client, bucket)
    client.put_object(bucket, object_key, io.BytesIO(data), len(data), content_type=content_type)
    return object_key


def generate_object_key(prefix: str, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    return f"{prefix}/{uuid.uuid4().hex}.{ext}" if ext else f"{prefix}/{uuid.uuid4().hex}"


def get_presigned_url(bucket: str, object_key: str, expires: int = 3600) -> str:
    client = get_minio_client()
    return client.presigned_get_object(bucket, object_key, expires=timedelta(seconds=expires))
