import React from "react";

export function RecordButton({ connected, recording, onClick }) {
  return (
    <button className={`record-button ${recording ? "is-recording" : ""}`} type="button" onClick={onClick} aria-pressed={recording} title={recording ? "Stop and finish this dictation" : "Start a new dictation"}>
      <span className="record-icon" aria-hidden="true">{recording ? "■" : "●"}</span>
      <span>{recording ? "Stop session" : connected ? "Start speaking" : "Start session"}</span>
    </button>
  );
}
