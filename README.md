# FamilyLog

A self-hosted household app. A phone front page at `/` with **Alf** (a local
model the family can ask anything, that knows the family's places) and the
**Dagbog** (rate the day); **FamilyMap** (the family's own reviews of places,
Alf's Atlas at `/fm/`); and **Økonomi** (bank exports in, exact numbers out).
The admin app is at `/app/`.
FastAPI + SQLite backend, React + Vite frontend, one container, models from
Ollama on the GPU VM.

- Deploy and update: [docs/CONTAINER.md](docs/CONTAINER.md)
- What changed: [docs/CHANGELOG.md](docs/CHANGELOG.md)
- How it is built, for the next change: [docs/HANDOFF.md](docs/HANDOFF.md)
- In-app help: [docs/HELP.md](docs/HELP.md) (Alt + click any control)

Development:

    cd backend && pip install -r requirements-dev.txt && python -m pytest -q
    cd frontend && npm ci && npm test && npm run build
    python3 tools/mock_ollama.py 11434 &          # a stand-in Ollama
    cd backend && APP_DATA_DIR=./data python -m uvicorn app.main:app --port 8080
    cd frontend && npm run dev                    # proxies /api to :8080
