import { useCallback, useEffect, useRef, useState } from "react";
import { encodeAudioChunk } from "../lib/audio";

const EMPTY_REPORT = { patient: "", specimen: "", gross_description: "", microscopic_description: "", diagnosis: "", comments: "" };

function websocketUrl() {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL;
  return `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.hostname || "localhost"}:8000/ws/voice`;
}

export function useVoiceSession() {
  const [connected, setConnected] = useState(false);
  const [recording, setRecording] = useState(false);
  const [status, setStatus] = useState("Ready for a new session");
  const [error, setError] = useState("");
  const [report, setReport] = useState(EMPTY_REPORT);
  const [highlighted, setHighlighted] = useState([]);
  const [transcripts, setTranscripts] = useState([]);
  const [livePartial, setLivePartial] = useState("");
  const wsRef = useRef(null);
  const audioRef = useRef({ context: null, processor: null, stream: null });
  const highlightTimerRef = useRef(null);

  const stopAudio = useCallback(() => {
    const { context, processor, stream } = audioRef.current;
    if (processor) { processor.disconnect(); processor.onaudioprocess = null; }
    if (stream) stream.getTracks().forEach((track) => track.stop());
    if (context) context.close().catch(() => {});
    audioRef.current = { context: null, processor: null, stream: null };
  }, []);

  const closeSocket = useCallback(() => {
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
    setConnected(false);
  }, []);

  const resetSessionView = useCallback(() => {
    setReport(EMPTY_REPORT); setHighlighted([]); setTranscripts([]); setLivePartial("");
  }, []);

  const handleMessage = useCallback((event) => {
    const data = JSON.parse(event.data);
    if (data.type === "state" || data.type === "report_state_update") {
      if (data.report) setReport({ ...EMPTY_REPORT, ...data.report });
      const updated = data.updated_fields || [];
      if (updated.length) {
        setHighlighted(updated);
        window.clearTimeout(highlightTimerRef.current);
        highlightTimerRef.current = window.setTimeout(() => setHighlighted([]), 1800);
      }
      if (data.is_finished) setStatus("Report finalized");
      return;
    }
    if (data.type === "begin") { setStatus("Session active"); return; }
    if (data.type === "turn") {
      const text = data.transcript || "";
      if (data.is_final) { if (text) setTranscripts((previous) => [...previous, text]); setLivePartial(""); }
      else if (text) setLivePartial(text);
      return;
    }
    if (data.type === "termination") { setStatus("Session terminated"); return; }
    if (data.error) setError(data.error);
  }, []);

  const startSession = useCallback(async () => {
    setError(""); resetSessionView(); setStatus("Connecting securely...");
    const socket = new WebSocket(websocketUrl());
    wsRef.current = socket;
    socket.onopen = async () => {
      setConnected(true); setStatus("Requesting microphone...");
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
        source.connect(processor); processor.connect(context.destination);
        processor.onaudioprocess = (event) => {
          if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ audio: encodeAudioChunk(event.inputBuffer.getChannelData(0), context.sampleRate) }));
        };
        audioRef.current = { context, processor, stream };
        setRecording(true); setStatus("Listening in English");
      } catch (microphoneError) {
        setError(microphoneError.name === "NotAllowedError" ? "Microphone permission is required" : "Could not access microphone");
        closeSocket();
      }
    };
    socket.onmessage = handleMessage;
    socket.onerror = () => setError("Connection failed. Check that the backend is running.");
    socket.onclose = () => { stopAudio(); setRecording(false); setConnected(false); wsRef.current = null; };
  }, [closeSocket, handleMessage, resetSessionView, stopAudio]);

  const stopSession = useCallback(() => {
    stopAudio();
    if (wsRef.current?.readyState === WebSocket.OPEN) { setStatus("Finalizing report..."); wsRef.current.send(JSON.stringify({ type: "stop" })); }
    else closeSocket();
    setRecording(false);
  }, [closeSocket, stopAudio]);

  useEffect(() => () => { stopAudio(); if (wsRef.current) wsRef.current.close(); window.clearTimeout(highlightTimerRef.current); }, [stopAudio]);

  return { connected, recording, status, error, report, highlighted, transcripts, livePartial, toggleRecording: recording ? stopSession : startSession };
}
