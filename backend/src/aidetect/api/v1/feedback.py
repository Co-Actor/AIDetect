import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, status

from aidetect.api.deps import SettingsDep
from aidetect.schemas.feedback import FeedbackRequest, FeedbackResponse
from aidetect.services.auth import CurrentUserDep
from aidetect.services.cache import get_cache
from aidetect.services.feedback_log import append_feedback
from aidetect.services.observability import get_observer

logger = logging.getLogger(__name__)

router = APIRouter()


# Maps the categorical feedback label to a numeric Langfuse score so the
# trace UI can show a single column and we can aggregate accuracy over time.
# correct → 1, partially → 0.5, incorrect → 0, unsure → no score recorded.
_LABEL_TO_SCORE: dict[str, float | None] = {
    "correct": 1.0,
    "partially_correct": 0.5,
    "incorrect": 0.0,
    "unsure": None,
}


@router.post("", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    payload: FeedbackRequest,
    settings: SettingsDep,
    _user: CurrentUserDep,
) -> FeedbackResponse:
    feedback_id = uuid.uuid4()
    created_at = datetime.now(UTC)
    await append_feedback(
        settings.feedback_log_path,
        {
            "id": str(feedback_id),
            "detection_id": str(payload.detection_id),
            "label": payload.label,
            "note": payload.note,
        },
    )

    # Mirror the label onto the original Langfuse trace as a score, so the
    # observability UI shows ground-truth alongside our predicted probability.
    # Best-effort: if tracing was disabled when the detection ran, the lookup
    # is a no-op and we silently skip.
    score_value = _LABEL_TO_SCORE.get(payload.label)
    if score_value is not None:
        try:
            cache = await get_cache(settings)
            trace_id = await cache.get(f"t:{payload.detection_id}")
            if trace_id:
                observer = get_observer()
                observer.score_detection(
                    trace_id=trace_id,
                    name="user_feedback",
                    value=score_value,
                    comment=payload.note,
                )
        except Exception as exc:
            logger.warning("[feedback] failed to record Langfuse score: %s", exc)

    return FeedbackResponse(
        id=feedback_id,
        detection_id=payload.detection_id,
        label=payload.label,
        created_at=created_at,
    )
