import React, { useState } from "react";

function NewCaseForm({ onCreate, onCancel }) {
  const [patientName, setPatientName] = useState("");
  const [patientMrn, setPatientMrn] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await onCreate(patientName.trim(), patientMrn.trim());
    } catch (err) {
      setError(err.message || "Could not create the case");
      setBusy(false);
    }
  }

  return (
    <form className="new-case-form" onSubmit={submit} aria-label="New case">
      <label className="form-field">
        <span>Patient name</span>
        <input value={patientName} onChange={(e) => setPatientName(e.target.value)} required maxLength={200} autoFocus />
      </label>
      <label className="form-field">
        <span>MRN <em>(optional)</em></span>
        <input value={patientMrn} onChange={(e) => setPatientMrn(e.target.value)} maxLength={64} />
      </label>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="review-actions">
        <button className="review-button" type="button" onClick={onCancel} disabled={busy}>Cancel</button>
        <button className="review-button is-primary" type="submit" disabled={busy || !patientName.trim()}>
          {busy ? "Creating..." : "Create case"}
        </button>
      </div>
    </form>
  );
}

export function Sidebar({ cases, loading, error, selectedId, onSelect, onCreate }) {
  const [creating, setCreating] = useState(false);

  return (
    <aside className="sidebar" aria-label="Cases">
      <div className="sidebar-heading">
        <h2>Cases</h2>
        {!creating && (
          <button className="review-button is-primary" type="button" onClick={() => setCreating(true)}>+ New case</button>
        )}
      </div>
      {creating && (
        <NewCaseForm
          onCancel={() => setCreating(false)}
          onCreate={async (name, mrn) => {
            const created = await onCreate(name, mrn);
            setCreating(false);
            return created;
          }}
        />
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading ? (
        <p className="sidebar-empty">Loading cases...</p>
      ) : !cases.length ? (
        <p className="sidebar-empty">No cases yet. Create one for each new patient.</p>
      ) : (
        <ul className="case-list">
          {cases.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className={`case-item ${c.id === selectedId ? "is-selected" : ""}`}
                aria-current={c.id === selectedId ? "true" : undefined}
                onClick={() => onSelect(c.id)}
              >
                <span className="case-patient">{c.patient_name}</span>
                <span className="case-meta">
                  <span>{c.case_number}</span>
                  <span className={`case-status is-${c.status}`}>{c.status === "reported" ? "Reported" : "Open"}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
