"""Streamlit Cloud entry point for the complete FairRoute desktop interface."""
import json
from pathlib import Path
import time

import streamlit as st
import streamlit.components.v1 as components
import server

st.set_page_config(page_title="FairRoute — A fairer way there", page_icon="🚏", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
[data-testid="stHeader"], [data-testid="stToolbar"] {display:none}
.block-container {padding:0!important;max-width:none!important}
[data-testid="stMainBlockContainer"] {padding:0!important}
[data-testid="stVerticalBlock"] {gap:0}
iframe {border:0;display:block}
</style>""", unsafe_allow_html=True)

desktop = components.declare_component("fairroute_desktop", path=str(Path(__file__).parent / "web"))


def dispatch(request):
    """Same Python engine as the local server; no public secondary port required."""
    if not isinstance(request, dict) or len(json.dumps(request)) > 20000:
        raise ValueError("Invalid request size.")
    path = request.get("path")
    payload = request.get("body") or {}
    if not isinstance(payload, dict):
        raise ValueError("Invalid settings.")
    if path == "bootstrap":
        return server.bootstrap()
    if path == "network":
        return [dict(path=s["path"], color=server.router().routes.get(s["route"], {}).get("color", "#888"),
                     name=server.router().routes.get(s["route"], {}).get("short_name", s["route"]))
                for s in server.router().route_shapes()]
    if path == "search": return server.search_api(payload)
    if path == "journey": return server.journey_api(payload)
    if path == "gaps": return server.gaps_api(str(payload.get("category", "Food assistance")), str(payload.get("profile", "typical")))
    if path == "planning": return server.planning_api(payload.get("budget", 24))
    if path == "scenario": return server.scenario_api(str(payload.get("intervention", "")))
    if path == "assistant":
        now = time.monotonic()
        if now - st.session_state.get("assistant_last_request", -100) < 3:
            raise ValueError("Please wait a moment before asking again.")
        st.session_state.assistant_last_request = now
        return server.assistant_api(payload)
    raise ValueError("Unknown app action.")


request = desktop(response=st.session_state.get("desktop_response"), key="fairroute", default=None)
if request and request.get("id") != st.session_state.get("desktop_completed"):
    request_id = request.get("id")
    try:
        response = {"id": request_id, "data": dispatch(request)}
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        response = {"id": request_id, "error": str(error) or "Invalid settings."}
    except Exception:
        response = {"id": request_id, "error": "The calculation could not finish. Please try again."}
    st.session_state.desktop_completed = request_id
    st.session_state.desktop_response = response
    st.rerun()
