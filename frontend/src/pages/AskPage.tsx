import { FormEvent, Fragment, useEffect, useRef, useState } from "react";
import { api, ApiError, AskResponse, Citation, SourceInfo } from "../api";
import SourcePanel from "../components/SourcePanel";
import { formatMs, formatUsd } from "../format";

const EXAMPLES = [
  "How quickly must a financial institution notify MAS of a severe disruption?",
  "Which accounts need multi-factor authentication under the cyber hygiene notice?",
  "When do the AI risk management guidelines take effect?",
  "How often should internet-facing systems be penetration tested?",
];

const STACKED = "(max-width: 960px)";

interface Turn {
  id: number;
  question: string;
  response?: AskResponse;
  error?: string;
}

interface Claim {
  text: string;
  markers: number[];
}

/** "Claim one. [1][2] Claim two. [3]" -> [{text: "Claim one.", markers: [1, 2]}, ...] */
function splitClaims(answer: string): Claim[] {
  const claims: Claim[] = [];
  const pattern = /([^[]+?)\s*((?:\[\d+\])+)/g;
  let match: RegExpExecArray | null;
  let consumed = 0;
  while ((match = pattern.exec(answer)) !== null) {
    claims.push({
      text: match[1].trim(),
      markers: [...match[2].matchAll(/\d+/g)].map((m) => Number(m[0])),
    });
    consumed = pattern.lastIndex;
  }
  const rest = answer.slice(consumed).trim();
  if (rest) claims.push({ text: rest, markers: [] });
  return claims;
}

function CiteChip({ citation, active, onSelect }: {
  citation: Citation | undefined;
  active: boolean;
  onSelect: () => void;
}) {
  if (!citation) return null;
  return (
    <button type="button" className={active ? "cite-chip is-active" : "cite-chip"} aria-pressed={active}
            onClick={onSelect} title={`${citation.title}, page ${citation.page}`}>
      <span aria-hidden="true">{citation.marker}</span>
      <span className="sr-only">Source {citation.marker}: {citation.title}, page {citation.page}</span>
    </button>
  );
}

function pageLabel(c: Citation): string {
  return c.page === c.page_end ? `Page ${c.page}` : `Pages ${c.page}–${c.page_end}`;
}

function Answer({ turn, selected, onSelect }: {
  turn: Turn;
  selected: number | null;
  onSelect: (marker: number) => void;
}) {
  if (turn.error) {
    return <p className="answer-error" role="alert">{turn.error}</p>;
  }
  if (!turn.response) {
    return <p className="answer-loading">Searching 10 MAS publications for passages that answer this…</p>;
  }
  const r = turn.response;
  if (r.refused) {
    return (
      <div className="answer-refused">
        <p>{r.answer}</p>
        <p className="muted">
          No passage in the indexed MAS documents answers this, so ReguLens didn't guess. Try naming the
          guideline or the requirement you're thinking of.
        </p>
      </div>
    );
  }
  const byMarker = new Map(r.citations.map((c) => [c.marker, c]));
  const claims = splitClaims(r.answer);
  const passagesCited = new Set(r.citations.map((c) => c.chunk_id)).size;
  return (
    <>
      <ol className="claims">
        {claims.map((claim, i) => (
          <li key={i}>
            {claim.text}
            {claim.markers.length > 0 && " "}
            {claim.markers.map((m) => (
              <Fragment key={m}>
                <CiteChip citation={byMarker.get(m)} active={selected === m}
                          onSelect={() => onSelect(m)} />
              </Fragment>
            ))}
          </li>
        ))}
      </ol>
      <p className="advice-line">Not legal advice. Check the cited passages before you act on this answer.</p>
      <dl className="answer-strip">
        <div>
          <dt>Sources cited</dt>
          <dd>{passagesCited} of {r.retrieved_chunk_ids.length}<span className="sr-only"> passages found</span></dd>
        </div>
        <div><dt>Response time</dt><dd>
          {r.cached ? <>Instant <span className="strip-note">(answered before)</span></> : formatMs(r.latency_ms)}
        </dd></div>
        <div><dt>Cost per query</dt><dd>{formatUsd(r.cost_usd)}</dd></div>
      </dl>
      <h2 className="section-title">Sources</h2>
      <ol className="source-list">
        {r.citations.map((c) => (
          <li key={c.marker}>
            <button type="button" className={selected === c.marker ? "source-item is-active" : "source-item"}
                    aria-pressed={selected === c.marker} onClick={() => onSelect(c.marker)}>
              <span className="source-num" aria-hidden="true">{c.marker}</span>
              <span className="source-body">
                <span className="source-title">{c.title}</span>
                <span className="source-meta">
                  {pageLabel(c)}{c.heading ? `, ${c.heading}` : ""}
                </span>
                {!c.quote_verified && <span className="source-flag">Closest match, not word for word</span>}
              </span>
              <svg className="source-arrow" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
                <path d="M3 8h10M9 4l4 4-4 4" />
              </svg>
            </button>
          </li>
        ))}
      </ol>
    </>
  );
}

function EmptyPanel({ refused }: { refused: boolean }) {
  const [docs, setDocs] = useState<SourceInfo[]>([]);
  useEffect(() => {
    api.sources("regulation").then(setDocs).catch(() => setDocs([]));
  }, []);
  return (
    <section className="source-panel is-empty" aria-label="Source document">
      <div className="sheet">
        {refused ? (
          <p className="sheet-status">This question wasn't answered, so there's no source to show.</p>
        ) : (
          <>
            <p className="empty-lead">
              The page each answer comes from opens here, with the cited paragraph highlighted.
            </p>
            {docs.length > 0 && (
              <>
                <h2 className="empty-title">Publications you can ask about</h2>
                <ul className="doc-list">
                  {docs.map((d) => <li key={d.id}>{d.title}</li>)}
                </ul>
              </>
            )}
          </>
        )}
      </div>
    </section>
  );
}

export default function AskPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [question, setQuestion] = useState("");
  const busy = turns.some((t) => !t.response && !t.error);
  const panelRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const current = turns.find((t) => t.id === currentId) ?? null;
  const citation = current?.response?.citations.find((c) => c.marker === selected) ?? null;

  async function submit(text: string) {
    const q = text.trim();
    if (q.length < 3 || busy) return;
    const id = Date.now();
    setTurns((t) => [...t, { id, question: q }]);
    setCurrentId(id);
    setSelected(null);
    setQuestion("");
    requestAnimationFrame(() => headingRef.current?.focus());
    try {
      const response = await api.ask(q);
      setTurns((t) => t.map((turn) => (turn.id === id ? { ...turn, response } : turn)));
      setSelected((s) => s ?? response.citations[0]?.marker ?? null);
    } catch (err) {
      const message = err instanceof ApiError
        ? err.message
        : "The question couldn't be sent. Check your connection and try again.";
      setTurns((t) => t.map((turn) => (turn.id === id ? { ...turn, error: message } : turn)));
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit(question);
  }

  function selectCitation(marker: number) {
    setSelected(marker);
    // When the columns are stacked, the panel is below the answer: take the reader to it.
    if (window.matchMedia(STACKED).matches) {
      const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      requestAnimationFrame(() =>
        panelRef.current?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" }),
      );
    }
  }

  function openTurn(id: number) {
    const turn = turns.find((t) => t.id === id);
    setCurrentId(id);
    setSelected(turn?.response?.citations[0]?.marker ?? null);
  }

  const earlier = turns.filter((t) => t.id !== currentId).reverse();

  return (
    <div className="ask-layout">
      <div className="answer-col">
        <form className="ask-form" onSubmit={onSubmit} role="search">
          <label htmlFor="question" className="ask-label">Ask about MAS guidelines and notices</label>
          <div className="ask-row">
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
              aria-describedby="ask-hint"
            />
            <button type="submit" className="button-primary" disabled={busy || question.trim().length < 3}>
              {busy ? "Asking…" : "Ask"}
            </button>
          </div>
          <p id="ask-hint" className="hint">Enter to ask, Shift+Enter for a new line.</p>
        </form>

        {!current && (
          <section className="examples" aria-labelledby="examples-title">
            <h2 id="examples-title" className="section-title">Try a question</h2>
            <ul>
              {EXAMPLES.map((ex) => (
                <li key={ex}>
                  <button type="button" className="example" onClick={() => void submit(ex)}>{ex}</button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {current && (
          <article className="answer" aria-live="polite" aria-busy={busy}>
            {current.response?.summary && (
              <p className="answer-asked"><span className="sr-only">You asked: </span>{current.question}</p>
            )}
            {/* The heading is the answer in one line once it arrives (checked on the server),
                otherwise the question. */}
            <h1 ref={headingRef} tabIndex={-1} className="answer-title">
              {current.response?.summary ?? current.question}
            </h1>
            <Answer turn={current} selected={selected} onSelect={selectCitation} />
          </article>
        )}

        {earlier.length > 0 && (
          <nav className="history" aria-labelledby="history-title">
            <h2 id="history-title" className="section-title">Earlier questions</h2>
            <ul>
              {earlier.map((t) => (
                <li key={t.id}>
                  <button type="button" className="history-item" onClick={() => openTurn(t.id)}>
                    {t.question}
                  </button>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </div>

      <div className="panel-col" ref={panelRef}>
        {citation && current ? (
          <SourcePanel key={`${current.id}-${citation.marker}`} citation={citation} />
        ) : (
          <EmptyPanel refused={!!current?.response?.refused} />
        )}
      </div>
    </div>
  );
}
