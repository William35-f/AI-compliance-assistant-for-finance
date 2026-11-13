import { FormEvent, useEffect, useState } from "react";
import { api, ApiError, RiskCheckResult, SourceInfo } from "../api";
import RiskResults from "../components/RiskResults";

type Mode = "report" | "own";

export default function RiskPage() {
  const [mode, setMode] = useState<Mode>("report");
  const [reports, setReports] = useState<SourceInfo[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [result, setResult] = useState<RiskCheckResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.sources("annual_report")
      .then((list) => {
        const available = list.filter((s) => s.downloaded);
        setReports(available);
        if (available.length) setSourceId(available[0].id);
      })
      .catch(() => setReports([]));
  }, []);

  const ready = mode === "report" ? !!sourceId : title.trim().length > 2 && description.trim().length > 10;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(mode === "report"
        ? await api.riskCheckReport(sourceId, 3)
        : await api.riskCheck([{ title: title.trim(), summary: description.trim(), page: 0 }], 1));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The risk check couldn't be run. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="page-intro">
        <h1>Risk check</h1>
        <p>
          For each risk a company discloses, ReguLens finds the MAS guideline passages that cover it and
          flags the ones a person should review. It points you to the rules; it doesn't decide compliance.
        </p>
      </div>

      <form className="panel risk-form" onSubmit={onSubmit}>
        <fieldset className="choice">
          <legend>What to check</legend>
          <label>
            <input type="radio" name="mode" value="report" checked={mode === "report"}
                   onChange={() => setMode("report")} />
            The top 3 risks in an annual report
          </label>
          <label>
            <input type="radio" name="mode" value="own" checked={mode === "own"}
                   onChange={() => setMode("own")} />
            A risk I describe
          </label>
        </fieldset>

        {mode === "report" ? (
          <label className="field">
            <span>Annual report</span>
            <select value={sourceId} onChange={(e) => setSourceId(e.target.value)} disabled={reports.length === 0}>
              {reports.length === 0 && <option value="">No reports available</option>}
              {reports.map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}
            </select>
          </label>
        ) : (
          <>
            <label className="field">
              <span>Risk</span>
              <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120}
                     placeholder="e.g. Third-party technology outages" />
            </label>
            <label className="field">
              <span>What the company says about it</span>
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3}
                        maxLength={1000}
                        placeholder="e.g. The bank relies on cloud providers for core banking; an outage could disrupt payments." />
            </label>
          </>
        )}

        <div>
          <button type="submit" className="button-primary" disabled={!ready || busy}>
            {busy ? "Checking against MAS guidelines…" : "Check against MAS guidelines"}
          </button>
          {busy && mode === "report" && (
            <p className="hint" role="status">Reading the report first. This can take a minute.</p>
          )}
        </div>
      </form>

      {error && <p className="error-box" role="alert">{error}</p>}
      {result && <RiskResults result={result} />}
    </div>
  );
}
