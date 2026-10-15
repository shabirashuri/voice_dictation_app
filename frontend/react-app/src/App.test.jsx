import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { installBrowserFakes, lastSocket, routeFetch } from "./test/fakes";

const USER = { id: 1, email: "doc@example.com", full_name: "Dr. House", created_at: "2026-10-15T10:00:00Z" };
const OPEN_CASE = {
  id: 1, case_number: "C-2026-00001", patient_name: "John Doe", patient_mrn: "MRN-1",
  created_at: "2026-10-15T10:00:00Z", status: "open", report_id: null,
};
const REPORTED_CASE = {
  id: 2, case_number: "C-2026-00002", patient_name: "Jane Roe", patient_mrn: null,
  created_at: "2026-10-15T09:00:00Z", status: "reported", report_id: 9,
};
const SAVED_REPORT = {
  id: 9, case_id: 2, case_number: "C-2026-00002", session_id: "s", patient: "Jane Roe",
  specimen: "Skin punch biopsy", gross_description: "", microscopic_description: "",
  diagnosis: "Seborrheic keratosis.", comments: "AI comment", comment_source: "ai",
  status: "approved", created_at: "2026-10-15T09:30:00Z", updated_at: "2026-10-15T09:30:00Z",
  approved_at: "2026-10-15T09:30:00Z",
};

const ROUTES = {
  "GET /auth/me": [200, USER],
  "GET /cases": [200, { cases: [OPEN_CASE, REPORTED_CASE], total: 2 }],
  "GET /cases/1": [200, { ...OPEN_CASE, report: null }],
  "GET /cases/2": [200, { ...REPORTED_CASE, report: SAVED_REPORT }],
};

beforeEach(() => {
  installBrowserFakes();
  window.localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function renderSignedIn(routes = ROUTES) {
  window.localStorage.setItem("pvr.token", "tok");
  routeFetch(routes);
  render(<App />);
  await screen.findByText("Dr. House");
}

async function openCase(name) {
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(name) }));
  await screen.findByRole("heading", { level: 1, name });
}

async function dictateToReview(report) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
  });
  const socket = lastSocket();
  await act(async () => {
    await socket.open();
  });
  act(() => fireEvent.click(screen.getByRole("button", { name: /stop session/i })));
  act(() => socket.serverSend({ type: "state", report, is_finished: true, awaiting_review: true }));
  return socket;
}

describe("signing in", () => {
  it("shows the sign-in screen when signed out and signs in", async () => {
    routeFetch({ ...ROUTES, "POST /auth/login": [200, { access_token: "new-tok", token_type: "bearer", expires_in: 60, user: USER }] });
    render(<App />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "doc@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "correct-horse" } });
    await act(async () => {
      fireEvent.submit(screen.getByLabelText("Email").closest("form"));
    });
    expect(await screen.findByText("Dr. House")).toBeTruthy();
    expect(window.localStorage.getItem("pvr.token")).toBe("new-tok");
    const login = fetch.mock.calls.find(([url]) => url.endsWith("/auth/login"));
    expect(JSON.parse(login[1].body)).toEqual({ email: "doc@example.com", password: "correct-horse" });
  });

  it("shows the server's message on a failed sign-in", async () => {
    routeFetch({ "POST /auth/login": [401, { detail: "Incorrect email or password" }] });
    render(<App />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "doc@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong" } });
    await act(async () => {
      fireEvent.submit(screen.getByLabelText("Email").closest("form"));
    });
    expect((await screen.findByRole("alert")).textContent).toBe("Incorrect email or password");
  });

  it("creates an account from the sign-up tab", async () => {
    routeFetch({ ...ROUTES, "POST /auth/signup": [201, { access_token: "t", token_type: "bearer", expires_in: 60, user: USER }] });
    render(<App />);
    fireEvent.click(screen.getByRole("tab", { name: "Sign up" }));
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Dr. House" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "doc@example.com" } });
    fireEvent.change(screen.getByLabelText(/Password/), { target: { value: "correct-horse" } });
    await act(async () => {
      fireEvent.submit(screen.getByLabelText("Email").closest("form"));
    });
    expect(await screen.findByText("Dr. House")).toBeTruthy();
    const signup = fetch.mock.calls.find(([url]) => url.endsWith("/auth/signup"));
    expect(JSON.parse(signup[1].body)).toEqual({ full_name: "Dr. House", email: "doc@example.com", password: "correct-horse" });
  });

  it("returns to sign-in when the stored token is rejected", async () => {
    window.localStorage.setItem("pvr.token", "expired");
    routeFetch({ "GET /auth/me": [401, { detail: "Not signed in or session expired" }] });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(window.localStorage.getItem("pvr.token")).toBeNull();
  });
});

describe("cases", () => {
  it("lists the doctor's cases with their status", async () => {
    await renderSignedIn();
    const open = await screen.findByRole("button", { name: /John Doe/ });
    expect(open.textContent).toContain("C-2026-00001");
    expect(open.textContent).toContain("Open");
    expect(screen.getByRole("button", { name: /Jane Roe/ }).textContent).toContain("Reported");
  });

  it("creates a case for a new patient and opens it", async () => {
    const created = { ...OPEN_CASE, id: 3, case_number: "C-2026-00003", patient_name: "New Patient", patient_mrn: null };
    await renderSignedIn({
      ...ROUTES,
      "POST /cases": [201, created],
      "GET /cases/3": [200, { ...created, report: null }],
    });
    fireEvent.click(screen.getByRole("button", { name: "+ New case" }));
    fireEvent.change(screen.getByLabelText("Patient name"), { target: { value: "New Patient" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Create case" }));
    });
    expect(await screen.findByRole("heading", { level: 1, name: "New Patient" })).toBeTruthy();
    const post = fetch.mock.calls.find(([url, o]) => url.endsWith("/cases") && o.method === "POST");
    expect(JSON.parse(post[1].body)).toEqual({ patient_name: "New Patient", patient_mrn: null });
    expect(post[1].headers.Authorization).toBe("Bearer tok");
  });

  it("shows a reported case's saved report read-only, without recording", async () => {
    await renderSignedIn();
    await openCase("Jane Roe");
    expect(screen.getByText(/Approved report #9/)).toBeTruthy();
    expect(screen.getByLabelText("Diagnosis").value).toBe("Seborrheic keratosis.");
    expect(screen.getByLabelText("Diagnosis").readOnly).toBe(true);
    expect(screen.queryByRole("button", { name: /start session/i })).toBeNull();
    expect(screen.getByText(/AI-generated · reviewed/)).toBeTruthy();
  });

  it("dictates in an open case, authenticating the socket for that case", async () => {
    await renderSignedIn();
    await openCase("John Doe");
    const socket = await dictateToReview({ diagnosis: "Gastritis", comments: "AI comment", comment_source: "ai" });
    expect(socket.sent[0]).toEqual({ type: "auth", token: "tok", case_id: 1 });

    const approve = screen.getByRole("button", { name: /approve & save/i });
    expect(approve.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/I have reviewed this AI-generated comment/));
    expect(approve.disabled).toBe(false);
  });

  it("asks before leaving a case with an unsaved dictation", async () => {
    await renderSignedIn();
    await openCase("John Doe");
    await dictateToReview({ diagnosis: "Gastritis", comments: "", comment_source: null });
    const confirm = vi.fn().mockReturnValue(false);
    vi.stubGlobal("confirm", confirm);
    fireEvent.click(screen.getByRole("button", { name: /Jane Roe/ }));
    expect(confirm).toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("John Doe");
    expect(screen.getByLabelText("Diagnosis").value).toBe("Gastritis");
  });

  it("shows the saved report after approving", async () => {
    let saved = false;
    const savedOpenCase = { ...SAVED_REPORT, id: 10, case_id: 1, case_number: "C-2026-00001", diagnosis: "Gastritis", comments: "", comment_source: null };
    await renderSignedIn({
      ...ROUTES,
      "POST /cases/1/report": () => {
        saved = true;
        return [201, savedOpenCase];
      },
      "GET /cases/1": () => [200, { ...OPEN_CASE, status: saved ? "reported" : "open", report: saved ? savedOpenCase : null }],
    });
    await openCase("John Doe");
    await dictateToReview({ diagnosis: "Gastritis", comments: "", comment_source: null });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /approve & save/i }));
    });
    expect(await screen.findByText(/Approved report #10/)).toBeTruthy();
    expect(screen.getByLabelText("Diagnosis").readOnly).toBe(true);
  });
});
