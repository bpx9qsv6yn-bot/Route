# FairRoute: handoff to FCI / the next maintainer

## Product and audience

An accessibility layer for the existing Florida Community Resource Map. The primary audience is Gainesville residents who walk, roll or use transit, and caseworkers helping them identify realistic next steps. The core flow is search → travel constraints → field-level access evidence → provider questions. It does not certify accessible routes or determine service eligibility.

## Run the judge-ready desktop app

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Open http://localhost:8501 at desktop width. No frontend build or account is required. This binds locally and is not a production deployment. The old Streamlit app remains optional.

The footer's **Try the access example** produces a repeatable comparison: two explicitly fictional pantry locations, one invented inaccessible entrance, one invented step-free entrance, and real modeled travel times. This data is isolated from ordinary FCI searches. It is not a factual claim about a provider.

## Data ownership and refresh

- **FCI directory:** `resource_adapter.py` uses a fixed public Gainesville search. A resident's origin is never sent to FCI. `python scripts/refresh_resources.py` explicitly saves a dated public snapshot for outage fallback. Restart the app to clear the in-process catalog cache. Snapshot loading is visibly labeled. Directory dates do not certify access facts.
- **Transit:** current build downloaded September 20, 2026 from the official [RTS data page](https://go-rts.com/rts-data/), linked [fall archive](https://www.go-rts.com/wp-content/uploads/2026/08/RTSGTFS_Fall2026-1.zip). Rebuild with `python scripts/build_transit.py --gtfs /path/to/unpacked/feed --service Weekday,M-Th`. Inspect service IDs and calendars for every new feed. The current model combines weekday and Monday–Thursday service; it is not a date-specific timetable or live departure planner. Selected calendar validity ends April 29, 2027. The publisher's overall feed end is May 2, 2027.
- **Streets:** bundled OSM geometry supports path drawing, not curb-cut or sidewalk certification. Keep the map attribution. Basemap tiles require internet; the local routing and results do not require a directions service.
- **Access evidence:** missing structured entrance/restroom fields remain unknown. Known inaccessible boarding and alighting stops are excluded for wheelchair-required transit. Missing stop or vehicle information remains flagged. Fictional demonstration facts are labeled.

## Gemini

Copy `.env.example` to `.env`, put a real `GEMINI_API_KEY` there, and select an available `GEMINI_MODEL`. The user's dummy key is currently local configuration only. `.env` is ignored and is never served by the static server. Configuration is read per request, so key replacement does not need a restart.

The assistant uses Gemini REST function calling with an allowlist: find resources, explain a selected journey, show gaps, compare plans. It cannot run shell commands, contact providers, modify FCI, or issue arbitrary network requests. Coordinates remain in local tool execution; explicit user messages and mobility preferences are sent to Google after the user presses **Send to Gemini**. The UI explains this. Dictation depends on browser speech-recognition support and permission; prompt buttons and typing remain available. Read-aloud uses browser speech synthesis.

Tests simulate Gemini replies and verify dispatch and coordinate omission. **A real-key end-to-end Gemini call has not been verified.** Before presenting it live, replace the dummy key, try each tool prompt, confirm the resulting app view, and review Google's applicable data handling and account settings.

## Planning assumptions

The access-gap view counts anonymous synthetic sample points near transit, not people. The investment planner measures the share of resource categories reachable at eight sample locations, with equal weights per location and illustrative costs. Efficiency maximizes mean access; fairness weights mean access 55% and minimum access 45%. Both use the same budget cap; they may spend different amounts. Mobility hubs enable optional cycling and are **not** modeled wheelchair-access interventions. Scenarios include demonstration listings. These results illustrate tradeoffs, not investment recommendations.

## Verification and known boundaries

Run `python -m unittest discover -s tests` and `node --check web/app.js`. Current checks include routing limits, boarding access, evidence labels, offline snapshots, demo reversal, and bounded assistant dispatch. Browser verification covers finder, preference changes, evidence/checklist, both gap profiles, and the two planning results.

Before serving residents: observe residents and caseworkers completing tasks; verify physical access with providers; agree with FCI on allowed integration, ownership and any writeback; add a reviewed provider-update workflow with per-field source/date/reviewer; implement production hosting, request limits and data lifecycle controls. No provider updates or diagnoses are stored by this prototype.

## Files to start with

- `server.py`: local API and validation.
- `fairroute.py`: deterministic routing and burden calculations.
- `access_evidence.py`: access facts and provider checklist.
- `gemini_assistant.py`: bounded optional language interface.
- `planner.py`: explicit scenario objectives.
- `web/`: desktop interface; Leaflet is vendored with its license.
- `demo_story.py`: isolated fictional demo fixtures.
- `artifacts/showcase/`: finished video, narration and subtitle file.
