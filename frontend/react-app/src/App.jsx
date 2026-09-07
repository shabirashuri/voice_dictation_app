import React, { useRef, useState } from "react";

function floatTo16BitPCM(float32Array) {
  const l = float32Array.length;
  const buffer = new ArrayBuffer(l * 2);
  const view = new DataView(buffer);
  let offset = 0;
  for (let i = 0; i < l; i++, offset += 2) {
    let s = Math.max(-1, Math.min(1, float32Array[i]));
    s = s < 0 ? s * 0x8000 : s * 0x7fff;
    view.setInt16(offset, s, true);
  }
  return buffer;
}

function downsampleBuffer(buffer, sampleRate, outSampleRate) {
  if (outSampleRate === sampleRate) {
    return buffer;
  }
  if (outSampleRate > sampleRate) {
    console.warn("downsampling rate should be smaller than original");
    return buffer;
  }
  const sampleRateRatio = sampleRate / outSampleRate;
  const newLength = Math.round(buffer.length / sampleRateRatio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * sampleRateRatio);
    let accum = 0,
      count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
      accum += buffer[i];
      count++;
    }
    result[offsetResult] = accum / count;
    offsetResult++;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

export default function App() {
  const [wsUrl, setWsUrl] = useState("ws://localhost:8000/ws/voice");
  const [connected, setConnected] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcripts, setTranscripts] = useState([]);
  const [livePartial, setLivePartial] = useState("")
  const lastTurnRef = useRef(null)

  const wsRef = useRef(null);
  const audioRef = useRef({
    audioContext: null,
    processor: null,
    stream: null,
  });

  function appendTranscript(t) {
    setTranscripts((prev) => [...prev, t]);
  }

  const connect = () => {
    if (wsRef.current) return;
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => setConnected(true);
    ws.onmessage = (evt) => {
      try {
        const d = JSON.parse(evt.data);
        if (d.type === "turn") {
          const isFinal = Boolean(d.is_final);
          const turnOrder = d.turn_order ?? null;

          if (isFinal) {
            // finalize: push transcript into finalized list and clear live partial
            setTranscripts((prev) => [...prev, d.transcript]);
            setLivePartial("");
            lastTurnRef.current = null;
          } else {
            // partial: start or update live partial for the current turn
            if (lastTurnRef.current === null || lastTurnRef.current !== turnOrder) {
              lastTurnRef.current = turnOrder;
              setLivePartial(d.transcript);
            } else {
              setLivePartial(d.transcript);
            }
          }
        } else if (d.type === "begin") {
          setTranscripts((prev) => [...prev, "[Session started]"]);
        } else if (d.type === "termination") {
          setTranscripts((prev) => [...prev, "[Session terminated]"]);
        } else if (d.error) {
          setTranscripts((prev) => [...prev, "[Error] " + d.error]);
        }
      } catch (e) {
        console.log("non-json", evt.data);
      }
    };
    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
    };
    ws.onerror = (e) => {
      console.error(e);
    };
    wsRef.current = ws;
  };

  const disconnect = () => {
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch (e) {}
      wsRef.current = null;
    }
    setConnected(false);
  };

  const startRecording = async () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      connect();
      // wait a short time for connect
      await new Promise((r) => setTimeout(r, 200));
    }
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      alert("WebSocket not connected");
      return;
    }

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const audioContext = new (
      window.AudioContext || window.webkitAudioContext
    )();
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    source.connect(processor);
    processor.connect(audioContext.destination);
    const sampleRate = audioContext.sampleRate;

    processor.onaudioprocess = function (e) {
      const inputData = e.inputBuffer.getChannelData(0);
      const downsampled = downsampleBuffer(inputData, sampleRate, 16000);
      const pcm16Buffer = floatTo16BitPCM(downsampled);
      const uint8 = new Uint8Array(pcm16Buffer);
      let binary = "";
      const chunkSize = 0x8000;
      for (let i = 0; i < uint8.length; i += chunkSize) {
        binary += String.fromCharCode.apply(
          null,
          uint8.subarray(i, i + chunkSize),
        );
      }
      const b64 = btoa(binary);
      const payload = JSON.stringify({ audio: b64 });
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(payload);
      }
    };

    audioRef.current = { audioContext, processor, stream };
    setRecording(true);
  };

  const stopRecording = () => {
    const { audioContext, processor, stream } = audioRef.current;
    if (processor) {
      try {
        processor.disconnect();
        processor.onaudioprocess = null;
      } catch (e) {}
    }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
    }
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "stop" }));
    }
    setRecording(false);
  };

  return (
    <div style={{ padding: 20, fontFamily: "Arial, sans-serif" }}>
      <h2>Voice Dictation — React</h2>
      <div style={{ marginBottom: 12 }}>
        <input
          style={{ width: 360 }}
          value={wsUrl}
          onChange={(e) => setWsUrl(e.target.value)}
        />
        <button
          onClick={connect}
          disabled={connected}
          style={{ marginLeft: 8 }}
        >
          Connect
        </button>
        <button
          onClick={disconnect}
          disabled={!connected}
          style={{ marginLeft: 8 }}
        >
          Disconnect
        </button>
      </div>

      <div style={{ marginBottom: 12 }}>
        <button
          onClick={recording ? stopRecording : startRecording}
          disabled={!connected && !recording}
        >
          {recording ? "Stop Speaking" : "Start Speaking"}
        </button>
      </div>

      <div
        style={{
          border: "1px solid #ddd",
          padding: 8,
          height: 300,
          overflow: "auto",
        }}
      >
        {transcripts.length === 0 && livePartial === "" ? (
          <div style={{ color: '#666' }}>Transcript will appear here...</div>
        ) : (
          <>
            {transcripts.map((t,i) => <div key={"f-"+i} style={{ marginBottom: 6 }}>{t}</div>)}
            {livePartial !== "" && (
              <div key="live" style={{ marginBottom: 6, color: '#333', fontStyle: 'italic' }}>{livePartial}</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
