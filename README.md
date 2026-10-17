# FamilyLog

A self-hosted household app: **Økonomi** (bank exports in, exact numbers
out, questions answered by a local model from SQL results) and **FamilyMap**
(the family's own reviews of places, with a Danish phone page at `/fm/`).
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
