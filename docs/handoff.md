# FairRoute: maintainer handoff

## Product and audience

FairRoute is an accessibility layer for the existing Florida Community Resource Map. The primary audience is Gainesville residents who walk, roll or use transit, and caseworkers helping them identify realistic next steps. The core flow is search → travel constraints → field-level access evidence → provider questions. It does not certify accessible routes or determine service eligibility.

## Run the desktop app

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Open http://localhost:8501 at desktop width. No frontend build or account is required. This binds locally and is not a production deployment. The earlier Streamlit interface remains available through `app.py`.

The footer's **Try the access example** produces a repeatable comparison using two explicitly fictional pantry locations, including invented entrance facts and modeled travel times. This data is isolated from ordinary FCI searches and is not a factual claim about a provider.

## Data ownership and refresh

- **FCI directory:** `resource_adapter.py` uses a fixed public Gainesville search. A resident's origin is not sent as part of that directory query. The repository includes `data/resource_snapshot.json` as an outage fallback. Restart the app to clear the in-process catalog cache. Snapshot loading is visibly labeled. Directory dates do not certify access facts. A snapshot-refresh utility is not currently checked into this repository, so future maintainers should add a reviewed refresh process before relying on the fallback operationally.
- **Transit:** the bundled network was built from the official RTS fall 2026 feed. The current repository contains the built `data/transit_network.json`, but not the original GTFS build utility. Rebuilding from a newer feed therefore requires restoring or replacing that build step and validating service IDs/calendars. The current model is not a date-specific timetable or live-departure planner.
- **Streets:** bundled OSM-derived geometry supports path drawing, not curb-cut or sidewalk certification. Keep the map attribution. Basemap tiles require internet; local routing and results do not require an external directions service.
- **Access evidence:** missing structured entrance/restroom fields remain unknown. Known inaccessible boarding and alighting stops are excluded for wheelchair-required transit. Missing stop or vehicle information remains flagged. Fictional demonstration facts are labeled.

## Gemini

Copy `.env.example` to `.env`, put a real `GEMINI_API_KEY` there, and select an available `GEMINI_MODEL`. No API key is committed to the repository. `.env` is ignored and is never served by the static server. Configuration is read per request, so key replacement does not require a restart.

The assistant uses Gemini REST function calling with an allowlist: find resources, explain a selected journey, show gaps, and compare plans. It cannot run shell commands, contact providers, modify FCI, or issue arbitrary network requests. Coordinates remain in local tool execution; explicit user messages and mobility preferences are sent to Google only after the user invokes the assistant. The UI explains this. Dictation depends on browser speech-recognition support and permission; prompt buttons and typing remain available. Read-aloud uses browser speech synthesis.

Tests simulate Gemini replies and verify dispatch and coordinate omission. A real-key end-to-end Gemini call should be re-verified before a live presentation or deployment, including the applicable Google data-handling and account settings.

## Planning assumptions

The access-gap view counts anonymous synthetic sample points near transit, not people. The investment planner measures the share of resource categories reachable at eight sample locations, with equal weights per location and illustrative costs. Efficiency maximizes mean access; fairness weights mean access 55% and minimum access 45%. Both use the same budget cap; they may spend different amounts. Mobility hubs enable optional cycling and are **not** modeled wheelchair-access interventions. Scenarios include demonstration listings. These results illustrate tradeoffs, not investment recommendations.

## Verification and known boundaries

Run:

```bash
python -m unittest discover -s tests
node --check web/app.js
```

GitHub Actions runs the same checks for pushes to `main` and pull requests.

Current tests cover routing limits, boarding access, evidence labels, offline snapshots, demo reversal, and bounded assistant dispatch. Browser verification should cover finder behavior, preference changes, evidence/checklist presentation, access-gap profiles, and planning results.

Before serving residents: observe residents and caseworkers completing tasks; verify physical access with providers; agree with FCI on allowed integration, ownership, and any writeback; add a reviewed provider-update workflow with per-field source/date/reviewer; restore documented data-refresh/build pipelines; and implement production hosting, request limits, and data-lifecycle controls. No provider updates or diagnoses are stored by this prototype.

## Files to start with

- `README.md`: public project overview and setup.
- `docs/architecture.md`: component boundaries and data flow.
- `server.py`: local API and validation.
- `fairroute.py`: deterministic routing and burden calculations.
- `access_evidence.py`: access facts and provider checklist.
- `gemini_assistant.py`: bounded optional language interface.
- `planner.py`: explicit scenario objectives.
- `web/`: desktop interface; Leaflet is vendored with its license.
- `demo_story.py`: isolated fictional demo fixtures.
