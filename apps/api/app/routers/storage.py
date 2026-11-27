import re
from typing import Annotated

from fastapi import APIRouter, File, Header, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.config import settings
from app.services import storage_service

router = APIRouter()
RangeHeader = Annotated[str | None, Header(alias="Range")]


def _stream_video(client, bucket: str, key: str, requested: str | None):
    size = client.stat_object(bucket, key).size
    start, end = 0, size - 1
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"}
    if requested:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
        if not match or not any(match.groups()):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        first, last = match.groups()
        if first:
            start = int(first)
            end = min(int(last), end) if last else end
        else:
            start = max(0, size - int(last))
        if start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    length = end - start + 1
    headers["Content-Length"] = str(length)

    def chunks():
        obj = client.get_object(bucket, key, offset=start, length=length)
        try:
            yield from obj.stream(256 * 1024)
        finally:
            obj.close()
            obj.release_conn()

    return StreamingResponse(chunks(), status_code=206 if requested else 200, media_type="video/mp4", headers=headers)


@router.get("/file/{key:path}")
def get_default_bucket_file(key: str, range_header: RangeHeader = None):
    return get_file(settings.MINIO_BUCKET, key, range_header)


@router.get("/{bucket}/{key:path}")
def get_file(bucket: str, key: str, range_header: RangeHeader = None):
    actual_bucket = settings.MINIO_BUCKET if bucket == "default" else bucket
    client = storage_service.get_minio_client()
    try:
        if key.startswith("flow/") and key.endswith(".mp4"):
            return _stream_video(client, actual_bucket, key, range_header)
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
