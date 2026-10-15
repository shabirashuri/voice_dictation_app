import React from "react";

const REPORT_FIELDS = [
  { key: "patient", label: "Patient", type: "textarea", compact: true },
  { key: "specimen", label: "Specimen", type: "textarea", compact: true },
  { key: "gross_description", label: "Gross description", type: "textarea" },
  {
    key: "microscopic_description",
    label: "Microscopic description",
    type: "textarea",
  },
  { key: "diagnosis", label: "Diagnosis", type: "textarea" },
  { key: "comments", label: "Comments", type: "textarea" },
];

function isPopulated(value) {
  return Boolean(value && String(value).trim());
}

function CommentSourceBadge({ source, acknowledged }) {
  if (source === "ai")
    return (
      <span className={`source-badge is-ai ${acknowledged ? "is-reviewed" : ""}`}>
        {acknowledged ? "AI-generated · reviewed" : "AI-generated · review required"}
      </span>
    );
  if (source === "doctor") return <span className="source-badge">Clinician</span>;
  return null;
}

export function ReportPanel({
  report,
  highlighted,
  editable = false,
  onFieldChange,
  commentSource,
  aiCommentAcknowledged,
  onAcknowledgeAiComment,
}) {
  const highlightedFields = new Set(
    (highlighted || []).map((field) =>
      typeof field === "string" ? field : field.target_section,
    ),
  );
  const completeCount = REPORT_FIELDS.filter(({ key }) =>
    isPopulated(report[key]),
  ).length;
  return (
    <section className="report-panel panel" aria-labelledby="report-heading">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">
            {editable ? "Clinician review" : "Structured output"}
          </p>
          <h2 id="report-heading">Report fields</h2>
        </div>
        <span className="field-count">{completeCount}/6 complete</span>
      </div>
      <div className="report-fields">
        {REPORT_FIELDS.map(({ key, label, type, compact }) => {
          const populated = isPopulated(report[key]);
          const Field = type === "textarea" ? "textarea" : "input";
          const isComments = key === "comments";
          return (
            <div
              className={`report-field ${compact ? "is-compact" : ""} ${highlightedFields.has(key) ? "is-updated" : ""} ${editable ? "is-editable" : ""}`}
              key={key}
            >
              <label className="field-label" htmlFor={`field-${key}`}>
                <span>{label}</span>
                {isComments && populated ? (
                  <CommentSourceBadge
                    source={commentSource ?? report.comment_source}
                    acknowledged={aiCommentAcknowledged}
                  />
                ) : (
                  <span
                    className={`field-state ${populated ? "is-complete" : ""}`}
                  >
                    {populated ? "Complete" : "Pending"}
                  </span>
                )}
              </label>
              <Field
                id={`field-${key}`}
                aria-label={label}
                value={report[key] || ""}
                readOnly={!editable}
                onChange={
                  editable
                    ? (event) => onFieldChange?.(key, event.target.value)
                    : undefined
                }
                rows={compact ? 1 : type === "textarea" ? 4 : undefined}
                placeholder={
                  editable
                    ? `Add ${label.toLowerCase()}...`
                    : `Waiting for ${label.toLowerCase()}...`
                }
              />
              {isComments && editable && commentSource === "ai" && populated && (
                <label className="ack-row">
                  <input
                    type="checkbox"
                    checked={aiCommentAcknowledged}
                    onChange={(event) =>
                      onAcknowledgeAiComment?.(event.target.checked)
                    }
                  />
                  <span>I have reviewed this AI-generated comment</span>
                </label>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
