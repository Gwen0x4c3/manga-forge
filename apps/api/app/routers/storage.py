from fastapi import APIRouter, File, UploadFile
from fastapi.responses import RedirectResponse, Response

from app.services import storage_service

router = APIRouter()


@router.get("/{bucket}/{key:path}")
async def get_file(bucket: str, key: str):
    client = storage_service.get_minio_client()
    try:
        response = client.get_object(bucket, key)
        data = response.read()
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        response.close()
        response.release_conn()
        return Response(content=data, media_type=content_type)
    except Exception:
        return Response(status_code=404, content=b"Not found")


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), bucket: str = "mangaforge", prefix: str = "uploads"):
    content = await file.read()
    object_key = storage_service.generate_object_key(prefix, file.filename or "unknown")
    storage_service.upload_file(
        bucket, object_key, content, content_type=file.content_type or "application/octet-stream"
    )
    return {"object_key": object_key, "bucket": bucket}
