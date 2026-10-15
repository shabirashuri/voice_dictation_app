import React from "react";

// Why a line did not reach the report, in words the clinician can act on.
const IGNORED_REASONS = {
  low_confidence: "Low confidence: not added",
  not_english: "Not English: not added",
  under_review: "Report under review: not added",
  unknown_turn: "Cannot be retried",
};

const FAILED_REASONS = {
  llm_rate_limit: "AI busy: not added",
  validation: "Could not be checked: not added",
  processing: "Not added",
};

function LineStatus({ line, onRetry }) {
  if (line.status === "pending")
    return <span className="transcript-status is-pending" aria-label="Being processed">…</span>;
  if (line.status === "applied")
    return <span className="transcript-status is-applied">Added</span>;
  if (line.status === "ignored")
    return <span className="transcript-status is-ignored">{IGNORED_REASONS[line.code] || "Not added"}</span>;
  if (line.status === "failed")
    return (
      <span className="transcript-status is-failed">
        {FAILED_REASONS[line.code] || "Not added"}
        {onRetry && (
          <button
            className="retry-button"
            type="button"
            onClick={() => onRetry(line.id)}
            aria-label={`Retry: ${line.text}`}
          >
            Retry
          </button>
        )}
      </span>
    );
  return null; // "nothing": processed, no change to report
}

export function TranscriptPanel({ transcripts, livePartial, recording, onRetry }) {
  return (
    <aside className="transcript-panel panel" aria-labelledby="transcript-heading">
      <div className="panel-heading"><div><p className="section-kicker">Audio stream</p><h2 id="transcript-heading">Live transcript</h2></div>{recording && <span className="live-pill"><span /> Listening</span>}</div>
      <div className="transcript-list" aria-live="polite">
        {!transcripts.length && !livePartial ? <div className="empty-state"><div className="waveform-placeholder" aria-hidden="true"><i /><i /><i /><i /><i /></div><p>Your transcript will appear here</p><span>Start speaking to begin the report.</span></div> : <>
          {transcripts.map((line) => (
            <div className={`transcript-entry is-${line.status}`} key={line.id}>
              <p className="transcript-line">{line.text}</p>
              <LineStatus line={line} onRetry={onRetry} />
            </div>
          ))}
          {livePartial && <p className="transcript-line is-live">{livePartial}</p>}
        </>}
      </div>
      <div className="transcript-footer"><span className="pulse-dot" /><span>Transcript updates are processed securely in real time</span></div>
    </aside>
  );
}
