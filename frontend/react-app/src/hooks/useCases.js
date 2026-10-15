import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

// The signed-in doctor's cases and the currently selected case (with report).
export function useCases({ token, onUnauthorized }) {
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [selected, setSelected] = useState(null);

  const handle = useCallback(
    (err) => {
      if (err.status === 401) onUnauthorized?.();
      else setError(err.message);
    },
    [onUnauthorized],
  );

  const refresh = useCallback(async () => {
    try {
      const data = await apiFetch("/cases", { token });
      setCases(data.cases);
      setError("");
    } catch (err) {
      handle(err);
    } finally {
      setLoading(false);
    }
  }, [handle, token]);

  const loadSelected = useCallback(
    async (caseId) => {
      if (caseId == null) {
        setSelected(null);
        return;
      }
      try {
        setSelected(await apiFetch(`/cases/${caseId}`, { token }));
      } catch (err) {
        handle(err);
      }
    },
    [handle, token],
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    setSelected((current) => (current?.id === selectedId ? current : null));
    loadSelected(selectedId);
  }, [loadSelected, selectedId]);

  const createCase = useCallback(
    async (patientName, patientMrn) => {
      const created = await apiFetch("/cases", {
        method: "POST",
        token,
        body: { patient_name: patientName, patient_mrn: patientMrn || null },
      });
      setCases((previous) => [created, ...previous]);
      setSelectedId(created.id);
      return created;
    },
    [token],
  );

  // After a report is approved: refresh the list badge and the case view.
  const reportSaved = useCallback(async () => {
    await Promise.all([refresh(), loadSelected(selectedId)]);
  }, [loadSelected, refresh, selectedId]);

  return { cases, loading, error, selectedId, selected, select: setSelectedId, createCase, reportSaved };
}
