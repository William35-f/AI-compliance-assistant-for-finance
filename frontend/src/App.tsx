import { useEffect, useState } from "react";
import { api } from "./api";
import AskPage from "./pages/AskPage";
import ExtractPage from "./pages/ExtractPage";
import RiskPage from "./pages/RiskPage";
import StatsPage from "./pages/StatsPage";
import { useTheme } from "./theme";

// Tiny hash router: #/ask, #/extract, #/risk, #/stats. No library needed for four pages,
// and hash URLs work when FastAPI serves the built files.
type Route = "ask" | "extract" | "risk" | "stats";
const ROUTES: { id: Route; label: string }[] = [
  { id: "ask", label: "Ask" },
  { id: "extract", label: "Extract" },
  { id: "risk", label: "Risk check" },
  { id: "stats", label: "Stats and evals" },
];

function currentRoute(): Route {
  const id = window.location.hash.replace("#/", "");
  return ROUTES.some((r) => r.id === id) ? (id as Route) : "ask";
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "Searching 10 MAS guidelines and 5 annual reports", from the server's source list. */
function useScope(): string | null {
  const [scope, setScope] = useState<string | null>(null);
  useEffect(() => {
    api.sources()
      .then((all) => {
        const regulations = all.filter((s) => s.doc_type === "regulation").length;
        const reports = all.filter((s) => s.doc_type === "annual_report").length;
        setScope(`Searching ${plural(regulations, "MAS guideline", "MAS guidelines")} and ${plural(reports, "annual report", "annual reports")}`);
      })
      .catch(() => setScope(null));
  }, []);
  return scope;
}

export default function App() {
  const [route, setRoute] = useState<Route>(currentRoute);
  const [theme, setTheme] = useTheme();
  const scope = useScope();
  const dark = theme === "dark";

  useEffect(() => {
    const onHash = () => setRoute(currentRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="topbar">
        <a className="brand" href="#/ask">
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
            <rect x="3" y="9" width="18" height="6" className="brand-mark" />
            <path d="M3 5h18M3 19h12" className="brand-lines" />
          </svg>
          <span>ReguLens</span>
        </a>
        {scope && <p className="scope">{scope}</p>}
        <nav className="nav" aria-label="Pages">
          {ROUTES.map((r) => (
            <a key={r.id} href={`#/${r.id}`} className={route === r.id ? "nav-link is-active" : "nav-link"}
               aria-current={route === r.id ? "page" : undefined}>
              {r.label}
            </a>
          ))}
        </nav>
        <button type="button" role="switch" aria-checked={dark} className="theme-switch"
                onClick={() => setTheme(dark ? "light" : "dark")}>
          <span className="theme-switch-track" aria-hidden="true"><span className="theme-switch-thumb" /></span>
          <span>Dark theme</span>
        </button>
      </header>

      <main id="main" className={route === "ask" ? "content is-wide" : "content"}>
        {route === "ask" && <AskPage />}
        {route === "extract" && <ExtractPage />}
        {route === "risk" && <RiskPage />}
        {route === "stats" && <StatsPage />}
      </main>

      <footer className="footer">
        Answers draw only on MAS publications and company annual reports, with page citations.
        Check the source document before acting on any answer.
      </footer>
    </div>
  );
}
