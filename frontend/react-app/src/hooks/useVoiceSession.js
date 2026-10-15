import { useCallback, useEffect, useRef, useState } from "react";
import { encodeAudioChunk } from "../lib/audio";

const EMPTY_REPORT = {
  patient: "",
  specimen: "",
  gross_description: "",
  microscopic_description: "",
  diagnosis: "",
  comments: "",
};

const REPORT_KEYS = Object.keys(EMPTY_REPORT);

// idle → connecting → recording → finalizing → review → saving → saved
const STATUS_BY_PHASE = {
  idle: "Ready for a new session",
  connecting: "Connecting securely...",
  recording: "Listening in English",
  finalizing: "Finalizing report...",
  review: "Review and approve the report",
  saving: "Saving report...",
  saved: "Report saved",
};

function websocketUrl() {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL;
  return `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.hostname || "localhost"}:8000/ws/voice`;
}

function apiBaseUrl() {
  if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL.replace(/\/$/, "");
  return `${window.location.protocol}//${window.location.hostname || "localhost"}:8000`;
}

function pickReport(report) {
  return Object.fromEntries(REPORT_KEYS.map((key) => [key, report?.[key] || ""]));
}

export function useVoiceSession() {
  const [phase, setPhaseState] = useState("idle");
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);
  const [report, setReport] = useState(EMPTY_REPORT);
  const [draft, setDraft] = useState(EMPTY_REPORT);
  const [commentSource, setCommentSource] = useState(null);
  const [aiCommentAcknowledged, setAiCommentAcknowledged] = useState(false);
  const [savedReportId, setSavedReportId] = useState(null);
  const [highlighted, setHighlighted] = useState([]);
  const [transcripts, setTranscripts] = useState([]);
  const [livePartial, setLivePartial] = useState("");
  const wsRef = useRef(null);
  const sessionIdRef = useRef(null);
  const phaseRef = useRef("idle");
  const reportRef = useRef(EMPTY_REPORT);
  const audioRef = useRef({ context: null, processor: null, stream: null });
  const highlightTimerRef = useRef(null);

  const setPhase = useCallback((next) => {
    phaseRef.current = next;
    setPhaseState(next);
  }, []);

  const stopAudio = useCallback(() => {
    const { context, processor, stream } = audioRef.current;
    if (processor) {
      processor.disconnect();
      processor.onaudioprocess = null;
    }
    if (stream) stream.getTracks().forEach((track) => track.stop());
    if (context) context.close().catch(() => {});
    audioRef.current = { context: null, processor: null, stream: null };
  }, []);

  // Ends the server session politely; the server drops its live state on close.
  const closeSocket = useCallback(() => {
    const socket = wsRef.current;
    wsRef.current = null;
    if (socket) {
      if (socket.readyState === WebSocket.OPEN)
        socket.send(JSON.stringify({ type: "close" }));
      socket.close();
    }
    setConnected(false);
  }, []);

  const resetSessionView = useCallback(() => {
    reportRef.current = EMPTY_REPORT;
    sessionIdRef.current = null;
    setReport(EMPTY_REPORT);
    setDraft(EMPTY_REPORT);
    setCommentSource(null);
    setAiCommentAcknowledged(false);
    setSavedReportId(null);
    setHighlighted([]);
    setTranscripts([]);
    setLivePartial("");
  }, []);

  // Freeze the latest report into an editable draft for clinician review.
  const enterReview = useCallback(
    (finalReport) => {
      const source = finalReport?.comment_source ?? null;
      setDraft(pickReport(finalReport));
      setCommentSource(source);
      setAiCommentAcknowledged(source !== "ai");
      setPhase("review");
    },
    [setPhase],
  );

  const handleMessage = useCallback(
    (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "state" || data.type === "report_state_update") {
        if (data.report) {
          const next = { ...EMPTY_REPORT, ...data.report };
          reportRef.current = next;
          setReport(next);
        }
        const updated = data.updated_fields || [];
        if (updated.length) {
          setHighlighted(updated);
          window.clearTimeout(highlightTimerRef.current);
          highlightTimerRef.current = window.setTimeout(
            () => setHighlighted([]),
            1800,
          );
        }
        if (data.awaiting_review && phaseRef.current === "finalizing")
          enterReview(data.report);
        return;
      }
      if (data.type === "begin") {
        sessionIdRef.current = data.id || null;
        return;
      }
      if (data.type === "turn") {
        const text = data.transcript || "";
        if (data.is_final) {
          if (text) setTranscripts((previous) => [...previous, text]);
          setLivePartial("");
        } else if (text) setLivePartial(text);
        return;
      }
      if (data.type === "termination") return;
      if (data.type === "error" || data.error) {
        setError({ code: data.code || "unknown", message: data.error || "Unexpected error" });
        // If finalize failed outright, still let the clinician review and
        // complete the report by hand.
        if (data.code === "finalize" && phaseRef.current === "finalizing")
          enterReview(reportRef.current);
      }
    },
    [enterReview],
  );

  const startSession = useCallback(async () => {
    if (wsRef.current) closeSocket();
    setError(null);
    resetSessionView();
    setPhase("connecting");
    const socket = new WebSocket(websocketUrl());
    wsRef.current = socket;
    socket.onopen = async () => {
      if (wsRef.current !== socket) return;
      setConnected(true);
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: false,
          },
        });
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        const context = new AudioContext();
        const source = context.createMediaStreamSource(stream);
        const processor = context.createScriptProcessor(4096, 1, 1);
        source.connect(processor);
        processor.connect(context.destination);
        processor.onaudioprocess = (event) => {
          if (wsRef.current === socket && socket.readyState === WebSocket.OPEN)
            socket.send(
              JSON.stringify({
                audio: encodeAudioChunk(
                  event.inputBuffer.getChannelData(0),
                  context.sampleRate,
                ),
              }),
            );
        };
        audioRef.current = { context, processor, stream };
        setPhase("recording");
      } catch (microphoneError) {
        setError({
          code: "microphone",
          message:
            microphoneError.name === "NotAllowedError"
              ? "Microphone permission is required"
              : "Could not access microphone",
        });
        closeSocket();
        setPhase("idle");
      }
    };
    socket.onmessage = (event) => {
      if (wsRef.current === socket) handleMessage(event);
    };
    socket.onerror = () => {
      if (wsRef.current === socket)
        setError({ code: "connection", message: "Connection failed. Check that the backend is running." });
    };
    socket.onclose = () => {
      // Ignore late closes from a previous session's socket.
      if (wsRef.current !== socket) return;
      wsRef.current = null;
      stopAudio();
      setConnected(false);
      const current = phaseRef.current;
      if (current === "connecting" || current === "recording") {
        setError({ code: "connection", message: "Connection closed before the report was finalized." });
        setPhase("idle");
      } else if (current === "finalizing") {
        // The draft can still be reviewed and saved over HTTP.
        enterReview(reportRef.current);
      }
    };
  }, [closeSocket, enterReview, handleMessage, resetSessionView, setPhase, stopAudio]);

  const stopSession = useCallback(() => {
    stopAudio();
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setPhase("finalizing");
      wsRef.current.send(JSON.stringify({ type: "stop" }));
    } else {
      closeSocket();
      setPhase("idle");
    }
  }, [closeSocket, setPhase, stopAudio]);

  const updateDraftField = useCallback(
    (key, value) => {
      if (phaseRef.current !== "review") return;
      setDraft((previous) => ({ ...previous, [key]: value }));
      // Editing the AI comment counts as reviewing it; it stays labelled AI.
      if (key === "comments") setAiCommentAcknowledged(true);
    },
    [],
  );

  // POST /reports {session_id, report, comment_source} -> {id, ...}
  const approveAndSave = useCallback(async () => {
    if (phaseRef.current !== "review") return;
    setError(null);
    setPhase("saving");
    try {
      const response = await fetch(`${apiBaseUrl()}/reports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionIdRef.current,
          report: draft,
          // A comment typed in review with no prior source is the clinician's.
          comment_source: draft.comments.trim() ? commentSource || "doctor" : null,
        }),
      });
      if (!response.ok) {
        let detail = "";
        try {
          const body = await response.json();
          detail = typeof body.detail === "string" ? body.detail : "";
        } catch {
          // non-JSON error body
        }
        throw new Error(detail || `Save failed (HTTP ${response.status})`);
      }
      const saved = await response.json().catch(() => ({}));
      setSavedReportId(saved.id ?? null);
      setPhase("saved");
      closeSocket();
    } catch (saveError) {
      setError({ code: "save", message: saveError.message || "Could not save the report" });
      setPhase("review");
    }
  }, [closeSocket, commentSource, draft, setPhase]);

  const discardReport = useCallback(() => {
    closeSocket();
    resetSessionView();
    setError(null);
    setPhase("idle");
  }, [closeSocket, resetSessionView, setPhase]);

  useEffect(
    () => () => {
      stopAudio();
      if (wsRef.current) wsRef.current.close();
      window.clearTimeout(highlightTimerRef.current);
    },
    [stopAudio],
  );

  const inReview = phase === "review" || phase === "saving" || phase === "saved";

  return {
    phase,
    connected,
    recording: phase === "recording",
    status: STATUS_BY_PHASE[phase],
    error,
    dismissError: () => setError(null),
    report: inReview ? draft : report,
    editable: phase === "review",
    commentSource,
    aiCommentAcknowledged,
    acknowledgeAiComment: setAiCommentAcknowledged,
    savedReportId,
    highlighted,
    transcripts,
    livePartial,
    updateDraftField,
    approveAndSave,
    discardReport,
    canStart: phase === "idle" || phase === "saved",
    toggleRecording: phase === "recording" ? stopSession : startSession,
  };
}
