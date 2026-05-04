import json
import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ResponseWrapperMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        if response.status_code == 204:
            return response

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        body = b""
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                body += chunk.encode("utf-8")
            else:
                body += chunk

        try:
            original = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        if isinstance(original, dict) and "code" in original and "data" in original:
            return JSONResponse(content=original, status_code=response.status_code)

        if 200 <= response.status_code < 300:
            wrapped = {
                "code": response.status_code,
                "message": "ok",
                "data": original,
            }
        else:
            message = ""
            if isinstance(original, dict):
                raw = original.get("detail", original.get("message", str(original)))
                if isinstance(raw, list):
                    parts = []
                    for item in raw:
                        if isinstance(item, dict):
                            loc = ".".join(str(x) for x in item.get("loc", []))
                            parts.append(f"{loc}: {item.get('msg', str(item))}")
                        else:
                            parts.append(str(item))
                    message = "; ".join(parts)
                else:
                    message = str(raw)
            else:
                message = str(original)
            wrapped = {
                "code": response.status_code,
                "message": message,
                "data": None,
            }

        return JSONResponse(content=wrapped, status_code=response.status_code)
