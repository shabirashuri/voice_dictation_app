import React from "react";
import { ErrorBanner } from "./components/ErrorBanner";
import { Header } from "./components/Header";
import { ReportPanel } from "./components/ReportPanel";
import { ReviewBar } from "./components/ReviewBar";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { useVoiceSession } from "./hooks/useVoiceSession";

export default function App() {
  const session = useVoiceSession();
  const showReview = ["review", "saving", "saved"].includes(session.phase);
  const aiCommentPending =
    session.commentSource === "ai" && Boolean(session.report.comments.trim()) && !session.aiCommentAcknowledged;

  return (
    <div className="app-shell">
      <Header connected={session.connected} recording={session.recording} canStart={session.canStart} status={session.status} onToggleRecording={session.toggleRecording} />
      <main className="workspace">
        <section className="intro-row" aria-labelledby="workspace-title">
          <div>
            <p className="eyebrow">Live clinical workspace</p>
            <h1 id="workspace-title">Pathology report</h1>
            <p className="intro-copy">Speak naturally. The report is structured as your dictation arrives.</p>
          </div>
          <div className="language-badge"><span className="language-dot" /> English transcription</div>
        </section>
        <ErrorBanner error={session.error} onDismiss={session.dismissError} />
        {showReview && (
          <ReviewBar
            phase={session.phase}
            canApprove={!aiCommentPending}
            savedReportId={session.savedReportId}
            onApprove={session.approveAndSave}
            onDiscard={() => {
              if (window.confirm("Discard this report? The dictation will not be saved.")) session.discardReport();
            }}
            onNewSession={session.discardReport}
          />
        )}
        <div className="content-grid">
          <ReportPanel
            report={session.report}
            highlighted={session.highlighted}
            editable={session.editable}
            onFieldChange={session.updateDraftField}
            commentSource={session.commentSource}
            aiCommentAcknowledged={session.aiCommentAcknowledged}
            onAcknowledgeAiComment={session.acknowledgeAiComment}
          />
          <TranscriptPanel transcripts={session.transcripts} livePartial={session.livePartial} recording={session.recording} />
        </div>
      </main>
    </div>
  );
}
