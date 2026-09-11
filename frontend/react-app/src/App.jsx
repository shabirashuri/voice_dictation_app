import React from "react";
import { Header } from "./components/Header";
import { ReportPanel } from "./components/ReportPanel";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { useVoiceSession } from "./hooks/useVoiceSession";

export default function App() {
  const session = useVoiceSession();

  return (
    <div className="app-shell">
      <Header connected={session.connected} recording={session.recording} status={session.status} error={session.error} onToggleRecording={session.toggleRecording} />
      <main className="workspace">
        <section className="intro-row" aria-labelledby="workspace-title">
          <div>
            <p className="eyebrow">Live clinical workspace</p>
            <h1 id="workspace-title">Pathology report</h1>
            <p className="intro-copy">Speak naturally. The report is structured as your dictation arrives.</p>
          </div>
          <div className="language-badge"><span className="language-dot" /> English transcription</div>
        </section>
        <div className="content-grid">
          <ReportPanel report={session.report} highlighted={session.highlighted} />
          <TranscriptPanel transcripts={session.transcripts} livePartial={session.livePartial} recording={session.recording} />
        </div>
      </main>
    </div>
  );
}
