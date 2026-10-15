import React from "react";
import { RecordButton } from "./RecordButton";

export function Header({ connected, recording, canStart, status, onToggleRecording }) {
  return (
    <header className="topbar">
      <div className="brand-lockup">
        <div className="brand-mark" aria-hidden="true">PR</div>
        <div><div className="brand-name">Pathology Report</div><div className="brand-caption">AI-assisted dictation</div></div>
      </div>
      <div className="session-status" aria-live="polite"><span className={`status-light ${connected ? "is-live" : ""}`} /><span>{status}</span></div>
      <RecordButton recording={recording} disabled={!recording && !canStart} onClick={onToggleRecording} />
    </header>
  );
}
