from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["fast", "balanced", "thorough"]
Verdict = Literal["human", "likely_human", "uncertain", "likely_ai", "ai"]
Severity = Literal["low", "medium", "high"]
ChunkStrategy = Literal["none", "sentence", "paragraph", "auto"]


class DetectionOptions(BaseModel):
    include_evidence: bool = True
    include_signals: bool = True
    include_rubric_scores: bool = False
    chunk_strategy: ChunkStrategy = "auto"


class DetectionContext(BaseModel):
    platform: str | None = None
    expected_register: str | None = None


class DetectionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    text: str = Field(..., min_length=1)
    language: str = "auto"
    mode: Mode = "balanced"
    options: DetectionOptions = Field(default_factory=DetectionOptions)
    context: DetectionContext | None = None
    rubric_version: str = "latest"
    model_version: str = "latest"


class PatternMatch(BaseModel):
    category: str
    name: str
    span: tuple[int, int]
    severity: Severity = "medium"
    suggestion: str | None = None


class StatisticalSignal(BaseModel):
    score: float
    contributors: dict[str, object] = Field(default_factory=dict)


class PatternsSignal(BaseModel):
    score: float
    matches: list[PatternMatch] = Field(default_factory=list)


class SentenceScore(BaseModel):
    index: int
    text: str
    score: float
    reason: str | None = None


class LLMJudgeSignal(BaseModel):
    score: float
    model: str
    summary: str | None = None
    rubric_scores: dict[str, "RubricDimensionScore"] | None = None
    error: str | None = None
    sentence_scores: list[SentenceScore] | None = None
    sentence_aggregate: dict[str, float | int] | None = None
    usage: dict[str, int] | None = None


class Signals(BaseModel):
    statistical: StatisticalSignal | None = None
    patterns: PatternsSignal | None = None
    llm_judge: LLMJudgeSignal | None = None


class RubricDimensionScore(BaseModel):
    score: float
    evidence: str | None = None


class EvidenceSpan(BaseModel):
    start: int
    end: int
    type: str
    severity: Severity = "medium"
    reason: str


class Evidence(BaseModel):
    spans: list[EvidenceSpan] = Field(default_factory=list)
    annotated_html: str | None = None
    annotated_markdown: str | None = None


class DetectionResultBlock(BaseModel):
    ai_probability: float
    human_probability: float
    verdict: Verdict
    confidence: float
    severity: Severity


class RequestDetails(BaseModel):
    text_hash: str
    length_chars: int
    length_tokens: int | None = None
    language_detected: str | None = None


class ResponseMetadata(BaseModel):
    model_version: str
    rubric_version: str
    mode: Mode
    duration_ms: int
    cached: bool = False
    cost_credits: int = 1


class DetectionResponse(BaseModel):
    id: UUID
    object: Literal["detection"] = "detection"
    created_at: datetime
    result: DetectionResultBlock
    signals: Signals | None = None
    rubric_scores: dict[str, RubricDimensionScore] | None = None
    evidence: Evidence | None = None
    request: RequestDetails
    metadata: ResponseMetadata
