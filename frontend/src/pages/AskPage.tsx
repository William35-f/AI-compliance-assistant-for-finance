import { FormEvent, Fragment, useEffect, useRef, useState } from "react";
import { api, ApiError, AskResponse, Citation } from "../api";
import { formatMs, formatUsd } from "../format";

const EXAMPLES = [
  "How quickly must a financial institution notify MAS of a severe disruption?",
  "Which accounts need multi-factor authentication under the cyber hygiene notice?",
  "When do the AI risk management guidelines take effect?",
  "How often should internet-facing systems be penetration tested?",
];

interface Turn {
  id: number;
  question: string;
  response?: AskResponse;
  error?: string;
}

/** Split "Claim one. [1][2] Claim two. [3]" into text and clickable markers. */
function AnswerText({ text, citations, active, onSelect }: {
  text: string;
  citations: Citation[];
  active: number | null;
  onSelect: (marker: number) => void;
}) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="answer-text">
      {parts.map((part, i) => {
        const match = part.match(/^\[(\d+)\]$/);
        if (!match) return <Fragment key={i}>{part}</Fragment>;
        const marker = Number(match[1]);
        const citation = citations.find((c) => c.marker === marker);
        return (
          <button key={i} type="button" className={active === marker ? "cite-chip active" : "cite-chip"}
                  onClick={() => onSelect(marker)}
                  title={citation ? `${citation.title}, page ${citation.page}` : undefined}>
            {marker}
          </button>
        );
      })}
    </p>
  );
}

function CitationCard({ citation, active, onSelect }: {
  citation: Citation;
  active: boolean;
  onSelect: () => void;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [active]);
  const pages = citation.page === citation.page_end ? `p. ${citation.page}` : `pp. ${citation.page}–${citation.page_end}`;
  return (
    <button ref={ref} type="button" className={active ? "source-card active" : "source-card"} onClick={onSelect}>
      <span className="source-head">
        <span className="source-marker">{citation.marker}</span>
        <span className="source-title">{citation.title}</span>
      </span>
      <span className="source-meta">
        {pages}
        {citation.heading ? ` · ${citation.heading}` : ""}
      </span>
      <blockquote className="source-quote">“{citation.quote}”</blockquote>
      <span className={citation.quote_verified ? "verify ok" : "verify warn"}>
        {citation.quote_verified ? "✓ Quote found verbatim in source" : "≈ Closest sentence in the cited passage"}
      </span>
    </button>
  );
}

export default function AskPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<{ turn: number; marker: number } | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  async function submit(text: string) {
    const q = text.trim();
    if (q.length < 3 || busy) return;
    const id = Date.now();
    setTurns((t) => [...t, { id, question: q }]);
    setQuestion("");
    setBusy(true);
    try {
      const response = await api.ask(q);
      setTurns((t) => t.map((turn) => (turn.id === id ? { ...turn, response } : turn)));
      if (response.citations.length) setSelected({ turn: id, marker: response.citations[0].marker });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Something went wrong.";
      setTurns((t) => t.map((turn) => (turn.id === id ? { ...turn, error: message } : turn)));
    } finally {
      setBusy(false);
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit(question);
  }

  const activeTurn = turns.find((t) => t.id === selected?.turn);

  return (
    <div className="ask-layout">
      <section className="conversation" aria-live="polite">
        <div className="page-intro">
          <h1>Ask the MAS guidelines</h1>
          <p>
            Answers use only passages retrieved from 10 MAS publications. Every claim carries a numbered
            citation; select a number to see the exact quote and page.
          </p>
        </div>

        {turns.length === 0 && (
          <div className="examples">
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" className="example" onClick={() => void submit(ex)}>
                {ex}
              </button>
            ))}
          </div>
        )}

        {turns.map((turn) => (
          <article key={turn.id} className="turn">
            <p className="question">{turn.question}</p>
            {!turn.response && !turn.error && <div className="answer loading">Searching the guidelines…</div>}
            {turn.error && <div className="answer error">{turn.error}</div>}
            {turn.response && (
              <div className={turn.response.refused ? "answer refused" : "answer"}>
                <AnswerText
                  text={turn.response.answer}
                  citations={turn.response.citations}
                  active={selected?.turn === turn.id ? selected.marker : null}
                  onSelect={(marker) => setSelected({ turn: turn.id, marker })}
                />
                {turn.response.refused && (
                  <p className="refusal-note">
                    No passage in the indexed MAS documents answers this, so ReguLens did not guess.
                  </p>
                )}
                <dl className="meta-row">
                  <div><dt>Latency</dt><dd>{formatMs(turn.response.latency_ms)}</dd></div>
                  <div><dt>Tokens</dt><dd>{turn.response.tokens.input + turn.response.tokens.output}</dd></div>
                  <div><dt>Est. cost</dt><dd>{formatUsd(turn.response.cost_usd)}</dd></div>
                  {turn.response.cached && <div><dt>Cache</dt><dd>hit</dd></div>}
                </dl>
              </div>
            )}
          </article>
        ))}
        <div ref={bottomRef} />

        <form className="ask-form" onSubmit={onSubmit}>
          <label htmlFor="question" className="sr-only">Your question</label>
          <textarea
            id="question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit(question);
              }
            }}
            placeholder="e.g. What must a bank do when a sanctions screening hit occurs?"
            rows={2}
            maxLength={1000}
          />
          <button type="submit" className="primary" disabled={busy || question.trim().length < 3}>
            {busy ? "Asking…" : "Ask"}
          </button>
        </form>
        <p className="fineprint">{turns.at(-1)?.response?.disclaimer ??
          "ReguLens summarises MAS publications for research. Not legal or regulatory advice."}</p>
      </section>

      <aside className="sources-panel" aria-label="Sources for the selected answer">
        <h2>Sources</h2>
        {!activeTurn?.response?.citations.length ? (
          <p className="muted">Citations for the selected answer appear here.</p>
        ) : (
          activeTurn.response.citations.map((c) => (
            <CitationCard key={c.marker} citation={c} active={selected?.marker === c.marker}
                          onSelect={() => setSelected({ turn: activeTurn.id, marker: c.marker })} />
          ))
        )}
      </aside>
    </div>
  );
}
