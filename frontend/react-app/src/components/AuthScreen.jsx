import React, { useState } from "react";

export function AuthScreen({ onLogin, onSignup }) {
  const [mode, setMode] = useState("login");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const signingUp = mode === "signup";

  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (signingUp) await onSignup(fullName.trim(), email.trim(), password);
      else await onLogin(email.trim(), password);
    } catch (err) {
      setError(err.message || "Something went wrong");
      setBusy(false);
    }
  }

  function switchMode(next) {
    setMode(next);
    setError("");
  }

  return (
    <div className="auth-shell">
      <form className="auth-card panel" onSubmit={submit} aria-labelledby="auth-title">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">PR</div>
          <div><div className="brand-name">Pathology Report</div><div className="brand-caption">AI-assisted dictation</div></div>
        </div>
        <h1 id="auth-title" className="auth-title">{signingUp ? "Create your account" : "Sign in"}</h1>
        <div className="auth-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={!signingUp} className={!signingUp ? "is-active" : ""} onClick={() => switchMode("login")}>Sign in</button>
          <button type="button" role="tab" aria-selected={signingUp} className={signingUp ? "is-active" : ""} onClick={() => switchMode("signup")}>Sign up</button>
        </div>
        {signingUp && (
          <label className="form-field">
            <span>Full name</span>
            <input value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" required maxLength={200} />
          </label>
        )}
        <label className="form-field">
          <span>Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
        </label>
        <label className="form-field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={signingUp ? "new-password" : "current-password"}
            required
            minLength={signingUp ? 8 : undefined}
          />
          {signingUp && <small>At least 8 characters.</small>}
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="review-button is-primary auth-submit" type="submit" disabled={busy}>
          {busy ? "Please wait..." : signingUp ? "Create account" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
