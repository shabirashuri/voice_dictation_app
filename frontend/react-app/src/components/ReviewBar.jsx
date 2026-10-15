import React from "react";

export function ReviewBar({ phase, canApprove, savedReportId, onApprove, onDiscard, onNewSession }) {
  if (phase === "saved")
    return (
      <div className="review-bar is-saved" role="status">
        <div>
          <strong>Report saved</strong>
          <span>{savedReportId != null ? `Saved as report #${savedReportId}.` : "The approved report was saved."}</span>
        </div>
        <button className="review-button is-primary" type="button" onClick={onNewSession}>New session</button>
      </div>
    );

  const saving = phase === "saving";
  return (
    <div className="review-bar" role="region" aria-label="Report review">
      <div>
        <strong>Review before approving</strong>
        <span>
          {canApprove
            ? "Check and edit the fields, then approve to save the report."
            : "Review the AI-generated comment before approving."}
        </span>
      </div>
      <div className="review-actions">
        <button className="review-button" type="button" onClick={onDiscard} disabled={saving}>Discard</button>
        <button className="review-button is-primary" type="button" onClick={onApprove} disabled={!canApprove || saving}>
          {saving ? "Saving..." : "Approve & save"}
        </button>
      </div>
    </div>
  );
}
