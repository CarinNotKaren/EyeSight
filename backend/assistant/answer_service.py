
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
from whisper.tokenizer import LANGUAGES

# Gemini model confirmed to work with the configured API key.
DEFAULT_VLM_MODEL = "gemini-3.5-flash-lite"

PROMPT_VERSION = "eyesight-vlm-grounding-v1"
MAX_EVIDENCE_IMAGES = 3
MAX_OUTPUT_TOKENS = 180


# Keep the prompt focused on immediate surroundings and prevent invented details.
SYSTEM_PROMPT = """You are EyeSight, an accessibility assistant, not Apple's EyeSight feature.
Your purpose is to help blind and visually impaired users understand their immediate surroundings.
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
    """Map Whisper language codes to their full language names."""
    language = (language_code or "en").lower().split("-")[0]
    return LANGUAGES.get(language, "english").title()


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

    # Reject paths that point outside the permitted frames directory.
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

    # Recheck both frame and session retention before reading image bytes.
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

        # Use the database's canonical storage key, not a path from retrieval JSON.
        image_path = _safe_frame_path(frame.image_storage_key)

        if not image_path.is_file():
            continue

        # Only send image formats supported by the service.
        mime_type = (frame.mime_type or "").lower()

        if mime_type not in ("image/jpeg", "image/png", "image/webp"):
            continue

        # Convert the stored image into a data URL for the existing image pipeline.
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

    # Remove optional Markdown JSON code fences.
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        cleaned,
        flags=re.I,
    )

    # Extract the JSON object if the model includes surrounding text.
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

            # Never accept an unsupported answer classification.
            if answer_type not in ("grounded", "uncertain"):
                answer_type = "uncertain"

            return {
                "answer_text": answer[:4000],
                "answer_type": answer_type,
                "uncertainty_reason": (
                    str(reason)[:255] if reason else None
                ),
            }

        except (
            json.JSONDecodeError,
            AttributeError,
            ValueError,
            TypeError,
        ):
            pass

    # Never label unstructured model output as fully grounded.
    return {
        "answer_text": cleaned[:4000],
        "answer_type": "uncertain",
        "uncertainty_reason": (
            "The model did not return a verifiable confidence classification."
        ),
    }


def call_vision_model(question_text, language_code, images):
    """Send the question and retrieved images to Google's Gemini API."""

    try:
        from google import genai
        from google.genai import types

        # Read the Gemini credentials from the backend environment.
        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise VLMGenerationError("GEMINI_API_KEY is not configured.")

        # Read the selected model from .env, using the confirmed default.
        model_id = os.getenv("VLM_MODEL", DEFAULT_VLM_MODEL)

        # Initialize the cloud Gemini client.
        client = genai.Client(api_key=api_key)

        # Include the question and requested response language.
        prompt = (
            f"Answer this question: {question_text}\n"
            f"Answer language: {_language_name(language_code)}.\n"
            "The images are ordered from most relevant to least relevant. "
            "Use only visible evidence. "
            "If the evidence is insufficient, clearly state the uncertainty."
        )

        # Start the request with the question text.
        contents = [
            types.Part.from_text(text=prompt)
        ]

        # Convert each existing base64 data URL into Gemini image bytes.
        for image in images:
            data_url = image["data_url"]

            if "," not in data_url:
                raise ValueError("Invalid image data URL.")

            # Extract and decode the base64 image content.
            encoded_image = data_url.split(",", 1)[1]
            image_bytes = base64.b64decode(encoded_image)

            # Attach the image with its correct MIME type.
            contents.append(
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=image["mime_type"],
                )
            )

        # Generate the answer using Gemini's cloud API.
        response = client.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                temperature=0.2,
            ),
        )

        raw_text = response.text

        if not raw_text or not raw_text.strip():
            raise VLMGenerationError("Gemini returned an empty response.")

        # Reuse EyeSight's existing response parser.
        parsed = parse_vlm_response(raw_text)

        # Preserve the existing return format for the rest of EyeSight.
        return parsed, model_id

    except VLMGenerationError:
        raise

    except Exception as error:
        # Avoid exposing API keys, local paths, or provider response details.
        raise VLMGenerationError(
            f"Vision-language inference failed ({type(error).__name__})."
        ) from error


def _get_or_create_model(db, model_id):
    """Register the exact Gemini configuration used for this answer."""

    # Store the actual Gemini API configuration for this model.
    configuration = {
        "api": "google_genai_generate_content",
        "prompt_version": PROMPT_VERSION,
        "max_evidence_images": MAX_EVIDENCE_IMAGES,
    }

    # Reuse an existing database record when its configuration matches.
    candidates = db.scalars(
        select(AIModel).where(
            AIModel.task == "vision_language",
            AIModel.provider == "Google Gemini",
            AIModel.model_name == model_id,
            AIModel.model_revision == "api",
        )
    ).all()

    for candidate in candidates:
        if candidate.configuration == configuration:
            return candidate

    # Register Gemini as the provider in the existing ai_models table.
    model = AIModel(
        task="vision_language",
        provider="Google Gemini",
        model_name=model_id,
        model_revision="api",
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

    # Reuse Member 2's retrieved frames; do not perform another search.
    images = load_question_images(db, question, retrieval)

    model_id = None
    generation_latency_ms = 0
    answer_type = "no_evidence"
    uncertainty_reason = "No unexpired retrieved frame images were available."

    # Use a safe fallback if no valid evidence images are available.
    answer_text = _fallback_text(
        question.language_code,
        no_evidence=True,
    )

    # This becomes True only after Gemini successfully returns a response.
    provided_to_model = False

    if images:
        generation_started = perf_counter()

        try:
            generated, model_name = call_vision_model(
                question.question_text,
                question.language_code,
                images,
            )

            generation_latency_ms = round(
                (perf_counter() - generation_started) * 1000
            )

            # Register the model that actually generated this answer.
            model = _get_or_create_model(db, model_name)
            model_id = model.model_id

            answer_text = generated["answer_text"]
            answer_type = generated["answer_type"]
            uncertainty_reason = generated["uncertainty_reason"]

            # The inference call returned successfully with the supplied images.
            provided_to_model = True

        except VLMGenerationError:
            generation_latency_ms = round(
                (perf_counter() - generation_started) * 1000
            )

            answer_type = "error_fallback"
            uncertainty_reason = "The vision-language model was unavailable."
            answer_text = _fallback_text(question.language_code)

    retrieval_latency_ms = retrieval.get("retrieval_latency_ms")

    # Measure end-to-end server time from question receipt when available.
    received_at = getattr(question, "received_at", None)

    if isinstance(received_at, datetime):
        total_latency_ms = max(
            0,
            round((utc_now() - received_at).total_seconds() * 1000),
        )
    else:
        # Retain local answer-stage duration for isolated tests.
        total_latency_ms = round((perf_counter() - started) * 1000)

    # Create the answer using the existing database model.
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

        # Persist the retrieved frames and their relationship to this answer.
        for image in images:
            similarity = image.get("similarity")

            db.add(
                AnswerEvidence(
                    answer_id=answer.answer_id,
                    frame_id=image["frame_id"],
                    retrieval_rank=image["retrieval_rank"],

                    # Use only values allowed by the existing database ENUM.
                    retrieval_method=(
                        "time"
                        if retrieval.get("selection_mode") == "current_frame"
                        else "semantic" if similarity is not None else "time"
                    ),

                    semantic_score=similarity,
                    combined_score=similarity,
                    provided_to_model=provided_to_model,
                )
            )

        # A fallback/no-evidence response is still a completed user response.
        question.status = "completed"
        question.error_code = None

        db.commit()
        db.refresh(answer)
        db.refresh(question)

        return answer

    except Exception:
        # Roll back answer and evidence changes if persistence fails.
        db.rollback()
        raise
