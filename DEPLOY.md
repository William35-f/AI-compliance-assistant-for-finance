# Deploying ReguLens (free tier)

Target: **Render** (free Docker web service) + **Neon** (free serverless Postgres with pgvector).
One container serves both the API and the React app, so there is a single URL.

Why this pair: both have free tiers that need no credit card, Neon supports the `vector`
extension, and Render builds straight from the repo's `Dockerfile`. The API uses about 300 MB
of RAM (measured), which fits Render's 512 MB free instance as long as the reranker stays off.

---

## 1. Create the database (Neon, ~5 min)

1. Sign up at <https://neon.tech> and create a project. Pick the region closest to Singapore
   (AWS Asia Pacific, Singapore) and Postgres 16 or newer.
2. On the project dashboard, copy the **connection string**. It looks like
   `postgresql://user:password@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`.
   Keep `?sslmode=require` at the end.
3. Nothing else to configure: on first start the app runs `schema.sql`, which creates the
   `vector` extension and all tables.

## 2. Load the MAS guidelines into Neon (from your laptop, ~4 min)

The server never ingests documents itself: you build the index once from your machine.

```powershell
.venv\Scripts\activate
$env:DATABASE_URL = "postgresql://...neon.tech/neondb?sslmode=require"   # your Neon string
python scripts/download_sources.py --doc-type regulation   # skips files you already have
python scripts/ingest.py --index heading --doc-type regulation
```

You should see 10 documents and about 366 chunks. Close that PowerShell window afterwards
(or `Remove-Item Env:DATABASE_URL`) so later local runs use your Docker database again.

## 3. Push the code to GitHub

```powershell
git push origin main
```

## 4. Create the web service (Render, ~15 min including the first build)

1. Sign up at <https://render.com> with your GitHub account.
2. **New → Web Service**, choose this repository.
3. Settings:
   - **Language / Runtime:** Docker (Render detects the `Dockerfile`).
   - **Instance type:** Free.
   - **Health check path:** `/health`.
4. **Environment variables:**

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | your Neon connection string |
   | `GEMINI_API_KEY` | your Gemini key |

   Optional: `RATE_LIMIT_ASK_PER_MINUTE` (default 10), `RATE_LIMIT_HEAVY_PER_HOUR` (default 6).
5. **Create Web Service.** The first build takes about 10 minutes: it builds the React app,
   installs Python packages, bakes the embedding model into the image and downloads the five
   annual reports.

## 5. Check it works

- `https://<your-app>.onrender.com/health` returns `{"status":"ok", ...}`.
- Open `https://<your-app>.onrender.com/`, ask "How quickly must an FI notify MAS of a severe
  disruption?" and click the citation numbers.
- Put the URL in the README's "Live demo" line.

## 6. Turn on the CI smoke eval

GitHub → your repo → **Settings → Secrets and variables → Actions → New repository secret**:
name `GEMINI_API_KEY`, value your key. The `smoke-eval` job then runs on every push to `main`
(20 questions, about 40 Gemini requests) and fails if answer correctness drops below the
threshold in `.github/workflows/ci.yml`.

---

## Things to know

- **Cold starts.** Free Render services sleep after 15 minutes without traffic; the first request
  afterwards takes about a minute. Open the site a minute before a demo or interview.
- **Gemini quota.** The free tier allows only a few hundred requests per day. Rate limits and
  three cache layers protect it, but a busy demo can still hit the daily cap; the API then answers
  `429` with a clear message until the quota resets.
- **Secrets.** Keys live only in Render's environment settings and the GitHub secret, never in
  the repo. If a key leaks, revoke it in Google AI Studio and create a new one.
- **Alternatives.** Railway or Fly.io work the same way (Docker + `DATABASE_URL` +
  `GEMINI_API_KEY`); Supabase is an alternative free Postgres with pgvector.
