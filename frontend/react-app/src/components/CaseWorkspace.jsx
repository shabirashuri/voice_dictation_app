import React, { useEffect } from "react";
import { useVoiceSession } from "../hooks/useVoiceSession";
import { ErrorBanner } from "./ErrorBanner";
import { RecordButton } from "./RecordButton";
import { ReportPanel } from "./ReportPanel";
import { ReviewBar } from "./ReviewBar";
import { TranscriptPanel } from "./TranscriptPanel";

function CaseHeader({ caseDetail, children }) {
  return (
    <section className="case-header" aria-labelledby="case-title">
      <div>
        <p className="eyebrow">Case {caseDetail.case_number}</p>
        <h1 id="case-title">{caseDetail.patient_name}</h1>
        <p className="intro-copy">{caseDetail.patient_mrn ? `MRN ${caseDetail.patient_mrn}` : "No MRN recorded"}</p>
      </div>
      <div className="case-header-actions">{children}</div>
    </section>
  );
}

function ReportedCase({ caseDetail }) {
  const { report } = caseDetail;
  const approved = report.approved_at ? new Date(report.approved_at).toLocaleString() : null;
  return (
    <>
      <CaseHeader caseDetail={caseDetail}>
        <span className="case-status is-reported">Reported</span>
      </CaseHeader>
      <div className="review-bar is-saved" role="status">
        <div>
          <strong>Approved report #{report.id}</strong>
          <span>{approved ? `Approved ${approved}. ` : ""}This case's report is final and read-only.</span>
        </div>
      </div>
      <ReportPanel report={report} highlighted={[]} commentSource={report.comment_source} aiCommentAcknowledged />
    </>
  );
}

function DictationCase({ caseDetail, token, onReportSaved, onPhaseChange }) {
  const session = useVoiceSession({ caseId: caseDetail.id, token, onSaved: onReportSaved });
  const showReview = ["review", "saving", "saved"].includes(session.phase);
  const aiCommentPending =
    session.commentSource === "ai" && Boolean(session.report.comments.trim()) && !session.aiCommentAcknowledged;

  useEffect(() => {
    onPhaseChange?.(session.phase);
  }, [onPhaseChange, session.phase]);
  useEffect(() => () => onPhaseChange?.("idle"), [onPhaseChange]);

  return (
    <>
      <CaseHeader caseDetail={caseDetail}>
        <div className="session-status" aria-live="polite">
          <span className={`status-light ${session.connected ? "is-live" : ""}`} />
          <span>{session.status}</span>
        </div>
        <RecordButton
          recording={session.recording}
          disabled={!session.recording && !session.canStart}
          onClick={session.toggleRecording}
        />
      </CaseHeader>
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
    </>
  );
}

export function CaseWorkspace({ caseDetail, token, onReportSaved, onPhaseChange }) {
  if (caseDetail.report) return <ReportedCase caseDetail={caseDetail} />;
  return (
    <DictationCase caseDetail={caseDetail} token={token} onReportSaved={onReportSaved} onPhaseChange={onPhaseChange} />
  );
}
