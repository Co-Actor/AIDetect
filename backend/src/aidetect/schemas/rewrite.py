from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aidetect.schemas.detection import DetectionResultBlock, Severity

VoicePreset = Literal[
    "casual_tech_blog",
    "personal_essay",
    "business_minus_buzzwords",
    "linkedin_human",
]
RewriteMode = Literal["fast", "balanced", "thorough"]


class RewriteOptions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    voice: VoicePreset | None = None
    preserve: list[str] = Field(
        default_factory=lambda: ["facts", "numbers", "code_blocks", "urls"]
    )
    max_iterations: int = Field(default=2, ge=1, le=4)
    target_ai_probability: float = Field(default=0.30, ge=0.0, le=1.0)


class RewriteRequest(BaseModel):
    text: str = Field(..., min_length=1)
    language: str = "auto"
    mode: RewriteMode = "balanced"
    options: RewriteOptions = Field(default_factory=RewriteOptions)
    custom_voice_instructions: str | None = Field(default=None, max_length=2000)


class IterationDiagnostic(BaseModel):
    index: int
    ai_probability: float
    verdict: str
    summary: str | None = None


class RewriteUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class RewriteResponse(BaseModel):
    id: UUID
    object: Literal["rewrite"] = "rewrite"
    created_at: datetime
    rewritten_text: str
    changes: list[str] = Field(default_factory=list)
    preserved_note: str | None = None
    before: DetectionResultBlock
    after: DetectionResultBlock
    iterations: list[IterationDiagnostic]
    target_reached: bool
    voice: VoicePreset | None = None
    model: str
    duration_ms: int
    usage: RewriteUsage
    severity: Severity
