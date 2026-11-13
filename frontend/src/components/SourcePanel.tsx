import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, ApiError, Citation, SourcePage } from "../api";

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

type Load =
  | { state: "loading"; page: number }
  | { state: "ready"; data: SourcePage }
  | { state: "error"; message: string };

/**
 * The cited document page next to the answer: the page's paragraphs in a serif
 * "sheet", the document's own paragraph numbers in the margin, and the cited
 * paragraph highlighted. The reader can step to neighbouring pages for context.
 * The parent gives it a `key` per citation, so switching citations starts fresh.
 */
export default function SourcePanel({ citation }: { citation: Citation }) {
  const [load, setLoad] = useState<Load>({ state: "loading", page: citation.page });
  // null = the cited page (as located by the server); a number = a page the reader moved to.
  const [browsePage, setBrowsePage] = useState<number | null>(null);
  const [citedPage, setCitedPage] = useState<number | null>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const markRef = useRef<HTMLElement>(null);

  useEffect(() => {
    let cancelled = false;
    const page = browsePage ?? citation.page;
    setLoad({ state: "loading", page });
    const request = browsePage === null
      ? api.sourcePage(citation.source_id, citation.page, citation.quote, citation.page_end)
      : api.sourcePage(citation.source_id, browsePage, citation.quote);
    request
      .then((data) => {
        if (cancelled) return;
        if (browsePage === null) setCitedPage(data.page);
        setLoad({ state: "ready", data });
      })
      .catch((err) => {
        if (cancelled) return;
        const message = err instanceof ApiError && err.status === 404
          ? "This document's PDF isn't available on the server, so only the quoted passage can be shown."
          : err instanceof ApiError ? err.message : "The page couldn't be loaded.";
        setLoad({ state: "error", message });
      });
    return () => { cancelled = true; };
  }, [citation.source_id, citation.page, citation.page_end, citation.quote, browsePage]);

  // Bring the highlighted paragraph into view inside the sheet (not the whole window).
  useLayoutEffect(() => {
    const sheet = sheetRef.current;
    const mark = markRef.current;
    if (load.state !== "ready" || !sheet) return;
    if (!mark || sheet.scrollHeight <= sheet.clientHeight) {
      sheet.scrollTop = 0;
      return;
    }
    const top = mark.offsetTop - sheet.offsetTop - sheet.clientHeight / 4;
    sheet.scrollTo({ top: Math.max(0, top), behavior: reducedMotion() ? "auto" : "smooth" });
  }, [load]);

  const data = load.state === "ready" ? load.data : null;
  const shownPage = data?.page ?? (load.state === "loading" ? load.page : citation.page);
  const onCitedPage = browsePage === null || browsePage === citedPage;

  return (
    <section className="source-panel" aria-label={`Source ${citation.marker}: ${citation.title}`}>
      <header className="source-panel-head">
        <h2 className="source-panel-title">
          <span className="source-num" aria-hidden="true">{citation.marker}</span>
          <span className="sr-only">Source {citation.marker}: </span>
          {citation.title}
        </h2>
        <p className="source-panel-meta">
          Page {citedPage ?? citation.page}{citation.heading ? `, ${citation.heading}` : ""}
        </p>
        <div className="source-panel-nav">
          <span className="page-count" aria-live="polite">
            Page {shownPage}{data ? ` of ${data.page_count}` : ""}
          </span>
          <button type="button" className="icon-button" aria-label="Previous page"
                  disabled={!data || data.page <= 1}
                  onClick={() => data && setBrowsePage(data.page - 1)}>
            <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M10 3 5 8l5 5" /></svg>
          </button>
          <button type="button" className="icon-button" aria-label="Next page"
                  disabled={!data || data.page >= data.page_count}
                  onClick={() => data && setBrowsePage(data.page + 1)}>
            <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="m6 3 5 5-5 5" /></svg>
          </button>
          {!onCitedPage && (
            <button type="button" className="text-button" onClick={() => setBrowsePage(null)}>
              Back to page {citedPage}
            </button>
          )}
          {data && (
            <a className="text-link" href={`${data.url}#page=${data.page}`} target="_blank" rel="noopener noreferrer">
              Open the PDF<span className="sr-only"> at page {data.page} (opens in a new tab)</span>
            </a>
          )}
        </div>
      </header>

      {load.state === "error" ? (
        <div className="sheet sheet-fallback">
          <p className="panel-note">{load.message}</p>
          <p className="doc-para is-cited">
            <span className="doc-label"><span className="label-chip" aria-hidden="true">{citation.marker}</span></span>
            <span className="doc-text"><mark className="cite-mark">{citation.quote}</mark></span>
          </p>
        </div>
      ) : (
        <>
          {data && onCitedPage && !data.cited_found && (
            <p className="panel-note">
              The quoted words weren't found exactly on this page. The quote as given:{" "}
              <q>{citation.quote}</q>
            </p>
          )}
          <div ref={sheetRef} className={load.state === "loading" ? "sheet is-loading" : "sheet"}
               tabIndex={0} aria-label={`Page ${shownPage} text`} aria-busy={load.state === "loading"}>
            {load.state === "loading" && !data && <p className="sheet-status">Loading page {load.page}…</p>}
            {data && data.paragraphs.length === 0 && (
              <p className="sheet-status">This page has no body text (it may be a cover, chart or table).</p>
            )}
            {data?.paragraphs.map((p, i) => {
              const firstCited = data.paragraphs.findIndex((q) => q.cited);
              const prev = data.paragraphs[i - 1];
              const showHeading = p.heading && p.heading !== prev?.heading;
              const cited = p.cited && onCitedPage;
              return (
                <div key={i}>
                  {showHeading && <h3 className="doc-heading">{p.heading}</h3>}
                  <p className={cited ? "doc-para is-cited" : "doc-para"}>
                    <span className="doc-label">
                      {cited && <span className="label-chip" aria-hidden="true">{citation.marker}</span>}
                      {p.label}
                    </span>
                    <span className="doc-text">
                      {cited ? (
                        <mark ref={i === firstCited ? markRef : undefined} className="cite-mark">
                          <span className="sr-only">Cited passage: </span>{p.text}
                        </mark>
                      ) : p.text}
                    </span>
                  </p>
                </div>
              );
            })}
          </div>
        </>
      )}

      <p className={citation.quote_verified ? "verify" : "verify is-flag"}>
        {citation.quote_verified
          ? "The quote matches the source text word for word."
          : "The model's quote didn't match the source exactly. The closest passage is shown; check it before relying on it."}
      </p>
    </section>
  );
}
