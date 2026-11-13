import { RiskCheckResult } from "../api";
import { formatMs, formatUsd } from "../format";

/** Each disclosed risk, the MAS guideline passages related to it, and whether a person should look. */
export default function RiskResults({ result }: { result: RiskCheckResult }) {
  return (
    <section className="panel" aria-labelledby="risk-results-title">
      <h2 id="risk-results-title">Risks checked against MAS guidelines</h2>
      <p className="muted">{result.disclaimer}</p>
      <dl className="meta-row">
        <div><dt>Response time</dt><dd>{formatMs(result.latency_ms)}</dd></div>
        <div><dt>Estimated cost</dt><dd>{formatUsd(result.cost_usd)}</dd></div>
      </dl>
      {result.assessments.map((a) => (
        <article key={a.risk.title} className="assessment">
          <header>
            <h3>{a.risk.title}</h3>
            <span className={a.needs_human_review ? "status is-flag" : "status"}>
              {a.needs_human_review ? "Needs human review" : "Covered by guidelines"}
            </span>
          </header>
          <p>{a.assessment}</p>
          {a.related_guidelines.length > 0 ? (
            <ul className="guidelines">
              {a.related_guidelines.map((g) => (
                <li key={g.chunk_id}>
                  <span className="source-title">{g.title}</span>{" "}
                  <span className="muted">page {g.page}{g.heading ? `, ${g.heading}` : ""}</span>
                  <blockquote className="guideline-quote">{g.quote}</blockquote>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No related guideline passage was found.</p>
          )}
          <p className="fineprint">
            Searched for: {a.searches.map((q) => `“${q}”`).join(", ")} ({a.steps_used} {a.steps_used === 1 ? "step" : "steps"})
          </p>
        </article>
      ))}
    </section>
  );
}
