from fastapi import APIRouter, File, UploadFile

from app.services import storage_service

router = APIRouter()


@router.get("/{bucket}/{key:path}")
async def get_file(bucket: str, key: str):
    url = storage_service.get_presigned_url(bucket, key)
    return {"url": url}


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), bucket: str = "mangaforge", prefix: str = "uploads"):
    content = await file.read()
    object_key = storage_service.generate_object_key(prefix, file.filename or "unknown")
    storage_service.upload_file(
        bucket, object_key, content, content_type=file.content_type or "application/octet-stream"
    )
    return {"object_key": object_key, "bucket": bucket}
