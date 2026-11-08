"""Generate accessible, evidence-grounded answers from retrieved frame images.

The service reuses Member 2's retrieval results and the existing Answer and
AnswerEvidence tables. It does not create a second image-search pipeline.
"""

import base64
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from sqlalchemy import select

from database.models.ai_model import AIModel
from database.models.answer import Answer
from database.models.answer_evidence import AnswerEvidence
from database.models.frame import Frame
from database.models.session import Session as CaptureSession


PROMPT_VERSION = "eyesight-vlm-grounding-v1"
DEFAULT_VLM_MODEL = "Qwen/Qwen2.5-VL-3B-Instruct"
MAX_EVIDENCE_IMAGES = 3
MAX_OUTPUT_TOKENS = 180

# Keep the prompt focused on the user's immediate surroundings and prevent
# the model from inventing details that are not visible in the supplied frames.
SYSTEM_PROMPT = """You are EyeSight, a visual assistant for a blind or visually impaired person.
Answer the user's question using ONLY the supplied camera frames.
Be concise, concrete, and useful for immediate orientation.
Never invent objects, text, distances, directions, identities, or events.
If the frames do not clearly support an answer, say so and explain what is uncertain.
Do not claim that an object is absent unless the relevant view is clear.
Return ONLY valid JSON with this exact shape:
{"answer":"one or two short sentences","answer_type":"grounded or uncertain","uncertainty_reason":null}
Use answer_type="grounded" only when the answer is clearly supported by the images.
Use answer_type="uncertain" when the evidence is incomplete, ambiguous, blurry, or conflicting.
Write the answer in the requested language.
"""


class VLMGenerationError(RuntimeError):
    """Raised when the configured vision-language model cannot answer."""


def utc_now():
    """Use naive UTC datetimes to match the existing MySQL models."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _language_name(language_code):
    """Map the project's supported language codes to prompt instructions."""
    language = (language_code or "en").lower().split("-")[0]
    return {
        "en": "English",
        "fr": "French",
        "ar": "Arabic",
    }.get(language, "English")


def _fallback_text(language_code, no_evidence=False):
    """Return a short safe response when images or model inference are absent."""
    language = (language_code or "en").lower().split("-")[0]

    if no_evidence:
        return {
            "fr": "Je ne peux pas déterminer cela à partir des images disponibles.",
            "ar": "لا أستطيع تحديد ذلك من الصور المتاحة.",
        }.get(language, "I can't determine that from the available images.")

    return {
        "fr": "Désolé, je ne peux pas analyser les images pour le moment. Réessayez.",
        "ar": "عذرًا، لا أستطيع تحليل الصور حاليًا. يرجى المحاولة مرة أخرى.",
    }.get(language, "Sorry, I can't analyze the images right now. Please try again.")


def _safe_frame_path(storage_key):
    """Resolve a storage key while preventing path traversal outside frames/."""
    storage_root = (Path(__file__).resolve().parents[1] / "storage").resolve()
    frames_root = (storage_root / "frames").resolve()
    image_path = (storage_root / storage_key).resolve()

    if not image_path.is_relative_to(frames_root):
        raise ValueError("Frame storage key is outside the frames directory.")

    return image_path


def load_question_images(db, question, retrieval):
    """Load only retrieved, unexpired frame images belonging to this session."""
    frame_refs = (retrieval or {}).get("frames", [])[:MAX_EVIDENCE_IMAGES]
    if not frame_refs:
        return []

    frame_ids = [
        item.get("frame_id")
        for item in frame_refs
        if item.get("frame_id") is not None
    ]
    if not frame_ids:
        return []

    # Recheck both frame and session retention immediately before reading bytes.
    now = utc_now()
    session = db.get(CaptureSession, question.session_id)
    if session is None or session.history_expires_at <= now:
        return []

    frames = db.scalars(
        select(Frame).where(
            Frame.frame_id.in_(frame_ids),
            Frame.session_id == question.session_id,
            Frame.expires_at > now,
            Frame.processing_status.in_(("ready", "partial")),
        )
    ).all()
    frames_by_id = {frame.frame_id: frame for frame in frames}

    images = []
    for rank, reference in enumerate(frame_refs, start=1):
        frame = frames_by_id.get(reference.get("frame_id"))
        if frame is None:
            continue

        # Use the database's canonical storage key, not an arbitrary path
        # supplied by the retrieval JSON.
        image_path = _safe_frame_path(frame.image_storage_key)
        if not image_path.is_file():
            continue

        mime_type = (frame.mime_type or "").lower()
        if mime_type not in ("image/jpeg", "image/png", "image/webp"):
            continue

        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        images.append({
            "frame_id": frame.frame_id,
            "retrieval_rank": rank,
            "image_storage_key": frame.image_storage_key,
            "mime_type": mime_type,
            "data_url": f"data:{mime_type};base64,{encoded}",
            "similarity": reference.get("similarity"),
        })

    return images


def parse_vlm_response(raw_text):
    """Parse the model's JSON response, with a safe uncertain fallback."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise VLMGenerationError("The vision model returned an empty response.")

    cleaned = raw_text.strip()
    cleaned = re.sub(r"^\x60{3}(?:json)?\s*|\s*\x60{3}$", "", cleaned, flags=re.I)

    # Some hosted models wrap JSON in a short explanation; extract the object.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(cleaned[start:end + 1])
            answer = str(payload.get("answer", "")).strip()
            answer_type = payload.get("answer_type", "uncertain")
            reason = payload.get("uncertainty_reason")
            if not answer:
                raise ValueError("Missing answer text.")
            if answer_type not in ("grounded", "uncertain"):
                answer_type = "uncertain"
            return {
                "answer_text": answer[:4000],
                "answer_type": answer_type,
                "uncertainty_reason": (
                    str(reason)[:255] if reason else None
                ),
            }
        except (json.JSONDecodeError, AttributeError, ValueError, TypeError):
            pass

    # Never label unstructured output as fully grounded.
    return {
        "answer_text": cleaned[:4000],
        "answer_type": "uncertain",
        "uncertainty_reason": "The model did not return a verifiable confidence classification.",
    }


def call_vision_model(question_text, language_code, images):
    """Send the question and retrieved images to Hugging Face Inference."""
    token = os.getenv("HF_TOKEN")
    if not token:
        raise VLMGenerationError("HF_TOKEN is not configured.")

    model_id = os.getenv("VLM_MODEL", DEFAULT_VLM_MODEL)
    endpoint_url = os.getenv("HF_INFERENCE_ENDPOINT_URL")

    try:
        from huggingface_hub import InferenceClient

        # Use a dedicated Inference Endpoint when configured; otherwise use
        # Hugging Face Inference Providers' automatic provider selection.
        if endpoint_url:
            client = InferenceClient(base_url=endpoint_url, token=token)
        else:
            client = InferenceClient(token=token)

        user_content = [{
            "type": "text",
            "text": (
                f"Answer this question: {question_text}\n"
                f"Answer language: {_language_name(language_code)}.\n"
                "The images are ordered from most relevant to least relevant. "
                "Use only visible evidence."
            ),
        }]

        # Attach the actual image bytes as data URLs; local file paths are
        # never exposed to the remote inference provider.
        for image in images:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": image["data_url"]},
            })

        response = client.chat_completion(
            model=model_id,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.2,
        )
        raw_text = response.choices[0].message.content
        if isinstance(raw_text, list):
            raw_text = " ".join(
                part.get("text", "")
                for part in raw_text
                if isinstance(part, dict)
            )

        parsed = parse_vlm_response(raw_text)
        return parsed, model_id

    except VLMGenerationError:
        raise
    except Exception as error:
        # Do not leak tokens, local paths, or provider response bodies to users.
        raise VLMGenerationError(
            f"Vision-language inference failed ({type(error).__name__})."
        ) from error


def _get_or_create_model(db, model_id):
    """Register the exact VLM configuration used for this answer."""
    configuration = {
        "api": "huggingface_inference_chat_completion",
        "prompt_version": PROMPT_VERSION,
        "max_evidence_images": MAX_EVIDENCE_IMAGES,
    }

    candidates = db.scalars(
        select(AIModel).where(
            AIModel.task == "vision_language",
            AIModel.provider == "Hugging Face",
            AIModel.model_name == model_id,
            AIModel.model_revision == "main",
        )
    ).all()

    for candidate in candidates:
        if candidate.configuration == configuration:
            return candidate

    model = AIModel(
        task="vision_language",
        provider="Hugging Face",
        model_name=model_id,
        model_revision="main",
        configuration=configuration,
    )
    db.add(model)
    db.flush()
    return model


def generate_and_persist_answer(db, question):
    """Generate and save one answer plus its exact frame-evidence links."""
    existing = db.query(Answer).filter(
        Answer.question_id == question.question_id
    ).first()
    if existing is not None:
        # Make retries idempotent if a client repeats the processing request.
        if question.status != "completed":
            question.status = "completed"
            db.commit()
            db.refresh(question)
        return existing

    started = perf_counter()
    retrieval = question.retrieval_configuration or {}
    images = load_question_images(db, question, retrieval)

    model_id = None
    generation_latency_ms = 0
    answer_type = "no_evidence"
    uncertainty_reason = "No unexpired retrieved frame images were available."
    answer_text = _fallback_text(question.language_code, no_evidence=True)
    provided_to_model = False

    if images:
        generation_started = perf_counter()
        # Record that images were included in an inference request only when
        # credentials exist; missing credentials produce a local fallback.
        provided_to_model = bool(os.getenv("HF_TOKEN"))
        try:
            generated, model_name = call_vision_model(
                question.question_text,
                question.language_code,
                images,
            )
            generation_latency_ms = round(
                (perf_counter() - generation_started) * 1000
            )
            model = _get_or_create_model(db, model_name)
            model_id = model.model_id
            answer_text = generated["answer_text"]
            answer_type = generated["answer_type"]
            uncertainty_reason = generated["uncertainty_reason"]
        except VLMGenerationError:
            generation_latency_ms = round(
                (perf_counter() - generation_started) * 1000
            )
            answer_type = "error_fallback"
            uncertainty_reason = "The vision-language model was unavailable."
            answer_text = _fallback_text(question.language_code)

    retrieval_latency_ms = (retrieval or {}).get("retrieval_latency_ms")
    # Measure end-to-end server time from question receipt when available;
    # otherwise retain the local answer-stage duration for isolated tests.
    received_at = getattr(question, "received_at", None)
    if isinstance(received_at, datetime):
        total_latency_ms = max(
            0, round((utc_now() - received_at).total_seconds() * 1000)
        )
    else:
        total_latency_ms = round((perf_counter() - started) * 1000)

    answer = Answer(
        question_id=question.question_id,
        model_id=model_id,
        answer_text=answer_text,
        language_code=question.language_code or "en",
        answer_type=answer_type,
        uncertainty_reason=uncertainty_reason,
        prompt_version=PROMPT_VERSION,
        stt_latency_ms=None,
        retrieval_latency_ms=retrieval_latency_ms,
        generation_latency_ms=generation_latency_ms,
        server_total_latency_ms=total_latency_ms,
        created_at=utc_now(),
    )

    try:
        db.add(answer)
        db.flush()

        # Persist every retrieved frame and whether it was actually supplied
        # to the VLM. Retrieval rank is retained for traceability.
        for image in images:
            similarity = image.get("similarity")
            db.add(AnswerEvidence(
                answer_id=answer.answer_id,
                frame_id=image["frame_id"],
                retrieval_rank=image["retrieval_rank"],
                retrieval_method="semantic" if similarity is not None else "time",
                semantic_score=similarity,
                combined_score=similarity,
                provided_to_model=provided_to_model,
            ))

        # A fallback/no-evidence response is still a completed user response.
        question.status = "completed"
        question.error_code = None
        db.commit()
        db.refresh(answer)
        db.refresh(question)
        return answer

    except Exception:
        db.rollback()
        raise
