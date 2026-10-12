"""period 请求/响应模型（V1.2 T24）。"""

from datetime import date

from pydantic import BaseModel


class PeriodWindowOut(BaseModel):
    kind: str
    label: str
    start: date
    end: date


class PeriodKindItem(BaseModel):
    kind: str
    description: str
