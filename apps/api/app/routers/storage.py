from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response

from app.config import settings
from app.services import storage_service

router = APIRouter()


@router.get("/file/{key:path}")
async def get_default_bucket_file(key: str):
    return await get_file(settings.MINIO_BUCKET, key)


@router.get("/{bucket}/{key:path}")
async def get_file(bucket: str, key: str):
    actual_bucket = settings.MINIO_BUCKET if bucket == "default" else bucket
    client = storage_service.get_minio_client()
    try:
        response = client.get_object(actual_bucket, key)
        try:
            data = response.read()
            content_type = response.headers.get("Content-Type", "application/octet-stream")
        finally:
            response.close()
            response.release_conn()
        return Response(
            content=data,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except Exception:
        return Response(status_code=404, content=b"Not found")


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    bucket: str | None = None,
    prefix: str = "uploads",
):
    target_bucket = bucket or settings.MINIO_BUCKET
    content = await file.read()
    object_key = storage_service.generate_object_key(prefix, file.filename or "unknown")
    storage_service.upload_file(
        target_bucket, object_key, content, content_type=file.content_type or "application/octet-stream"
    )
    return {"object_key": object_key, "bucket": target_bucket}
