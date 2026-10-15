import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installBrowserFakes, jsonResponse, lastSocket } from "../test/fakes";
import { useVoiceSession } from "./useVoiceSession";

const FINAL_REPORT = {
  patient: "John Doe",
  specimen: "Gastric biopsy",
  gross_description: "",
  microscopic_description: "Chronic inactive gastritis.",
  diagnosis: "Chronic inactive gastritis.",
  comments: "AI comment",
  comment_source: "ai",
};

async function startRecording(result) {
  await act(async () => {
    result.current.toggleRecording();
  });
  const socket = lastSocket();
  await act(async () => {
    await socket.open();
  });
  act(() => socket.serverSend({ type: "begin", id: "sess-1" }));
  return socket;
}

async function reachReview(result, report = FINAL_REPORT) {
  const socket = await startRecording(result);
  act(() => result.current.toggleRecording()); // stop
  act(() =>
    socket.serverSend({ type: "state", report, updated_fields: [], is_finished: true, awaiting_review: true }),
  );
  return socket;
}

beforeEach(() => installBrowserFakes());
afterEach(() => vi.unstubAllGlobals());

describe("useVoiceSession", () => {
  it("moves through recording, finalizing and review", async () => {
    const { result } = renderHook(() => useVoiceSession());
    expect(result.current.phase).toBe("idle");

    const socket = await startRecording(result);
    expect(result.current.phase).toBe("recording");
    expect(result.current.editable).toBe(false);

    act(() =>
      socket.serverSend({ type: "state", report: { specimen: "Gastric biopsy" }, updated_fields: ["specimen"] }),
    );
    expect(result.current.report.specimen).toBe("Gastric biopsy");
    expect(result.current.highlighted).toEqual(["specimen"]);

    act(() => result.current.toggleRecording());
    expect(result.current.phase).toBe("finalizing");
    expect(socket.sentTypes()).toContain("stop");

    act(() =>
      socket.serverSend({ type: "state", report: FINAL_REPORT, is_finished: true, awaiting_review: true }),
    );
    expect(result.current.phase).toBe("review");
    expect(result.current.editable).toBe(true);
    expect(result.current.commentSource).toBe("ai");
    expect(result.current.aiCommentAcknowledged).toBe(false);
    expect(result.current.report.diagnosis).toBe("Chronic inactive gastritis.");
  });

  it("ignores edits while recording and applies them in review", async () => {
    const { result } = renderHook(() => useVoiceSession());
    await startRecording(result);
    act(() => result.current.updateDraftField("diagnosis", "Edited"));
    expect(result.current.report.diagnosis).toBe("");
  });

  it("will not approve an unreviewed AI comment", async () => {
    const { result } = renderHook(() => useVoiceSession());
    await reachReview(result);
    await act(async () => {
      await result.current.approveAndSave();
    });
    expect(fetch).not.toHaveBeenCalled();
    expect(result.current.phase).toBe("review");
    expect(result.current.error.code).toBe("save");
  });

  it("saves the edited draft after the AI comment is acknowledged", async () => {
    fetch.mockResolvedValue(jsonResponse(201, { id: 7 }));
    const { result } = renderHook(() => useVoiceSession());
    const socket = await reachReview(result);

    act(() => result.current.updateDraftField("diagnosis", "Chronic gastritis, edited."));
    act(() => result.current.acknowledgeAiComment(true));
    await act(async () => {
      await result.current.approveAndSave();
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, options] = fetch.mock.calls[0];
    expect(url).toMatch(/\/reports$/);
    expect(options.method).toBe("POST");
    const body = JSON.parse(options.body);
    expect(body.session_id).toBe("sess-1");
    expect(body.comment_source).toBe("ai");
    expect(body.report.diagnosis).toBe("Chronic gastritis, edited.");
    expect(body.report).not.toHaveProperty("comment_source");

    expect(result.current.phase).toBe("saved");
    expect(result.current.savedReportId).toBe(7);
    expect(socket.sentTypes()).toContain("close");
    expect(result.current.connected).toBe(false);
  });

  it("editing the AI comment counts as reviewing it but keeps it labelled AI", async () => {
    fetch.mockResolvedValue(jsonResponse(201, { id: 8 }));
    const { result } = renderHook(() => useVoiceSession());
    await reachReview(result);
    act(() => result.current.updateDraftField("comments", "AI comment, checked."));
    expect(result.current.aiCommentAcknowledged).toBe(true);
    await act(async () => {
      await result.current.approveAndSave();
    });
    expect(JSON.parse(fetch.mock.calls[0][1].body).comment_source).toBe("ai");
  });

  it("labels a comment typed during review as the clinician's", async () => {
    fetch.mockResolvedValue(jsonResponse(201, { id: 9 }));
    const { result } = renderHook(() => useVoiceSession());
    await reachReview(result, { ...FINAL_REPORT, comments: "", comment_source: null });
    act(() => result.current.updateDraftField("comments", "Recommend clinical correlation."));
    await act(async () => {
      await result.current.approveAndSave();
    });
    expect(JSON.parse(fetch.mock.calls[0][1].body).comment_source).toBe("doctor");
  });

  it("keeps the draft and shows the server message when saving fails", async () => {
    fetch.mockResolvedValue(jsonResponse(409, { detail: "This dictation was already saved as report #3." }));
    const { result } = renderHook(() => useVoiceSession());
    await reachReview(result, { ...FINAL_REPORT, comment_source: "doctor" });
    act(() => result.current.updateDraftField("patient", "Jane Doe"));
    await act(async () => {
      await result.current.approveAndSave();
    });
    expect(result.current.phase).toBe("review");
    expect(result.current.error).toEqual({ code: "save", message: "This dictation was already saved as report #3." });
    expect(result.current.report.patient).toBe("Jane Doe");
  });

  it("reports a network failure on save as a save error", async () => {
    fetch.mockRejectedValue(new TypeError("Failed to fetch"));
    const { result } = renderHook(() => useVoiceSession());
    await reachReview(result, { ...FINAL_REPORT, comment_source: "doctor" });
    await act(async () => {
      await result.current.approveAndSave();
    });
    expect(result.current.phase).toBe("review");
    expect(result.current.error.code).toBe("save");
  });

  it("shows coded server errors without interrupting recording", async () => {
    const { result } = renderHook(() => useVoiceSession());
    const socket = await startRecording(result);
    act(() => socket.serverSend({ type: "error", code: "validation", error: "not applied" }));
    expect(result.current.error).toEqual({ code: "validation", message: "not applied" });
    expect(result.current.phase).toBe("recording");
    act(() => result.current.dismissError());
    expect(result.current.error).toBeNull();
  });

  it("goes back to idle with an error if the connection drops while recording", async () => {
    const { result } = renderHook(() => useVoiceSession());
    const socket = await startRecording(result);
    act(() => socket.close());
    expect(result.current.phase).toBe("idle");
    expect(result.current.error.code).toBe("connection");
  });

  it("still enters review if the connection drops while finalizing", async () => {
    const { result } = renderHook(() => useVoiceSession());
    const socket = await startRecording(result);
    act(() => socket.serverSend({ type: "state", report: { specimen: "Gastric biopsy" }, updated_fields: [] }));
    act(() => result.current.toggleRecording());
    act(() => socket.close());
    expect(result.current.phase).toBe("review");
    expect(result.current.report.specimen).toBe("Gastric biopsy");
  });

  it("enters review with the last report when finalize fails on the server", async () => {
    const { result } = renderHook(() => useVoiceSession());
    const socket = await startRecording(result);
    act(() => socket.serverSend({ type: "state", report: { diagnosis: "Gastritis" }, updated_fields: [] }));
    act(() => result.current.toggleRecording());
    act(() => socket.serverSend({ type: "error", code: "finalize", error: "could not finalize" }));
    expect(result.current.phase).toBe("review");
    expect(result.current.report.diagnosis).toBe("Gastritis");
    expect(result.current.error.code).toBe("finalize");
  });

  it("ignores a previous session's socket after discard and restart", async () => {
    const { result } = renderHook(() => useVoiceSession());
    const oldSocket = await reachReview(result);
    act(() => result.current.discardReport());
    expect(result.current.phase).toBe("idle");
    expect(result.current.report.patient).toBe("");

    await startRecording(result);
    act(() => oldSocket.serverSend({ type: "state", report: { patient: "Stale" }, updated_fields: [] }));
    act(() => oldSocket.onclose?.());
    expect(result.current.report.patient).toBe("");
    expect(result.current.phase).toBe("recording");
  });

  it("reports a denied microphone and returns to idle", async () => {
    navigator.mediaDevices.getUserMedia.mockRejectedValue(Object.assign(new Error("denied"), { name: "NotAllowedError" }));
    const { result } = renderHook(() => useVoiceSession());
    await act(async () => {
      result.current.toggleRecording();
    });
    await act(async () => {
      await lastSocket().open();
    });
    expect(result.current.phase).toBe("idle");
    expect(result.current.error).toEqual({ code: "microphone", message: "Microphone permission is required" });
  });
});
