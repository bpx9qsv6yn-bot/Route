# FairRoute — A fairer way there

Desktop civic-access planning for Gainesville residents and caseworkers, using Florida Community Innovation resource data and Gainesville RTS transit data.

Deploy `streamlit_app.py` with Python 3.12 on Streamlit Community Cloud. Add `GEMINI_API_KEY` and `GEMINI_MODEL="gemini-3.5-flash"` to app secrets. The map, search, access evidence, guided example, citywide analysis and planning comparison all run without AI credentials.

`fairroute-source.zip` contains the complete readable application, tests, data, and handoff documentation. The launcher unpacks it locally on the server; no external backend or local computer is required. To develop, extract it and run `streamlit run streamlit_app.py`. Source is bundled to permit immediate browser upload without a local GitHub CLI login.

The access example uses fictional providers, explicitly labeled. Citywide samples and planning interventions are illustrative, not population statistics or accessibility certifications. See `docs/handoff.md` in the source bundle for sources, limitations, and maintenance.
