# FairRoute

**Accessibility-aware resource routing for people who walk, roll, bike, or use transit.**

[![CI](https://github.com/bpx9qsv6yn-bot/Route/actions/workflows/ci.yml/badge.svg)](https://github.com/bpx9qsv6yn-bot/Route/actions/workflows/ci.yml)

FairRoute is a Gainesville-focused planning prototype that asks a harder question than “what service is nearby?”:

> **Can someone realistically reach and use it with the mobility constraints they have?**

It combines community-resource listings, local street geometry, transit data, mobility preferences, and explicit accessibility evidence. The routing and scoring core is deterministic; the optional Gemini integration is a bounded natural-language layer over the same application tools.

## Why this project exists

Distance alone can hide the real cost of reaching a resource. A destination may be geographically close while still requiring too much walking, an inaccessible boarding stop, an uncertain entrance, or a trip that exceeds a person's practical travel limit.

FairRoute keeps those constraints visible instead of silently treating unknown accessibility information as accessible.

## What it does

- **Resource journey planning** — ranks community resources using modeled walk, bike, and RTS transit journeys.
- **Mobility-aware filtering** — supports walking limits, walking pace, wheelchair transit requirements, and facility-access requirements.
- **Inspectable accessibility evidence** — distinguishes known, unknown, and demonstration-only access facts and generates provider questions when details need confirmation.
- **Access-gap analysis** — compares modeled reachability across synthetic sample locations and mobility profiles.
- **Scenario planning** — explores illustrative interventions and makes average-access vs. least-served tradeoffs explicit.
- **Optional Gemini assistant** — uses an allowlisted set of application tools for plain-language interaction without replacing the deterministic routing engine.
- **Offline resilience** — includes a checked-in public resource snapshot for fallback behavior when the live directory cannot be reached.

## Architecture

```text
Browser UI (web/)
        |
        v
server.py / streamlit_app.py
        |
        +--> resource_adapter.py ----> FCI directory / local snapshot
        +--> fairroute.py ----------> street + transit networks
        +--> journey.py ------------> ranking + trip summaries
        +--> access_evidence.py ----> access facts + verification prompts
        +--> planner.py ------------> gap + intervention analysis
        |
        +-. optional .-> gemini_assistant.py
```

The language-model path is intentionally optional. Numerical journey, accessibility, and planning claims come from application tools rather than free-form model output.

For a more detailed system view, see [docs/architecture.md](docs/architecture.md).

## Quick start

### Requirements

- Python 3.11+
- Node.js only if you want to run the JavaScript syntax check
- Internet access for the live community-resource lookup and map tiles; local fallback/resource-routing data is bundled

### Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Open `http://localhost:8501`.

The desktop experience is served by `server.py` and `web/`. `streamlit_app.py` provides a Streamlit-hosted bridge. `app.py` is an earlier Streamlit interface retained as an alternate prototype.

## Verify the project

```bash
python -m unittest discover -s tests
node --check web/app.js
```

The GitHub Actions workflow runs these checks automatically on pushes to `main` and on pull requests.

## Optional Gemini configuration

The core application works without Gemini.

```bash
cp .env.example .env
```

Then add a local `GEMINI_API_KEY` and, if needed, change `GEMINI_MODEL`. The local `.env` file is ignored by Git.

The assistant can call only a small allowlist of FairRoute tools. It cannot contact providers, modify the source directory, run shell commands, or replace the application's deterministic calculations.

## Repository map

| Path | Responsibility |
| --- | --- |
| `server.py` | Local API/server and request validation |
| `streamlit_app.py` | Streamlit wrapper around the desktop UI |
| `app.py` | Earlier Streamlit prototype |
| `fairroute.py` | Street/transit routing and travel calculations |
| `journey.py` | Journey filtering, ranking, and presentation helpers |
| `planner.py` | Access-gap and intervention scenario calculations |
| `access_evidence.py` | Accessibility evidence and verification checklist logic |
| `resource_adapter.py` | Community-resource integration and fallback handling |
| `gemini_assistant.py` | Optional bounded Gemini tool-calling layer |
| `demo_story.py` | Isolated fictional demonstration fixtures |
| `web/` | Desktop HTML, CSS, JavaScript, and vendored Leaflet assets |
| `data/` | Resource data, fallback snapshot, and local routing networks |
| `tests/` | Unit tests |
| `docs/` | Architecture, product direction, demo, submission, and maintainer notes |
| `dist/streamlit/` | Streamlit distribution bundle |

## Engineering choices

**Deterministic first.** Routing, scoring, access-gap calculations, and planning results live in Python application code. The LLM does not invent travel times or accessibility facts.

**Unknown stays unknown.** Missing entrance, restroom, stop, or vehicle information is surfaced as uncertainty instead of being converted into a positive accessibility claim.

**Demo data is isolated.** Fictional examples are explicitly labeled and kept separate from ordinary resource searches.

**Planning results are illustrative.** Synthetic sample locations and intervention costs help expose tradeoffs; they are not measurements of resident outcomes or investment recommendations.

## Current scope and limitations

FairRoute is a prototype, not:

- an accessible-route certification system,
- a live transit departure planner,
- a service-eligibility checker,
- a substitute for provider verification,
- or a production investment-allocation system.

Bundled street geometry does not establish sidewalk, curb-cut, or entrance quality. Transit and resource information can become stale and should be refreshed and validated before real-world deployment.

## Documentation

- [Architecture](docs/architecture.md)
- [Demo guide](docs/demo-guide.md)
- [Product direction](docs/product-direction.md)
- [Maintainer handoff](docs/handoff.md)
- [Submission summary](docs/submission.md)

## Project status

FairRoute is an actively polished prototype intended to demonstrate accessibility-aware product thinking, deterministic routing, public-data integration, transparent uncertainty, and bounded AI integration.
