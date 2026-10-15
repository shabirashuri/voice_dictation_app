import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "./App";
import { installBrowserFakes, lastSocket } from "./test/fakes";

beforeEach(() => installBrowserFakes());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function reachReview(report) {
  render(<App />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
  });
  const socket = lastSocket();
  await act(async () => {
    await socket.open();
  });
  act(() => fireEvent.click(screen.getByRole("button", { name: /stop session/i })));
  act(() => socket.serverSend({ type: "state", report, is_finished: true, awaiting_review: true }));
}

it("requires the AI comment to be reviewed before Approve is enabled", async () => {
  await reachReview({ diagnosis: "Gastritis", comments: "AI comment", comment_source: "ai" });

  const approve = screen.getByRole("button", { name: /approve & save/i });
  expect(approve.disabled).toBe(true);
  expect(screen.getByText(/AI-generated · review required/)).toBeTruthy();

  fireEvent.click(screen.getByLabelText(/I have reviewed this AI-generated comment/));
  expect(approve.disabled).toBe(false);
  expect(screen.getByText(/AI-generated · reviewed/)).toBeTruthy();
});

it("labels a dictated comment as the clinician's and allows approval", async () => {
  await reachReview({ diagnosis: "Gastritis", comments: "Recommend correlation.", comment_source: "doctor" });
  expect(screen.getByText("Clinician")).toBeTruthy();
  expect(screen.queryByLabelText(/I have reviewed this AI-generated comment/)).toBeNull();
  expect(screen.getByRole("button", { name: /approve & save/i }).disabled).toBe(false);
});

it("makes fields editable only in review and disables recording meanwhile", async () => {
  await reachReview({ diagnosis: "Gastritis", comments: "", comment_source: null });
  const diagnosis = screen.getByLabelText("Diagnosis");
  expect(diagnosis.readOnly).toBe(false);
  fireEvent.change(diagnosis, { target: { value: "Chronic gastritis" } });
  expect(diagnosis.value).toBe("Chronic gastritis");
  expect(screen.getByRole("button", { name: /start session/i }).disabled).toBe(true);
});

it("asks before discarding a report", async () => {
  await reachReview({ diagnosis: "Gastritis", comments: "", comment_source: null });
  const confirm = vi.fn().mockReturnValue(false);
  vi.stubGlobal("confirm", confirm);
  fireEvent.click(screen.getByRole("button", { name: /discard/i }));
  expect(confirm).toHaveBeenCalled();
  expect(screen.getByLabelText("Diagnosis").value).toBe("Gastritis");
});
