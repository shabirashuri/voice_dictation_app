from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
import os
import json
import base64
import asyncio
import itertools
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

from app.core.security import AuthConfigError, decode_access_token
from app.db.session import get_session_factory
from app.graph.routers import process_chunk, finalize
from app.prompts.pathology_terms import PATHOLOGY_TERMS
from app.repositories.case import get_case
from app.graph import workflow as _workflow_mod
from app.services.llm.provider import LLMAPIError, LLMRateLimitError, LLMTransientError
from app.services.streaming.worker import ChunkWorker, Turn

router = APIRouter()

# How long a connected client may stay silent (no audio, no messages) before
# the socket is closed. Covers both live dictation and the review phase.
def _idle_timeout_seconds() -> float:
    try:
        return float(os.environ.get("WS_IDLE_TIMEOUT_SECONDS", "900"))
    except ValueError:
        return 900.0


def _stop_drain_timeout_seconds() -> float:
    """How long Stop waits for in-flight chunks before finalizing without them."""
    try:
        return float(os.environ.get("STOP_DRAIN_TIMEOUT_SECONDS", "30"))
    except ValueError:
        return 30.0


# Errors worth retrying: rate limits, timeouts, connection failures, 5xx.
# A rejected request (e.g. bad API key) is not retried.
TRANSIENT_LLM_ERRORS = (LLMRateLimitError, LLMTransientError)
# Waits before each retry of a transient LLM failure.
# Three retries after the first attempt: four tries in total.
RETRY_DELAYS = (1.0, 3.0, 8.0)
# Silence before a turn ends. Long enough to keep a sentence with a mid-sentence
# pause together, short enough that the report updates while the doctor talks.
DEFAULT_TURN_SILENCE_MS = 3000
# Texts of failed chunks kept per session so the clinician can retry them.
MAX_FAILED_TURNS = 50


# Scripts kept in transcripts: Latin (incl. accented letters) and Greek (used
# for markers such as "α-SMA"). Everything else that is a letter or mark, e.g.
# Arabic, Cyrillic, CJK or Devanagari, is noise for an English report.
_KEPT_SCRIPT_PREFIXES = ("LATIN", "GREEK")
# Symbols that look like letters but carry meaning in pathology text.
_KEPT_SYMBOLS = {"\u00b5"}  # MICRO SIGN (µm)
# Combining diacritics (U+0300–U+036F) attach to Latin letters, e.g. decomposed "é".
_COMBINING_LATIN_RANGE = range(0x0300, 0x0370)


def _keep_character(character: str) -> bool:
    if ord(character) <= 127 or character in _KEPT_SYMBOLS:
        return True
    category = unicodedata.category(character)
    if category[0] not in {"L", "M"}:
        return True  # digits, punctuation, symbols such as × and °
    if category[0] == "M":
        return ord(character) in _COMBINING_LATIN_RANGE
    try:
        name = unicodedata.name(character)
    except ValueError:
        return False
    return name.startswith(_KEPT_SCRIPT_PREFIXES)


def _english_only_text(text: str) -> str:
    """Remove letters from non-Latin, non-Greek scripts; keep medical symbols and accents."""
    filtered = "".join(character for character in text if _keep_character(character))
    normalized = " ".join(filtered.split())
    return re.sub(r"\s+([,.!?;:])", r"\1", normalized)


def _final_turn_ignore_reason(event) -> str | None:
    """Why a final turn must not reach the report, or None if it may."""
    language_code = getattr(event, "language_code", None)
    if language_code and language_code.lower().split("-")[0] != "en":
        return "not_english"
    words = getattr(event, "words", None) or []
    confidences = [getattr(word, "confidence", 0.0) for word in words]
    if confidences and sum(confidences) / len(confidences) < 0.55:
        return "low_confidence"
    return None


AUTH_TIMEOUT_SECONDS = 10


async def _authorize(ws: WebSocket, session_factory) -> tuple[str | None, str | None]:
    """Wait for the client's first message, `{"type": "auth", "token", "case_id"}`.

    Browsers can't set headers on a WebSocket; sending the token as a message
    keeps it out of URLs and access logs. Returns (patient_text, error).
    """
    try:
        data = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=AUTH_TIMEOUT_SECONDS))
    except (asyncio.TimeoutError, ValueError):
        return None, "expected an auth message first"
    if not isinstance(data, dict) or data.get("type") != "auth":
        return None, "expected an auth message first"
    try:
        user_id = decode_access_token(str(data.get("token") or ""))
    except AuthConfigError:
        return None, "server authentication is not configured"
    if user_id is None:
        return None, "not signed in or session expired"
    try:
        case_id = int(data.get("case_id"))
    except (TypeError, ValueError):
        return None, "case_id is required"
    # Short-lived session: no DB connection is held during dictation.
    async with session_factory() as db:
        case = await get_case(db, user_id, case_id)
        if case is None:
            return None, "case not found"
        if case.report is not None:
            return None, "this case already has an approved report"
        patient = case.patient_name + (f" (MRN {case.patient_mrn})" if case.patient_mrn else "")
    return patient, None


@router.websocket("/ws/voice")
async def websocket_voice(ws: WebSocket, session_factory=Depends(get_session_factory)):
    await ws.accept()
    logger = logging.getLogger("voice_ws")

    try:
        case_patient, auth_error = await _authorize(ws, session_factory)
    except WebSocketDisconnect:
        return
    if auth_error:
        await ws.send_text(json.dumps({"type": "error", "code": "auth", "error": auth_error}))
        await ws.close(code=1008)
        return

    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        await ws.send_text(json.dumps({"type": "error", "code": "stt", "error": "missing AssemblyAI API key"}))
        await ws.close()
        return

    # Configure real-time parameters: PCM 16-bit, 16k sample rate, use universal model
    # Allow configurable turn silence via TURN_SILENCE_MS env var (milliseconds).
    try:
        turn_silence_ms = int(os.environ.get("TURN_SILENCE_MS", str(DEFAULT_TURN_SILENCE_MS)))
    except Exception:
        turn_silence_ms = DEFAULT_TURN_SILENCE_MS
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
        keyterms_prompt=PATHOLOGY_TERMS,
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
        # Start the case's report with its patient; dictation can add to it.
        if session_id:
            _workflow_mod.seed_patient(session_id, case_patient)
        await safe_send({"type": "begin", "id": session_id})

    # Keep UI transcript tracking separate from final turns. AssemblyAI can emit
    # a partial followed by an identical final event, so dedupe final turns here.
    last_transcript = ""
    last_submitted_turn = None
    last_submitted_text = ""
    turn_ids = itertools.count(1)
    failed_turns: dict[int, str] = {}
    session_id: str | None = None

    async def report_status(turn_id: int, status: str, code: str | None = None):
        payload = {"type": "chunk_status", "turn_id": turn_id, "status": status}
        if code:
            payload["code"] = code
        await safe_send(payload)

    def remember_failed(turn_id: int, text: str):
        failed_turns[turn_id] = text
        while len(failed_turns) > MAX_FAILED_TURNS:
            failed_turns.pop(next(iter(failed_turns)))

    async def process_with_retries(sid: str, text: str) -> dict:
        """Run one chunk. Transient LLM failures are retried with backoff; the
        final attempt's error propagates. Failed attempts leave state unchanged,
        so retrying the same text is safe."""
        for delay in (*RETRY_DELAYS, None):
            try:
                return await process_chunk(sid, text)
            except TRANSIENT_LLM_ERRORS as exc:
                if delay is None:
                    raise
                logger.warning("transient LLM failure (%s); retrying in %.0fs", type(exc).__name__, delay)
                await asyncio.sleep(delay)

    async def handle_turn(turn: Turn):
        """Runs on the worker: one final turn, processed in order."""
        sid = session_id or "default"
        try:
            result = await process_with_retries(sid, turn.text)
        except Exception as exc:
            if isinstance(exc, LLMAPIError):
                logger.warning("chunk %d not applied: %s", turn.turn_id, type(exc).__name__)
            else:
                logger.exception("langgraph process_chunk failed")
            remember_failed(turn.turn_id, turn.text)
            code = "llm_rate_limit" if isinstance(exc, LLMRateLimitError) else "processing"
            await report_status(turn.turn_id, "failed", code)
            return

        await safe_send({
            "type": "state",
            "session_id": sid,
            "report": result.get("report"),
            "updated_fields": result.get("updated_fields"),
            "is_finished": result.get("is_finished"),
        })
        if result.get("skipped"):
            await report_status(turn.turn_id, "ignored", result["skipped"])
        elif result.get("error_code"):
            remember_failed(turn.turn_id, turn.text)
            await report_status(turn.turn_id, "failed", result["error_code"])
        else:
            await report_status(turn.turn_id, "applied" if result.get("updated_fields") else "nothing")

    async def retry_turn(raw_turn_id, under_review: bool):
        try:
            turn_id = int(raw_turn_id)
        except (TypeError, ValueError):
            return
        if under_review:
            await report_status(turn_id, "ignored", "under_review")
            return
        text = failed_turns.pop(turn_id, None)
        if text is None:
            await report_status(turn_id, "ignored", "unknown_turn")
            return
        worker.submit(Turn(text=text, turn_id=turn_id))

    worker = ChunkWorker(handle_turn)

    async def on_turn(client, event):
        nonlocal last_transcript, last_submitted_turn, last_submitted_text
        is_final = bool(getattr(event, "end_of_turn", False))
        turn_order = getattr(event, "turn_order", None)
        # language_detection=False does not guarantee that the provider will
        # reject other scripts, so normalize those characters locally first.
        text = _english_only_text(getattr(event, "transcript", "") or "")

        if not is_final:
            # Partials are display-only: skip other languages and unchanged text.
            language_code = getattr(event, "language_code", None)
            if language_code and language_code.lower().split("-")[0] != "en":
                return
            if text == last_transcript:
                return
            last_transcript = text
            await safe_send({"type": "turn", "turn_order": turn_order, "transcript": text, "is_final": False})
            return

        last_transcript = ""
        if not text:
            return
        # AssemblyAI can send an identical final event twice; handle each turn once.
        if text == last_submitted_text and (turn_order is None or turn_order == last_submitted_turn):
            return
        last_submitted_text = text
        last_submitted_turn = turn_order

        turn_id = next(turn_ids)
        await safe_send({"type": "turn", "turn_id": turn_id, "turn_order": turn_order, "transcript": text, "is_final": True})
        # Every final turn gets a status: nothing is dropped silently.
        reason = _final_turn_ignore_reason(event)
        if reason:
            await report_status(turn_id, "ignored", reason)
            return
        # Returns at once; extraction happens on the worker, so this callback
        # (and partial transcripts) is never held up by the LLM.
        worker.submit(Turn(text=text, turn_id=turn_id))

    async def on_termination(client, event):
        await safe_send({"type": "termination"})

    async def on_error(client, event):
        # event may be RealTimeError or ErrorEvent
        try:
            msg = event.message
        except Exception:
            msg = str(event)
        await safe_send({"type": "error", "code": "stt", "error": msg})

    async def finish_dictation(sid_hint: str | None):
        """Stop: flush the open utterance, close STT, let queued turns finish, then finalize."""
        # 1. Ask STT to end the open utterance now, so its final turn is emitted
        #    even if the speaker didn't pause before pressing Stop.
        try:
            await transcriber.force_endpoint()
        except Exception:
            logger.exception("force_endpoint failed")
        # 2. Close STT. The SDK waits for its termination event, and final turns
        #    arriving meanwhile reach on_turn, which enqueues them.
        try:
            await transcriber.disconnect(terminate=True)
        except Exception:
            logger.exception("failed to disconnect transcriber")
        # 3. Let every queued turn finish, bounded so a hung LLM can't block Stop.
        if not await worker.drain(_stop_drain_timeout_seconds()):
            abandoned = await worker.cancel()
            logger.warning("stop timed out; abandoning %d turn(s) for session %s", abandoned, sid_hint)
            await safe_send({
                "type": "error",
                "code": "processing",
                "error": f"{abandoned} dictated part(s) could not be processed in time; please add them manually",
            })
        # 4. Finalize the report and hand it to the clinician for review.
        sid = session_id or "default"
        try:
            from app.services.llm.provider import build_default_llm

            final = await finalize(sid, llm=build_default_llm())
            await safe_send({
                "type": "state",
                "session_id": sid,
                "report": final.get("report"),
                "updated_fields": [],
                "is_finished": final.get("is_finished", False),
                "awaiting_review": final.get("awaiting_review", False),
            })
            if final.get("error_code"):
                await safe_send({
                    "type": "error",
                    "code": final["error_code"],
                    "error": final.get("error_message") or "finalize error",
                })
        except Exception:
            logger.exception("finalize failed for session %s", sid)
            await safe_send({"type": "error", "code": "finalize", "error": "could not finalize the report"})

    # Register handlers
    transcriber.on(RealTimeEvents.Begin, on_begin)
    transcriber.on(RealTimeEvents.Turn, on_turn)
    transcriber.on(RealTimeEvents.Termination, on_termination)
    transcriber.on(RealTimeEvents.Error, on_error)

    try:
        await transcriber.connect(params)
        worker.start()

        # Read loop from client websocket. While dictating, audio is streamed
        # to AssemblyAI. After `stop`, the transcriber is closed but the socket
        # stays open so the clinician can review the finalized report; the
        # client ends the session with `close` (or by disconnecting).
        reviewing = False
        idle_timeout = _idle_timeout_seconds()
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive_text(), timeout=idle_timeout)
                except asyncio.TimeoutError:
                    logger.info("closing idle websocket session %s", session_id)
                    await safe_send({"type": "error", "code": "timeout", "error": "session closed after inactivity"})
                    break
                # Expecting JSON messages with base64 audio in `audio` field
                try:
                    data = json.loads(msg)
                except Exception:
                    # ignore non-json messages
                    continue

                if data.get("type") == "close":
                    break

                if data.get("type") == "retry":
                    await retry_turn(data.get("turn_id"), under_review=reviewing)
                    continue

                # 'audio' field contains base64 encoded bytes; ignored once reviewing
                audio_b64 = data.get("audio")
                if audio_b64 and not reviewing:
                    try:
                        audio_bytes = base64.b64decode(audio_b64)
                    except Exception:
                        logger.exception("failed to decode base64 audio")
                        continue
                    # send binary chunk to AssemblyAI
                    await transcriber.stream(audio_bytes)

                if data.get("type") == "stop" and not reviewing:
                    reviewing = True
                    await finish_dictation(session_id)

        except WebSocketDisconnect:
            # client disconnected
            pass

    except Exception:
        logger.exception("websocket/assemblyai error")
        try:
            await ws.send_text(json.dumps({"type": "error", "code": "internal", "error": "internal server error"}))
        except Exception:
            pass
    finally:
        try:
            await transcriber.disconnect(terminate=True)
        except Exception:
            pass
        # Live state is not kept after the session ends; the clinician-approved
        # report is saved separately through the reports API.
        await worker.cancel()
        _workflow_mod.discard_session(session_id or "default")
        try:
            await ws.close()
        except Exception:
            pass