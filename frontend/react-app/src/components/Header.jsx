import React from "react";
import { RecordButton } from "./RecordButton";

export function Header({ connected, recording, status, error, onToggleRecording }) {
  return (
    <header className="topbar">
      <div className="brand-lockup">
        <div className="brand-mark" aria-hidden="true">PR</div>
        <div><div className="brand-name">Pathology Report</div><div className="brand-caption">AI-assisted dictation</div></div>
      </div>
      <div className="session-status" aria-live="polite"><span className={`status-light ${connected ? "is-live" : ""}`} /><span>{error || status}</span></div>
      <RecordButton connected={connected} recording={recording} onClick={onToggleRecording} />
    </header>
  );
}
