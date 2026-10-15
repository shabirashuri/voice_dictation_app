import { useCallback, useEffect, useState } from "react";
import { ApiError, apiFetch } from "../lib/api";

const TOKEN_KEY = "pvr.token";

function readToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeToken(token) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage blocked: the session just won't survive a reload
  }
}

// status: "checking" (validating a stored token) | "signed-out" | "signed-in"
export function useAuth() {
  const [token, setToken] = useState(() => readToken());
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState(() => (readToken() ? "checking" : "signed-out"));

  const signOut = useCallback(() => {
    writeToken(null);
    setToken(null);
    setUser(null);
    setStatus("signed-out");
  }, []);

  const accept = useCallback((data) => {
    writeToken(data.access_token);
    setToken(data.access_token);
    setUser(data.user);
    setStatus("signed-in");
  }, []);

  useEffect(() => {
    if (status !== "checking" || !token) return;
    let cancelled = false;
    apiFetch("/auth/me", { token })
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        setStatus("signed-in");
      })
      .catch((error) => {
        if (cancelled) return;
        // Only a rejected token signs out; keep it if the server is just down.
        if (error instanceof ApiError && error.status === 401) signOut();
        else setStatus("signed-out");
      });
    return () => {
      cancelled = true;
    };
  }, [signOut, status, token]);

  const login = useCallback(
    async (email, password) => accept(await apiFetch("/auth/login", { method: "POST", body: { email, password } })),
    [accept],
  );

  const signup = useCallback(
    async (fullName, email, password) =>
      accept(await apiFetch("/auth/signup", { method: "POST", body: { full_name: fullName, email, password } })),
    [accept],
  );

  return { token, user, status, login, signup, signOut };
}
