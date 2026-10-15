import React, { useCallback, useRef } from "react";
import { AuthScreen } from "./components/AuthScreen";
import { CaseWorkspace } from "./components/CaseWorkspace";
import { Sidebar } from "./components/Sidebar";
import { useAuth } from "./hooks/useAuth";
import { useCases } from "./hooks/useCases";

// Phases in which leaving the case would throw away an unsaved dictation.
const BUSY_PHASES = ["connecting", "recording", "finalizing", "review", "saving"];

function SignedInApp({ auth }) {
  const cases = useCases({ token: auth.token, onUnauthorized: auth.signOut });
  const phaseRef = useRef("idle");
  const onPhaseChange = useCallback((phase) => {
    phaseRef.current = phase;
  }, []);

  const confirmLeave = () =>
    !BUSY_PHASES.includes(phaseRef.current) ||
    window.confirm("Leave this case? The current dictation has not been saved and will be discarded.");

  const selectCase = (id) => {
    if (id !== cases.selectedId && confirmLeave()) cases.select(id);
  };
  const createCase = async (name, mrn) => {
    if (!confirmLeave()) throw new Error("Finish or discard the current dictation first.");
    return cases.createCase(name, mrn);
  };
  const signOut = () => {
    if (confirmLeave()) auth.signOut();
  };

  const loadingSelected = cases.selectedId != null && cases.selected?.id !== cases.selectedId;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">PR</div>
          <div><div className="brand-name">Pathology Report</div><div className="brand-caption">AI-assisted dictation</div></div>
        </div>
        <div className="user-menu">
          <span>{auth.user?.full_name}</span>
          <button className="review-button" type="button" onClick={signOut}>Sign out</button>
        </div>
      </header>
      <div className="layout">
        <Sidebar
          cases={cases.cases}
          loading={cases.loading}
          error={cases.error}
          selectedId={cases.selectedId}
          onSelect={selectCase}
          onCreate={createCase}
        />
        <main className="workspace">
          {cases.selectedId == null ? (
            <div className="empty-state workspace-empty">
              <p>No case selected</p>
              <span>Select a case, or create a new case for each new patient.</span>
            </div>
          ) : loadingSelected ? (
            <div className="empty-state workspace-empty"><p>Loading case...</p></div>
          ) : (
            <CaseWorkspace
              key={cases.selected.id}
              caseDetail={cases.selected}
              token={auth.token}
              onReportSaved={cases.reportSaved}
              onPhaseChange={onPhaseChange}
            />
          )}
        </main>
      </div>
    </div>
  );
}

export default function App() {
  const auth = useAuth();
  if (auth.status === "checking")
    return <div className="auth-shell"><p className="intro-copy">Loading...</p></div>;
  if (auth.status !== "signed-in") return <AuthScreen onLogin={auth.login} onSignup={auth.signup} />;
  return <SignedInApp auth={auth} />;
}
