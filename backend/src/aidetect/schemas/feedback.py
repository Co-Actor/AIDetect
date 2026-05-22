from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

FeedbackLabel = Literal["correct", "incorrect", "partially_correct", "unsure"]


class FeedbackRequest(BaseModel):
    detection_id: UUID
    label: FeedbackLabel
    note: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    id: UUID
    detection_id: UUID
    label: FeedbackLabel
    created_at: datetime
