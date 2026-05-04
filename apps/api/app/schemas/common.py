from pydantic import BaseModel


class PaginationParams(BaseModel):
    page: int = 1
    page_size: int = 20


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: object = None
