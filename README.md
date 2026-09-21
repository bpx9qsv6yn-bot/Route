# FairRoute

FairRoute is an accessibility-aware journey-planning prototype for Gainesville, Florida. It combines community-resource listings with modeled walking, rolling, biking and RTS transit access, while keeping uncertainty about entrances, boarding conditions and other accessibility details visible.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Open `http://localhost:8501`.

The main desktop experience is served by `server.py` with the static interface in `web/`. A Streamlit-hosted bridge is available through `streamlit_app.py`. The older `app.py` Streamlit interface remains in the repository as an alternate prototype.

## Verify the project

Run the Python test suite:

```bash
python -m unittest discover -s tests
```

Check the browser JavaScript syntax:

```bash
node --check web/app.js
```

## Repository layout

| Path | Purpose |
| --- | --- |
| `server.py` | Local HTTP/API entry point for the desktop demo |
| `streamlit_app.py` | Streamlit wrapper for the desktop interface |
| `app.py` | Earlier Streamlit interface |
| `fairroute.py` | Deterministic street/transit routing and travel calculations |
| `journey.py` | Journey filtering, ranking and presentation helpers |
| `planner.py` | Access-gap and intervention scenario calculations |
| `access_evidence.py` | Accessibility evidence and verification checklist logic |
| `resource_adapter.py` | Florida Community Resource Map integration and fallback data handling |
| `gemini_assistant.py` | Optional bounded Gemini tool-calling assistant |
| `demo_story.py` | Isolated fictional demonstration fixtures |
| `web/` | Desktop HTML, CSS, JavaScript and vendored Leaflet assets |
| `data/` | Curated resources, fallback snapshot and local routing networks |
| `tests/` | Unit tests |
| `docs/` | Demo, product direction, submission and maintainer handoff notes |
| `dist/streamlit/` | Small Streamlit distribution bundle |

## Optional Gemini configuration

Copy the example configuration and add a real API key locally:

```bash
cp .env.example .env
```

`.env` is ignored by Git. The assistant is optional; the deterministic app controls work without it.

## Data and interpretation

FairRoute is a planning prototype, not an accessibility certification, live departure system, eligibility checker or investment recommendation. Street geometry does not establish sidewalk or curb-cut quality. Unknown access details remain unknown rather than being treated as accessible.

For demo instructions, operating assumptions, data provenance and handoff notes, see `docs/demo-guide.md` and `docs/handoff.md`.
