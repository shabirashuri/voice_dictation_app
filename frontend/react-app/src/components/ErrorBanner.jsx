import React from "react";

const TITLES = {
  stt: "Transcription problem",
  llm_rate_limit: "AI service busy",
  validation: "Part of the dictation was not applied",
  processing: "Processing problem",
  finalize: "Finalization problem",
  save: "Report not saved",
  timeout: "Session timed out",
  connection: "Connection problem",
  microphone: "Microphone problem",
};

export function ErrorBanner({ error, onDismiss }) {
  if (!error) return null;
  return (
    <div className="error-banner" role="alert">
      <div>
        <strong>{TITLES[error.code] || "Something went wrong"}</strong>
        <span>{error.message}</span>
      </div>
      <button className="error-dismiss" type="button" onClick={onDismiss} aria-label="Dismiss error">Dismiss</button>
    </div>
  );
}
