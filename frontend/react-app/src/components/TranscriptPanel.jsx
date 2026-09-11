import React from "react";

export function TranscriptPanel({ transcripts, livePartial, recording }) {
  return (
    <aside className="transcript-panel panel" aria-labelledby="transcript-heading">
      <div className="panel-heading"><div><p className="section-kicker">Audio stream</p><h2 id="transcript-heading">Live transcript</h2></div>{recording && <span className="live-pill"><span /> Listening</span>}</div>
      <div className="transcript-list" aria-live="polite">
        {!transcripts.length && !livePartial ? <div className="empty-state"><div className="waveform-placeholder" aria-hidden="true"><i /><i /><i /><i /><i /></div><p>Your transcript will appear here</p><span>Start speaking to begin the report.</span></div> : <>{transcripts.map((transcript, index) => <p className="transcript-line" key={`${index}-${transcript}`}>{transcript}</p>)}{livePartial && <p className="transcript-line is-live">{livePartial}</p>}</>}
      </div>
      <div className="transcript-footer"><span className="pulse-dot" /><span>Transcript updates are processed securely in real time</span></div>
    </aside>
  );
}
