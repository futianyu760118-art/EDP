"""ingest 文件导入请求/响应模型（V1.2 T30：Excel/CSV 通道）。"""

from pydantic import BaseModel, Field


class ImportErrorItem(BaseModel):
    row: int
    code: str = "VALIDATION_ERROR"
    message: str


class ImportStats(BaseModel):
    """导入结果：received=解析行数、registered/duplicated/failed 沿管道口径。"""

    received: int = 0
    registered: int = 0
    duplicated: int = 0
    failed: int = 0
    errors: list[ImportErrorItem] = Field(default_factory=list)
