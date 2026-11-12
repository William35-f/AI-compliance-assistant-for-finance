import { useEffect, useState } from "react";
import AskPage from "./pages/AskPage";
import ExtractPage from "./pages/ExtractPage";
import StatsPage from "./pages/StatsPage";

// Tiny hash router: #/ask, #/extract, #/stats. No library needed for three pages,
// and hash URLs work when FastAPI serves the built files.
type Route = "ask" | "extract" | "stats";
const ROUTES: { id: Route; label: string }[] = [
  { id: "ask", label: "Ask" },
  { id: "extract", label: "Extract" },
  { id: "stats", label: "Stats" },
];

function currentRoute(): Route {
  const id = window.location.hash.replace("#/", "");
  return ROUTES.some((r) => r.id === id) ? (id as Route) : "ask";
}

export default function App() {
  const [route, setRoute] = useState<Route>(currentRoute);

  useEffect(() => {
    const onHash = () => setRoute(currentRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return (
    <div className="shell">
      <header className="topbar">
        <a className="brand" href="#/ask" aria-label="ReguLens home">
          <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
            <rect width="32" height="32" rx="7" className="brand-tile" />
            <circle cx="14" cy="14" r="7" fill="none" className="brand-lens" strokeWidth="3" />
            <path d="M19 19l6 6" className="brand-lens" strokeWidth="3" strokeLinecap="round" />
          </svg>
          <span>ReguLens</span>
        </a>
        <nav className="tabs" aria-label="Pages">
          {ROUTES.map((r) => (
            <a key={r.id} href={`#/${r.id}`} className={route === r.id ? "tab active" : "tab"}
               aria-current={route === r.id ? "page" : undefined}>
              {r.label}
            </a>
          ))}
        </nav>
        <span className="badge-advice" title="ReguLens is a research aid">Not legal advice</span>
      </header>

      <main className="content">
        {route === "ask" && <AskPage />}
        {route === "extract" && <ExtractPage />}
        {route === "stats" && <StatsPage />}
      </main>

      <footer className="footer">
        Answers come only from MAS publications and company annual reports, with page citations.
        Always check the source document.
      </footer>
    </div>
  );
}
