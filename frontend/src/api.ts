// Typed client for the ReguLens API. The types mirror the Pydantic models in
// backend/regulens (qa.py, extraction.py, risk_agent.py, main.py).

export interface Citation {
  marker: number;
  chunk_id: number;
  source_id: string;
  title: string;
  page: number;
  page_end: number;
  heading: string | null;
  quote: string;
  quote_verified: boolean;
}

export interface AskResponse {
  answer: string;
  summary: string | null; // one-line heading, checked against the claims; null if it failed
  citations: Citation[];
  refused: boolean;
  refusal_reason: string | null;
  retrieved_chunk_ids: number[];
  top_score: number | null;
  latency_ms: number;
  tokens: { input: number; output: number };
  cost_usd: number;
  model: string | null;
  cached: boolean;
  disclaimer: string;
}

export interface Figure {
  value: number | null;
  as_reported: number | null;
  unit_label: string | null;
  multiplier: number;
  page: number | null;
  source_text: string | null;
  verified: boolean;
}

export interface DebtFigure extends Figure {
  components: Figure[];
}

export interface KeyRisk {
  title: string;
  summary: string;
  page: number;
}

export interface ExtractionResult {
  source_id: string | null;
  company: string;
  fiscal_year: string;
  fiscal_year_end: string | null;
  currency: string;
  revenue: Figure;
  net_profit: Figure;
  total_debt: DebtFigure;
  key_risks: KeyRisk[];
  pages_used: Record<string, number[]>;
  warnings: string[];
  latency_ms: number;
  tokens: Record<string, number>;
  cost_usd: number;
  model: string;
}

export interface RelatedGuideline {
  chunk_id: number;
  source_id: string;
  title: string;
  page: number;
  heading: string | null;
  quote: string;
  quote_verified: boolean;
}

export interface RiskAssessment {
  risk: KeyRisk;
  related_guidelines: RelatedGuideline[];
  assessment: string;
  needs_human_review: boolean;
  steps_used: number;
  searches: string[];
}

export interface RiskCheckResult {
  assessments: RiskAssessment[];
  latency_ms: number;
  tokens: Record<string, number>;
  cost_usd: number;
  disclaimer: string;
}

export interface EvalSnapshot {
  run: string;
  timestamp: string;
  config: Record<string, unknown>;
  metrics: Record<string, number | null>;
}

export interface StatsResponse {
  usage: {
    queries: number;
    refused: number;
    cached: number;
    latency_p50_ms: number | null;
    latency_p95_ms: number | null;
    avg_cost_usd: number | null;
    first_query_at: string | null;
  };
  latest_eval: EvalSnapshot | null;
  latest_retrieval_eval: EvalSnapshot | null;
  rate_limits: Record<string, string>;
}

export interface SourceInfo {
  id: string;
  title: string;
  publisher: string;
  doc_type: "regulation" | "annual_report";
  url: string;
  downloaded: boolean;
}

export interface SourceParagraph {
  label: string | null; // the document's own paragraph number, e.g. "4.1.1" or "(g)"
  heading: string | null;
  text: string;
  cited: boolean;
}

export interface SourcePage {
  source_id: string;
  title: string;
  publisher: string;
  url: string;
  page: number;
  page_count: number;
  paragraphs: SourceParagraph[];
  cited_found: boolean;
}

/** An API error with the server's explanation (FastAPI puts it in `detail`). */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError(0, "Can't reach the ReguLens API. Is the backend running?");
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* keep the status text */
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  ask: (question: string) => request<AskResponse>("/ask", json({ question })),

  extractById(sourceId: string) {
    const form = new FormData();
    form.append("source_id", sourceId);
    return request<ExtractionResult>("/extract", { method: "POST", body: form });
  },

  extractUpload(file: File) {
    const form = new FormData();
    form.append("file", file);
    return request<ExtractionResult>("/extract", { method: "POST", body: form });
  },

  riskCheck: (risks: KeyRisk[], maxRisks = 3) =>
    request<RiskCheckResult>("/risk-check", json({ risks, max_risks: maxRisks })),

  /** Extract the report's risks on the server, then check the first `maxRisks`. */
  riskCheckReport: (sourceId: string, maxRisks = 3) =>
    request<RiskCheckResult>("/risk-check", json({ source_id: sourceId, max_risks: maxRisks })),

  sourcePage(sourceId: string, page: number, quote?: string, through?: number) {
    const params = new URLSearchParams();
    if (quote) params.set("quote", quote.slice(0, 2000));
    if (through && through > page) params.set("through", String(through));
    const query = params.toString();
    return request<SourcePage>(
      `/sources/${encodeURIComponent(sourceId)}/pages/${page}${query ? `?${query}` : ""}`,
    );
  },

  stats: () => request<StatsResponse>("/stats"),

  sources: (docType?: SourceInfo["doc_type"]) =>
    request<SourceInfo[]>(docType ? `/sources?doc_type=${docType}` : "/sources"),
};
