from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import os
import json
import base64
import asyncio
import logging

from assemblyai.streaming.v3 import (
    AsyncRealTimeTranscriber,
    RealTimeParameters,
    Encoding,
    SpeechModel,
    RealTimeEvents,
)

router = APIRouter()


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
    logger.info("Using TURN_SILENCE_MS=%d ms to finalize turns", turn_silence_ms)

    params = RealTimeParameters(
        sample_rate=16000,
        encoding=Encoding.pcm_s16le,
        speech_model=SpeechModel.universal_3_5_pro,
        min_turn_silence=turn_silence_ms,
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
        await safe_send({"type": "begin", "id": event.id})

    # Keep last transcript to avoid sending duplicate partials
    last_transcript = ""

    async def on_turn(client, event):
        nonlocal last_transcript
        # event.transcript may be partial; send incremental updates instead
        text = getattr(event, "transcript", "") or ""
        is_final = bool(getattr(event, "end_of_turn", False))

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