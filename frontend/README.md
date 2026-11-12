# ReguLens frontend

React + TypeScript (Vite). Three pages: **Ask** (chat with clickable citations), **Extract** (annual report figures as a table, plus the MAS risk check) and **Stats** (usage and latest eval scores).

```powershell
npm install
npm run dev        # http://localhost:5173, forwards API calls to http://127.0.0.1:8001
npm run build      # production build in dist/, served by FastAPI
```

Set `VITE_API_TARGET` if the API runs on another port.
