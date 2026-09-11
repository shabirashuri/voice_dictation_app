from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import os
import json
import base64
import asyncio
import logging
import re
import unicodedata

from assemblyai.streaming.v3 import (
    AsyncRealTimeTranscriber,
    RealTimeParameters,
    Encoding,
    SpeechModel,
    RealTimeEvents,
    NoiseSuppressionModel,
)

from app.graph.routers import process_chunk, finalize
from app.graph import workflow as _workflow_mod
from app.services.llm.provider import LLMRateLimitError

router = APIRouter()


def _english_only_text(text: str) -> str:
    """Remove letters from non-Latin scripts while preserving English text."""
    filtered = []
    for character in text:
        character_type = unicodedata.category(character)
        is_non_ascii_word_character = character_type[0] in {"L", "M"} and ord(character) > 127
        if is_non_ascii_word_character:
            continue
        filtered.append(character)
    normalized = " ".join("".join(filtered).split())
    return re.sub(r"\s+([,.!?;:])", r"\1", normalized)


def _accepted_final_turn(event) -> bool:
    """Reject explicitly non-English and low-confidence recognition results."""
    transcript = getattr(event, "transcript", "") or ""
    if not _english_only_text(transcript):
        return False

    language_code = getattr(event, "language_code", None)
    if language_code and language_code.lower().split("-")[0] != "en":
        return False

    words = getattr(event, "words", None) or []
    confidences = [getattr(word, "confidence", 0.0) for word in words]
    return not confidences or (sum(confidences) / len(confidences)) >= 0.55


@router.websocket("/ws/voice")
async def websocket_voice(ws: WebSocket):
    await ws.accept()
    logger = logging.getLogger("voice_ws")

    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        await ws.send_text(json.dumps({"error": "missing AssemblyAI API key"}))
        await ws.close()
        return

    # Configure real-time parameters: PCM 16-bit, 16k sample rate, use universal model
    # Allow configurable turn silence via TURN_SILENCE_MS env var (milliseconds).
    try:
        turn_silence_ms = int(os.environ.get("TURN_SILENCE_MS", "7000"))
    except Exception:
        turn_silence_ms = 7000
    try:
        vad_threshold = float(os.environ.get("VAD_THRESHOLD", "0.7"))
    except Exception:
        vad_threshold = 0.7
    logger.info("Using TURN_SILENCE_MS=%d ms to finalize turns", turn_silence_ms)
    logger.info("Using VAD_THRESHOLD=%.2f for voice activity detection", vad_threshold)

    params = RealTimeParameters(
        sample_rate=16000,
        encoding=Encoding.pcm_s16le,
        speech_model=SpeechModel.universal_3_5_pro,
        language_codes=["en"],
        language_detection=False,
        min_turn_silence=turn_silence_ms,
        vad_threshold=vad_threshold,
        voice_focus=NoiseSuppressionModel.near_field,
    )

    transcriber = AsyncRealTimeTranscriber(api_key=api_key)

    client_disconnected = False

    async def safe_send(payload: dict):
        nonlocal client_disconnected
        if client_disconnected:
            return
        try:
            await ws.send_text(json.dumps(payload))
        except Exception as e:
            # Log once and mark the client disconnected so handlers stop trying
            logger.info("client disconnected while sending: %s", e)
            client_disconnected = True
            return


    async def on_begin(client, event):
        # Use AssemblyAI event.id as the session identifier for LangGraph
        nonlocal session_id
        session_id = getattr(event, "id", None)
        await safe_send({"type": "begin", "id": session_id})

    # Keep UI transcript tracking separate from processed final turns. AssemblyAI
    # can emit a partial followed by an identical final event.
    last_transcript = ""
    last_processed_turn = None
    last_processed_text = ""
    session_id: str | None = None

    async def on_turn(client, event):
        nonlocal last_transcript, last_processed_turn, last_processed_text
        # event.transcript may be partial; send incremental updates instead
        text = getattr(event, "transcript", "") or ""
        is_final = bool(getattr(event, "end_of_turn", False))

        # language_detection=False does not guarantee that the provider will
        # reject other scripts, so normalize those characters locally first.
        text = _english_only_text(text)

        # Do not display or process turns that AssemblyAI identifies as another
        # language. For final turns, also reject likely noise hallucinations.
        if is_final and (not text or not _accepted_final_turn(event)):
            last_transcript = ""
            return
        if not is_final:
            language_code = getattr(event, "language_code", None)
            if language_code and language_code.lower().split("-")[0] != "en":
                return

        # If nothing changed and not final, skip to avoid duplicates
        if text == last_transcript and not is_final:
            return

        last_transcript = text

        payload = {
            "type": "turn",
            "turn_order": getattr(event, "turn_order", None),
            "transcript": text,
            "is_final": is_final,
        }
        await safe_send(payload)

        # Process only complete turns. Partial events are for display and may
        # contain cumulative text that would otherwise be appended twice.
        try:
            turn_order = getattr(event, "turn_order", None)
            duplicate_final = (
                is_final
                and text == last_processed_text
                and (turn_order is None or turn_order == last_processed_turn)
            )
            if is_final and text and not duplicate_final:
                sid = session_id or "default"
                try:
                    result = await process_chunk(sid, text)
                    state_payload = {
                        "type": "state",
                        "session_id": sid,
                        "report": result.get("report"),
                        "updated_fields": result.get("updated_fields"),
                        "is_finished": result.get("is_finished"),
                    }
                    await safe_send(state_payload)
                    last_processed_turn = turn_order
                    last_processed_text = text
                except Exception as e:
                    if isinstance(e, LLMRateLimitError):
                        logger.warning("LLM rate limit prevented transcript extraction: %s", e)
                        await safe_send({"type": "error", "error": "LLM rate limited; please try again shortly"})
                    else:
                        logger.exception("langgraph process_chunk failed: %s", e)
                        await safe_send({"type": "error", "error": "processing error"})
        except Exception:
            logger.exception("error while processing turn")
        # If this was a final turn, clear last_transcript so the next turn starts fresh
        if is_final:
            last_transcript = ""

    async def on_termination(client, event):
        await safe_send({"type": "termination"})

    async def on_error(client, event):
        # event may be RealTimeError or ErrorEvent
        try:
            msg = event.message
        except Exception:
            msg = str(event)
        await safe_send({"type": "error", "error": msg})

    # Register handlers
    transcriber.on(RealTimeEvents.Begin, on_begin)
    transcriber.on(RealTimeEvents.Turn, on_turn)
    transcriber.on(RealTimeEvents.Termination, on_termination)
    transcriber.on(RealTimeEvents.Error, on_error)

    try:
        await transcriber.connect(params)

        # Read loop from client websocket -> stream to AssemblyAI
        try:
            while True:
                msg = await ws.receive_text()
                # Expecting JSON messages with base64 audio in `audio` field
                try:
                    data = json.loads(msg)
                except Exception:
                    # ignore non-json messages
                    continue

                # 'audio' field contains base64 encoded bytes
                audio_b64 = data.get("audio")
                if audio_b64:
                    try:
                        audio_bytes = base64.b64decode(audio_b64)
                    except Exception:
                        logger.exception("failed to decode base64 audio")
                        continue
                    # send binary chunk to AssemblyAI
                    await transcriber.stream(audio_bytes)

                # handle explicit end/stop message from client
                if data.get("type") == "stop":
                    # Finalize session: generate AI comment only if needed, persist final state, and send it to client
                    sid = session_id or "default"
                    try:
                        from app.services.llm.provider import build_default_llm

                        llm = build_default_llm()

                        final = await finalize(sid, llm=llm)
                        await safe_send({"type": "state", "session_id": sid, "report": final.get("report"), "updated_fields": final.get("updated_fields", []), "is_finished": final.get("is_finished", True)})
                    except Exception:
                        logger.exception("finalize failed for session %s", sid)
                    # then disconnect the transcriber and end loop
                    await transcriber.disconnect(terminate=True)
                    break

        except WebSocketDisconnect:
            # client disconnected
            await transcriber.disconnect(terminate=True)

    except Exception:
        logger.exception("websocket/assemblyai error")
        try:
            await ws.send_text(json.dumps({"error": "internal server error"}))
        except Exception:
            pass
    finally:
        try:
            await transcriber.disconnect(terminate=True)
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass