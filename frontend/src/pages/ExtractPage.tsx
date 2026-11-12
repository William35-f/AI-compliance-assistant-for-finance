import { ChangeEvent, useEffect, useState } from "react";
import { api, ApiError, ExtractionResult, Figure, RiskCheckResult, SourceInfo } from "../api";
import { formatAsReported, formatMoney, formatMs, formatUsd } from "../format";

const FIELD_LABELS: [keyof Pick<ExtractionResult, "revenue" | "net_profit" | "total_debt">, string][] = [
  ["revenue", "Revenue"],
  ["net_profit", "Net profit (attributable to shareholders)"],
  ["total_debt", "Total debt (borrowings + debt securities)"],
];

function VerifiedBadge({ figure }: { figure: Figure }) {
  if (figure.value === null) return <span className="pill neutral">not found</span>;
  return figure.verified ? (
    <span className="pill ok" title="The number appears on the cited financial-statement page">✓ verified</span>
  ) : (
    <span className="pill warn" title="Could not confirm this number on the cited page">check</span>
  );
}

export default function ExtractPage() {
  const [reports, setReports] = useState<SourceInfo[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ExtractionResult | null>(null);
  const [risk, setRisk] = useState<RiskCheckResult | null>(null);
  const [busy, setBusy] = useState<"extract" | "risk" | null>(null);
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

  async function run<T>(kind: "extract" | "risk", action: () => Promise<T>, done: (value: T) => void) {
    setBusy(kind);
    setError(null);
    try {
      done(await action());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }

  function extract() {
    setRisk(null);
    void run("extract", () => (file ? api.extractUpload(file) : api.extractById(sourceId)), setResult);
  }

  function onFile(e: ChangeEvent<HTMLInputElement>) {
    setFile(e.target.files?.[0] ?? null);
  }

  return (
    <div className="stack">
      <div className="page-intro">
        <h1>Extract from an annual report</h1>
        <p>
          Pulls revenue, net profit, total debt and the main risk disclosures from an SGX-listed company's
          annual report. The model copies numbers as printed; ReguLens converts the units and checks each
          number on the cited statement page.
        </p>
      </div>

      <div className="panel controls">
        <label className="field">
          <span>Sample report</span>
          <select value={sourceId} onChange={(e) => { setSourceId(e.target.value); setFile(null); }}
                  disabled={!!file || reports.length === 0}>
            {reports.length === 0 && <option value="">No reports available</option>}
            {reports.map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}
          </select>
        </label>
        <span className="or">or</span>
        <label className="field">
          <span>Upload a PDF (max 40 MB)</span>
          <input type="file" accept="application/pdf" onChange={onFile} />
        </label>
        <button type="button" className="primary" onClick={extract}
                disabled={busy !== null || (!file && !sourceId)}>
          {busy === "extract" ? "Reading report…" : "Extract"}
        </button>
      </div>

      {error && <div className="answer error">{error}</div>}

      {result && (
        <section className="panel">
          <header className="result-head">
            <div>
              <h2>{result.company}</h2>
              <p className="muted">
                {result.fiscal_year}
                {result.fiscal_year_end ? ` · year ended ${result.fiscal_year_end}` : ""} · {result.currency}
              </p>
            </div>
            <dl className="meta-row">
              <div><dt>Latency</dt><dd>{formatMs(result.latency_ms)}</dd></div>
              <div><dt>Est. cost</dt><dd>{formatUsd(result.cost_usd)}</dd></div>
            </dl>
          </header>

          <div className="table-wrap">
            <table className="figures">
              <thead>
                <tr><th>Field</th><th className="num">Value</th><th>As reported</th><th className="num">Page</th><th>Check</th></tr>
              </thead>
              <tbody>
                {FIELD_LABELS.map(([key, label]) => {
                  const f = result[key];
                  return (
                    <tr key={key}>
                      <th scope="row">{label}</th>
                      <td className="num strong">{formatMoney(f.value, result.currency)}</td>
                      <td className="mono">
                        {key === "total_debt"
                          ? result.total_debt.components.length
                            ? result.total_debt.components.map((c) => formatAsReported(c.as_reported, c.unit_label)).join(" + ")
                            : "no borrowings found"
                          : formatAsReported(f.as_reported, f.unit_label)}
                      </td>
                      <td className="num">{f.page ?? "–"}</td>
                      <td><VerifiedBadge figure={f} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {result.warnings.length > 0 && (
            <ul className="warnings">
              {result.warnings.map((w) => <li key={w}>{w}</li>)}
            </ul>
          )}

          <h3>Key risk disclosures</h3>
          <ul className="risks">
            {result.key_risks.map((r) => (
              <li key={r.title}><strong>{r.title}</strong> <span className="muted">p. {r.page}</span><br />{r.summary}</li>
            ))}
          </ul>

          <button type="button" className="secondary" disabled={busy !== null || result.key_risks.length === 0}
                  onClick={() => void run("risk", () => api.riskCheck(result.key_risks, 3), setRisk)}>
            {busy === "risk" ? "Checking against MAS guidelines…" : "Check top 3 risks against MAS guidelines"}
          </button>
        </section>
      )}

      {risk && (
        <section className="panel">
          <h2>Risk check against MAS guidelines</h2>
          <p className="muted">{risk.disclaimer} · {formatMs(risk.latency_ms)} · est. {formatUsd(risk.cost_usd)}</p>
          {risk.assessments.map((a) => (
            <article key={a.risk.title} className="assessment">
              <header>
                <h3>{a.risk.title}</h3>
                <span className={a.needs_human_review ? "pill warn" : "pill ok"}>
                  {a.needs_human_review ? "Needs human review" : "Covered by guidelines"}
                </span>
              </header>
              <p>{a.assessment}</p>
              {a.related_guidelines.length > 0 && (
                <ul className="guidelines">
                  {a.related_guidelines.map((g) => (
                    <li key={g.chunk_id}>
                      <span className="source-title">{g.title}</span> <span className="muted">p. {g.page}{g.heading ? ` · ${g.heading}` : ""}</span>
                      <blockquote className="source-quote">“{g.quote}”</blockquote>
                    </li>
                  ))}
                </ul>
              )}
              <p className="fineprint">Searches: {a.searches.join(" → ")} · {a.steps_used} step(s)</p>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
