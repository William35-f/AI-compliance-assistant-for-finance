import { useEffect, useState } from "react";
import { api, ApiError, EvalSnapshot, StatsResponse } from "../api";
import { formatMs, formatRate, formatUsd } from "../format";

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className="tile-value">{value}</span>
      {hint && <span className="tile-hint">{hint}</span>}
    </div>
  );
}

const EVAL_ROWS: [string, string, (v: number | null) => string][] = [
  ["retrieval_hit_rate", "Retrieval hit@5", formatRate],
  ["mrr", "Mean reciprocal rank", (v) => (v === null ? "–" : v.toFixed(3))],
  ["answer_correctness", "Answer correctness (LLM judge)", formatRate],
  ["citation_accuracy", "Citation accuracy", formatRate],
  ["oos_refusal_rate", "Out-of-scope refusal rate", formatRate],
  ["false_refusal_rate", "False refusals (in-scope)", formatRate],
  ["latency_p50_ms", "Latency p50", formatMs],
  ["latency_p95_ms", "Latency p95", formatMs],
  ["avg_cost_usd", "Avg est. cost / query", formatUsd],
];

const RETRIEVAL_KEYS = new Set(["retrieval_hit_rate", "mrr"]);

function EvalTable({ title, snapshot }: { title: string; snapshot: EvalSnapshot | null }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {!snapshot ? (
        <p className="muted">No run recorded yet.</p>
      ) : (
        <>
          <p className="muted">
            {String(snapshot.metrics.questions ?? "?")} questions, {String(snapshot.config.mode)} search on
            the {String(snapshot.config.index)} index. Run <code>{snapshot.run}</code>.
          </p>
          <div className="table-wrap">
            <table className="figures">
              <tbody>
                {EVAL_ROWS.filter(([key]) => snapshot.metrics[key] !== null && snapshot.metrics[key] !== undefined)
                  // A retrieval-only run never answers or refuses, so only its search metrics mean anything.
                  .filter(([key]) => !snapshot.config.retrieval_only || RETRIEVAL_KEYS.has(key))
                  .map(([key, label, fmt]) => (
                    <tr key={key}><th scope="row">{label}</th><td className="num strong">{fmt(snapshot.metrics[key] ?? null)}</td></tr>
                  ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

export default function StatsPage() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.stats().then(setStats).catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load"));
  }, []);

  if (error) return <p className="error-box" role="alert">{error}</p>;
  if (!stats) return <p className="muted">Loading stats…</p>;

  const u = stats.usage;
  return (
    <div className="stack">
      <div className="page-intro">
        <h1>Stats and evals</h1>
        <p>Live usage of this deployment (evaluation traffic excluded) and the latest measured evaluation scores.</p>
      </div>
      <div className="tiles">
        <Tile label="Questions answered" value={u.queries.toLocaleString()} />
        <Tile label="Typical response time" value={formatMs(u.latency_p50_ms)} hint="median (p50)" />
        <Tile label="Slow response time" value={formatMs(u.latency_p95_ms)} hint="95th percentile" />
        <Tile label="Average estimated cost" value={formatUsd(u.avg_cost_usd)} hint="at paid-tier prices" />
        <Tile label="Refused" value={u.queries ? formatRate(u.refused / u.queries) : "–"} hint="no supporting source" />
        <Tile label="Cache hits" value={u.queries ? formatRate(u.cached / u.queries) : "–"} />
      </div>
      <div className="two-col">
        <EvalTable title="Latest full evaluation" snapshot={stats.latest_eval} />
        <EvalTable title="Latest retrieval evaluation" snapshot={stats.latest_retrieval_eval} />
      </div>
      <p className="fineprint">
        Rate limits: {Object.entries(stats.rate_limits).map(([k, v]) => `${k} ${v}`).join(", ")}.
      </p>
    </div>
  );
}
