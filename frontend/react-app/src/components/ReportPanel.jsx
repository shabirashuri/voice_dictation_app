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

export function ReportPanel({ report, highlighted }) {
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
          <p className="section-kicker">Structured output</p>
          <h2 id="report-heading">Report fields</h2>
        </div>
        <span className="field-count">{completeCount}/6 complete</span>
      </div>
      <div className="report-fields">
        {REPORT_FIELDS.map(({ key, label, type, compact }) => {
          const populated = isPopulated(report[key]);
          const Field = type === "textarea" ? "textarea" : "input";
          return (
            <label
              className={`report-field ${compact ? "is-compact" : ""} ${highlightedFields.has(key) ? "is-updated" : ""}`}
              key={key}
            >
              <span className="field-label">
                <span>{label}</span>
                <span
                  className={`field-state ${populated ? "is-complete" : ""}`}
                >
                  {populated ? "Complete" : "Pending"}
                </span>
              </span>
              <Field
                value={report[key] || ""}
                readOnly
                rows={compact ? 1 : type === "textarea" ? 4 : undefined}
                aria-label={label}
                placeholder={`Waiting for ${label.toLowerCase()}...`}
              />
            </label>
          );
        })}
      </div>
    </section>
  );
}
