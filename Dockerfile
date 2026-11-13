# ReguLens: one container serving the FastAPI backend and the built React app.
# Build:  docker build -t regulens .
# Run:    docker run -p 8000:8000 -e DATABASE_URL=... -e GEMINI_API_KEY=... regulens

# ---------- Stage 1: build the React frontend ----------
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: Python API ----------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1
WORKDIR /app

# Dependencies first, so code changes don't reinstall them (better layer caching).
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/regulens/__init__.py backend/regulens/__init__.py
RUN pip install --timeout 120 --retries 5 -e ./backend

COPY backend/regulens backend/regulens
COPY scripts scripts
COPY data/sources.csv data/sources.csv
COPY eval eval
COPY --from=frontend /app/frontend/dist frontend/dist

# Bake the embedding model into the image: no download on cold start.
RUN python -c "from regulens.embeddings import get_embedder; get_embedder()"

# Source PDFs: annual reports for /extract, regulations for the source panel on Ask.
# Public URLs; a failed download only hides that document in the UI (uploads still
# work, and answers still carry their quotes), so it must not break the build.
ARG DOWNLOAD_REPORTS=true
RUN if [ "$DOWNLOAD_REPORTS" = "true" ]; then \
      python scripts/download_sources.py || echo "source download skipped"; \
    fi

# Run as a non-root user.
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
# Hosts like Render pass the port in $PORT.
CMD ["sh", "-c", "uvicorn regulens.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
