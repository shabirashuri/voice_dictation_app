import React from "react";

export function RecordButton({ recording, disabled, onClick }) {
  return (
    <button className={`record-button ${recording ? "is-recording" : ""}`} type="button" onClick={onClick} disabled={disabled} aria-pressed={recording} title={recording ? "Stop and finish this dictation" : "Start a new dictation"}>
      <span className="record-icon" aria-hidden="true">{recording ? "■" : "●"}</span>
      <span>{recording ? "Stop session" : "Start session"}</span>
    </button>
  );
}
