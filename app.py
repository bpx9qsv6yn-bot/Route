from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

from fairroute import StreetRouter, TransitRouter, evaluate_resource, with_literal_street_legs
from planner import (
    INTERVENTIONS,
    MOBILITY_PROFILES,
    evaluate_manual_intervention,
    optimize_interventions,
    profile_access_grid,
    summarize_grid,
    synthetic_origins,
)
from resource_adapter import combine_with_curated, fetch_fci_resources
from journey import SORT_OPTIONS, category_matches, itinerary_steps, option_result, rank_results, schedule_notice, trip_summary


ROOT = Path(__file__).parent
DATA = ROOT / "data"
PAPER = [248, 247, 242]
INK = [24, 27, 25]
GRAY = [132, 134, 128]
BURDEN_COLORS = {
    "low": [47, 158, 108],
    "moderate": [244, 185, 43],
    "high": [225, 72, 62],
    "uncertain": [225, 112, 47],
    "unreachable": [151, 148, 139],
}
PROFILE_COLORS = {
    "typical": [42, 111, 187],
    "limited": [225, 112, 47],
    "mobility_device": [145, 91, 166],
}


st.set_page_config(page_title="FairRoute Gainesville", page_icon="●", layout="wide", initial_sidebar_state="collapsed")
st.markdown(f"<style>{(ROOT / 'assets' / 'styles.css').read_text()}</style>", unsafe_allow_html=True)


@st.cache_data(ttl=3600, show_spinner=False)
def load_catalog(schema_version: int = 2) -> tuple[pd.DataFrame, dict]:
    curated = pd.read_csv(DATA / "resources.csv", dtype=str).fillna("")
    try:
        fci, metadata = fetch_fci_resources()
        catalog = combine_with_curated(fci, curated)
        metadata["status"] = "connected"
        metadata["supplement_count"] = len(catalog) - len(fci)
    except Exception as error:
        catalog = combine_with_curated(pd.DataFrame(), curated)
        metadata = {
            "status": "fallback",
            "loaded": 0,
            "reported_total": 0,
            "supplement_count": len(catalog),
            "query_scope": "Public directory temporarily unavailable",
            "error": type(error).__name__,
        }
    return catalog.fillna(""), metadata


@st.cache_data
def load_locations() -> pd.DataFrame:
    frame = pd.read_csv(DATA / "start_locations.csv")
    frame["label"] = frame["name"] + " · " + frame["area"]
    return frame


@st.cache_resource
def load_router() -> TransitRouter:
    return TransitRouter.from_json(DATA / "transit_network.json")


@st.cache_resource
def load_street_router() -> StreetRouter:
    return StreetRouter.from_json(DATA / "street_network.json")


def rgb_css(color: list[int]) -> str:
    return f"rgb({color[0]},{color[1]},{color[2]})"


def hex_rgb(value: str, alpha: int | None = None) -> list[int]:
    value = value.lstrip("#")
    color = [int(value[index : index + 2], 16) for index in (0, 2, 4)] if len(value) == 6 else [42, 111, 187]
    return [*color, alpha] if alpha is not None else color


def route_color(router: TransitRouter, route_id: str, alpha: int | None = None) -> list[int]:
    return hex_rgb(str(router.routes.get(route_id, {}).get("color", "#2A6FBB")), alpha)


def page_intro(kicker: str, title: str, copy: str, route_color: str = "var(--blue)") -> None:
    st.markdown(
        f'<section class="page-intro" style="--route:{route_color}"><div>'
        f'<div class="page-kicker">{html.escape(kicker)}</div>'
        f'<h1 class="page-title">{html.escape(title)}</h1></div>'
        f'<p class="page-copy">{html.escape(copy)}</p></section>',
        unsafe_allow_html=True,
    )


def status_strip(items: list[tuple[str, int | str, list[int]]]) -> None:
    parts = ['<div class="status-strip">']
    for label, value, color in items:
        parts.append(
            f'<div class="status-stat" style="--status:{rgb_css(color)}">'
            f'<span class="status-node"></span><span class="status-value">{html.escape(str(value))}</span>'
            f'<span class="status-label">{html.escape(label)}</span></div>'
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)




def network_layers(router: TransitRouter, opacity: int = 75, selected_routes: set[str] | None = None) -> list[pdk.Layer]:
    shapes = []
    for shape in router.route_shapes(selected_routes):
        color = route_color(router, shape["route"], opacity)
        shapes.append({"path": shape["path"], "color": color, "route": router.routes.get(shape["route"], {}).get("short_name", shape["route"])})
    layers = [
        pdk.Layer(
            "PathLayer",
            data=shapes,
            get_path="path",
            get_color="color",
            get_width=5 if selected_routes else 2,
            width_min_pixels=4 if selected_routes else 1,
            joint_rounded=True,
            cap_rounded=True,
            pickable=True,
        )
    ]
    if selected_routes:
        stop_ids = {stop_id for (stop_id, route_id) in router.outgoing if route_id in selected_routes}
        stops = [{**router.stops[stop_id], "color": INK} for stop_id in stop_ids]
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=stops,
                get_position="[lon, lat]",
                get_fill_color=PAPER,
                get_line_color="color",
                get_radius=38,
                radius_min_pixels=2,
                radius_max_pixels=5,
                stroked=True,
                line_width_min_pixels=2,
            )
        )
    return layers


def map_view_state(points: list[tuple[float, float]], default_zoom: float = 12.0) -> pdk.ViewState:
    """Frame the visible story instead of forcing every trip into one fixed zoom."""
    if not points:
        return pdk.ViewState(latitude=29.66, longitude=-82.35, zoom=default_zoom)
    latitudes = [point[0] for point in points]
    longitudes = [point[1] for point in points]
    span = max(max(latitudes) - min(latitudes), max(longitudes) - min(longitudes))
    if span <= 0.018:
        zoom = 13.6
    elif span <= 0.04:
        zoom = 12.7
    elif span <= 0.075:
        zoom = 11.8
    elif span <= 0.13:
        zoom = 10.9
    else:
        zoom = 10.2
    return pdk.ViewState(
        latitude=(min(latitudes) + max(latitudes)) / 2,
        longitude=(min(longitudes) + max(longitudes)) / 2,
        zoom=zoom,
    )


def option_sentence(option) -> str:
    access = f"{round(option.walking_minutes)} min walk/roll" if option.walking_minutes else "no walking segment"
    if option.mode == "RTS":
        routes = " → ".join(option.routes)
        transfer = "direct" if option.transfers == 0 else f"{option.transfers} transfer{'s' if option.transfers != 1 else ''}"
        return f"RTS {routes} · {transfer} · {access} · {round(option.wait_minutes)} min expected wait"
    distance = f" · {option.distance_miles:.1f} mi" if option.distance_miles is not None else ""
    return f"{option.mode} · {access if option.mode == 'Walk' else f'{option.minutes} min'}{distance}"


def all_categories(resources: pd.DataFrame) -> list[str]:
    values = set()
    for categories in resources["categories"]:
        values.update(part for part in str(categories).split("|") if part)
    return sorted(values)


def run_search(search: dict, resources: pd.DataFrame, router: TransitRouter) -> list[dict]:
    origin = search["origin"]
    transit_plan = None
    if "RTS bus" in search["modes"]:
        transit_plan = router.build_plan(
            origin,
            search["max_walk"],
            search["walk_speed"],
            wheelchair_needed=search["wheelchair_transit"],
            max_minutes=search["max_minutes"] + 40,
        )
    candidates = resources
    if search["search_mode"] in {"By name", "Specific resource"}:
        candidates = candidates[candidates["resource_id"] == search["resource_id"]]
    elif search["category"] != "All resource types":
        candidates = candidates[candidates.apply(lambda row: category_matches(row, search["category"]), axis=1)]
    rows = [
        evaluate_resource(
            row.to_dict(),
            origin,
            search["modes"],
            search["max_walk"],
            search["max_minutes"],
            search["walk_speed"],
            search["access_needs"],
            router,
            transit_plan,
            search["wheelchair_transit"],
        )
        for _, row in candidates.iterrows()
    ]
    status_order = {"reachable": 0, "confirm": 1, "does_not_match": 2, "outside_limit": 3}
    rows.sort(key=lambda row: (status_order[row["status"]], row["burden"]["points"] if row["burden"] else 999, row["name"]))
    return rows


def select_map_resource(map_key: str) -> None:
    selection = st.session_state.get(map_key, {}).get("selection", {}).get("objects", {})
    points = selection.get("resource-stations", [])
    if points:
        st.session_state["selected_resource_id"] = points[0]["resource_id"]
    else:
        st.session_state.pop("selected_resource_id", None)


def trip_map(origin: tuple[float, float], origin_name: str, rows: list[dict], router: TransitRouter,
             selected: dict | None = None, show_network: bool = False) -> None:
    paths = []
    journey_stops = []
    bounds = [origin]
    if selected and selected["best_option"]:
        option = with_literal_street_legs(selected["best_option"], load_street_router(),
            wheelchair=bool(st.session_state.get("active_search", {}).get("wheelchair_transit")))
        for leg in option.legs:
            color = route_color(router, leg.route_id) if leg.kind == "bus" else ([229,176,39] if leg.kind == "bike" else [48,151,116])
            paths.append({"path": list(leg.geometry), "color": color,
                          "name": html.escape(leg.label), "detail": html.escape(leg.geometry_source)})
            bounds.extend((lat, lon) for lon, lat in leg.geometry)
            for stop_id in (leg.from_stop_id, leg.to_stop_id):
                if stop_id and stop_id in router.stops:
                    stop = router.stops[stop_id]
                    journey_stops.append({"position": [stop["lon"], stop["lat"]], "name": html.escape(stop["name"]), "detail": "Journey stop"})
    else:
        bounds.extend((float(row["latitude"]), float(row["longitude"])) for row in rows)
    stations = []
    for index, row in enumerate(rows, 1):
        is_selected = bool(selected and row["resource_id"] == selected["resource_id"])
        stations.append({"resource_id": row["resource_id"], "position": [float(row["longitude"]), float(row["latitude"])],
            "name": html.escape(row["name"]), "detail": f"{row['best_option'].minutes} min · burden {row['burden']['points']}/100" if row["best_option"] else "Outside selected limits",
            "color": BURDEN_COLORS[row["burden"]["key"]] if row["burden"] else GRAY,
            "fill": INK if is_selected else PAPER, "size": 12 if is_selected else 8,
            "number": str(index), "text_color": PAPER if is_selected else INK})
    layers = []
    if show_network:
        context = network_layers(router, 45)
        for index, layer in enumerate(context):
            layer.id = f"network-{index}"
        layers.extend(context)
    layers.extend([
        pdk.Layer("PathLayer", id="selected-route", data=paths, get_path="path", get_color="color", get_width=6,
                  width_units="'pixels'", joint_rounded=True, cap_rounded=True, pickable=False),
        pdk.Layer("ScatterplotLayer", id="journey-stops", data=journey_stops, get_position="position", get_radius=5,
                  radius_units="'pixels'", get_fill_color=PAPER, get_line_color=INK, stroked=True, line_width_min_pixels=2),
        pdk.Layer("ScatterplotLayer", id="resource-stations", data=stations, get_position="position", get_radius="size",
                  radius_units="'pixels'", get_fill_color="fill", get_line_color="color", stroked=True, line_width_min_pixels=3, pickable=True, auto_highlight=True),
        pdk.Layer("TextLayer", id="station-numbers", data=stations, get_position="position", get_text="number", get_color="text_color", get_size=10, get_text_anchor="'middle'", get_alignment_baseline="'center'"),
        pdk.Layer("ScatterplotLayer", id="starting-point", data=[{"position": [origin[1], origin[0]]}], get_position="position",
                  get_radius=9, radius_units="'pixels'", get_fill_color=INK, get_line_color=PAPER, stroked=True, line_width_min_pixels=3),
    ])
    map_key = "resource_map_" + (str(selected["resource_id"]) if selected else "overview")
    st.pydeck_chart(pdk.Deck(map_style=None, initial_view_state=map_view_state(bounds), layers=layers,
        tooltip={"html": "<b>{name}</b><br/>{detail}", "style": {"backgroundColor": "#242827", "color": "white", "fontSize": "12px"}}),
        width="stretch", height=650, key=map_key, on_select=lambda: select_map_resource(map_key), selection_mode="single-object")








def render_journey(row: dict, search: dict, router: TransitRouter) -> None:
    option = row["best_option"]
    st.markdown(f'<div class="journey-heading"><div class="eyebrow">YOUR DESTINATION</div><h3>{html.escape(row["name"])}</h3><div class="trip-total">{option.minutes}<small> min estimated</small></div></div>', unsafe_allow_html=True)
    st.caption(f"{row['burden']['points']}/100 burden · {option.walking_minutes:.0f} min walk / roll · {option.transfers} transfers")
    parts = ['<ol class="journey-line">']
    for step in itinerary_steps(option, router):
        color = "var(--blue)" if step["kind"] == "bus" else ("var(--yellow)" if step["kind"] == "bike" else "var(--green)")
        parts.append(f'<li style="--route:{color}"><strong>{html.escape(step["label"])}</strong><span>{step["minutes"]} min</span><p>{html.escape(step["detail"])}</p></li>')
    st.markdown("".join(parts) + '</ol>', unsafe_allow_html=True)
    if option.wait_minutes:
        st.caption(f"Includes about {option.wait_minutes:.0f} min of expected waiting. Step times exclude waiting and are rounded.")
    st.markdown("**Before you go**")
    st.caption(f"{row['address']} · {row.get('hours') or 'Confirm opening hours'}")
    if search["access_needs"] or search["wheelchair_transit"]:
        if row["confirmation_reasons"]:
            st.warning("Confirm access: " + ", ".join(row["confirmation_reasons"]) + ". " + str(row.get("accessibility_notes") or "Contact the service before traveling."))
        else:
            st.caption("The model has no flagged uncertainty for your selected access requirements. Verify current conditions before traveling.")
    else:
        st.caption("No facility access needs selected. This does not establish that the facility is accessible to you.")
    st.caption("Confirm hours, eligibility, availability, and any documents you need.")
    if row.get("phone"):
        st.link_button(f"Call {row['phone']}", f"tel:{row['phone']}", width="stretch")
    if row.get("website"):
        st.link_button("Visit service website ↗", row["website"], width="stretch")




def search_view(resources: pd.DataFrame, metadata: dict, locations: pd.DataFrame, router: TransitRouter) -> None:
    prefs = st.session_state.get("finder_preferences", {})
    fallback = metadata["status"] != "connected"
    demo_enabled = fallback or st.session_state.get("finder_demo", prefs.get("demo", False))
    visible_catalog = resources if demo_enabled else resources[~resources["source"].str.contains("demonstration", case=False, na=False)]
    panel, map_area = st.columns([1, 2.65], gap="large")
    with panel, st.container(key="finder_rail"):
        st.markdown('<div class="finder-heading"><span class="eyebrow">GAINESVILLE · RESOURCE FINDER</span><h2>Where to?</h2></div>', unsafe_allow_html=True)
        categories = all_categories(visible_catalog) or ["All resource types"]
        lookup = {f"category:{category}": category for category in categories}
        lookup.update({f"resource:{row['resource_id']}": str(row["name"]) for _, row in visible_catalog.sort_values("name").iterrows()})
        target = st.selectbox("What do you need?", list(lookup),
            index=list(lookup).index(prefs["target"]) if prefs.get("target") in lookup else (list(lookup).index("category:Food assistance") if "category:Food assistance" in lookup else 0),
            format_func=lambda value: lookup[value], key="finder_target", help="Type to find a category or a specific service.")
        starting_places = locations["label"].tolist() + ["Use temporary coordinates…"]
        location_label = st.selectbox("Starting from", starting_places, index=starting_places.index(prefs["start"]) if prefs.get("start") in starting_places else 0, key="finder_start")
        if location_label == "Use temporary coordinates…":
            lat_col, lon_col = st.columns(2)
            latitude = lat_col.number_input("Latitude", -90.0, 90.0, prefs.get("lat") or 29.6516, format="%.6f", key="finder_lat")
            longitude = lon_col.number_input("Longitude", -180.0, 180.0, prefs.get("lon") or -82.3248, format="%.6f", key="finder_lon")
            origin, origin_name = (latitude, longitude), "Temporary starting point"
            if st.button("Clear my location", width="stretch"):
                for key in ("finder_start", "finder_lat", "finder_lon", "active_search", "search_cache", "selected_resource_id", "finder_preferences"):
                    st.session_state.pop(key, None)
                st.rerun()
        else:
            place = locations.loc[locations["label"] == location_label].iloc[0]
            origin, origin_name = (float(place["latitude"]), float(place["longitude"])), str(place["name"])
        with st.expander("Travel & accessibility", expanded=False):
            modes = st.multiselect("Travel modes", ["RTS bus", "Walk", "Bike / micromobility"], default=prefs.get("modes", ["RTS bus", "Walk"]), key="finder_modes")
            max_minutes = st.slider("Maximum trip", 15, 90, prefs.get("minutes", 45), 5, format="%d min", key="finder_minutes")
            max_walk = st.select_slider("Maximum walk / roll at one time", [0.1,0.15,0.25,0.5,0.75,1.0], value=prefs.get("walk", 0.5), format_func=lambda value: f"{value:g} mi", key="finder_walk")
            pace = st.selectbox("Walking / rolling pace", ["Typical · 3 mph", "Slower · 2 mph", "Limited · 1.25 mph"], index=prefs.get("pace", 0), key="finder_pace")
            walk_speed = {"Typical · 3 mph": 3.0, "Slower · 2 mph": 2.0, "Limited · 1.25 mph": 1.25}[pace]
            wheelchair_transit = st.checkbox("Mobility-device-compatible transit required", value=prefs.get("wheelchair", False), key="finder_wheelchair")
            access_needs = st.multiselect("Facility features needed", ["Step-free entrance", "Accessible restroom"], default=prefs.get("needs", []), key="finder_needs")
            confirmed_only = st.checkbox("Only confirmed facility access", value=prefs.get("confirmed", False), disabled=not access_needs, key="finder_confirmed")
            include_demo = st.toggle("Include demonstration records", value=demo_enabled, disabled=fallback, key="finder_demo_fallback" if fallback else "finder_demo")
        search = {"origin": origin, "origin_name": origin_name, "search_mode": "By name" if target.startswith("resource:") else "By need",
            "category": lookup[target] if target.startswith("category:") else "All resource types", "resource_id": target.split(":",1)[1] if target.startswith("resource:") else "",
            "modes": modes, "max_minutes": max_minutes, "max_walk": max_walk, "walk_speed": walk_speed,
            "wheelchair_transit": wheelchair_transit, "access_needs": access_needs, "confirmed_only": confirmed_only}
        st.session_state["active_search"] = search
        catalog = resources if include_demo else resources[~resources["source"].str.contains("demonstration", case=False, na=False)]
        st.caption(f"{max_minutes} min max · {max_walk:g} mi walk / roll · " + (", ".join(modes) if modes else "Choose a travel mode"))
        fingerprint = json.dumps(search, sort_keys=True) + catalog.to_json(orient="records")
        cache = st.session_state.get("search_cache", {})
        if cache.get("input") != fingerprint:
            with st.spinner("Finding reachable services…"):
                rows = run_search(search, catalog, router) if modes and not catalog.empty else []
            st.session_state["search_cache"] = {"input": fingerprint, "rows": rows}
            st.session_state.pop("selected_resource_id", None)
        else:
            rows = cache["rows"]
        sort = st.selectbox("Sort matches", SORT_OPTIONS, label_visibility="collapsed", index=list(SORT_OPTIONS).index(prefs.get("sort", SORT_OPTIONS[0])), key="finder_sort")
        st.session_state["finder_preferences"] = {"target": target, "start": location_label,
            "lat": origin[0] if origin_name == "Temporary starting point" else None,
            "lon": origin[1] if origin_name == "Temporary starting point" else None,
            "modes": modes, "minutes": max_minutes, "walk": max_walk,
            "pace": ["Typical · 3 mph", "Slower · 2 mph", "Limited · 1.25 mph"].index(pace),
            "wheelchair": wheelchair_transit, "needs": access_needs, "confirmed": confirmed_only,
            "demo": include_demo, "sort": sort}
        ranked = rank_results(rows, sort, wheelchair_transit)
        hidden_uncertain = sum(row["status"] == "confirm" for row in ranked) if confirmed_only and access_needs else 0
        if confirmed_only and access_needs:
            ranked = [row for row in ranked if row["status"] == "reachable"]
        by_id = {row["resource_id"]: row for row in ranked}
        selected = by_id.get(st.session_state.get("selected_resource_id"))
        if selected:
            if st.button("← All matches", width="stretch"):
                st.session_state.pop("selected_resource_id", None)
                st.rerun()
            choices = [option_result(selected, option, wheelchair_transit) for option in selected["travel_options"]]
            if confirmed_only and access_needs:
                choices = [row for row in choices if row["status"] == "reachable"]
            if len(choices) > 1:
                default = next(i for i, row in enumerate(choices) if row["best_option"] == selected["best_option"])
                option_index = st.selectbox("Travel option", list(range(len(choices))), index=default,
                    format_func=lambda i: f"{choices[i]['best_option'].mode} · {choices[i]['best_option'].minutes} min · {choices[i]['burden']['points']}/100 burden" + (" · confirm access" if choices[i]["status"] == "confirm" else ""))
                selected = choices[option_index]
            render_journey(selected, search, router)
            with st.expander("About this service"):
                st.write(selected.get("description") or "Contact the provider for service details.")
                st.caption(f"Source: {selected.get('source', 'Not listed')} · Updated: {selected.get('source_checked') or 'Unknown'}")
            with st.expander("Why this burden score?"):
                for label, value in selected["burden"]["breakdown"].items():
                    st.caption(f"{label.replace('_',' ').capitalize()}: {value:g} pts")
                st.caption("Prototype policy weights, not a clinical assessment. Lower means less effort.")
            st.download_button("Save trip summary ↓", trip_summary(search, selected, router), file_name="fairroute-trip.txt", mime="text/plain", width="stretch")
        else:
            st.markdown(f'<div class="match-heading"><strong>{len(ranked)} matches</strong><span>Choose a service or a map station</span></div>', unsafe_allow_html=True)
            if not modes:
                st.info("Choose a travel mode in Travel & accessibility.")
            elif not ranked:
                st.info("No services fit these settings. Try another need, starting point, or travel mode. Keep your essential access requirements.")
            for index, row in enumerate(ranked, 1):
                with st.container(key=f"match_{row['resource_id']}"):
                    option = row["best_option"]
                    if st.button(f"{index:02d}  {row['name']}", key=f"choose_{row['resource_id']}", width="stretch"):
                        st.session_state["selected_resource_id"] = row["resource_id"]
                        st.rerun()
                    st.markdown(f'<div class="match-meta"><strong>{option.minutes} min</strong><span>{html.escape(option.mode)} · {option.walking_minutes:.0f} min walk / roll</span><span class="match-score">{row["burden"]["points"]}<small>/100 effort</small></span></div>', unsafe_allow_html=True)
                    description = str(row.get("description") or "")
                    if description:
                        st.caption(description[:110] + ("…" if len(description) > 110 else ""))
                    if "demonstration" in str(row.get("source", "")).lower():
                        st.caption("Demonstration record")
                    if row["status"] == "confirm":
                        st.caption("△ Confirm selected access needs")
            unavailable = [row for row in rows if row["status"] in {"outside_limit", "does_not_match"}]
            if hidden_uncertain:
                st.caption(f"{hidden_uncertain} trips hidden: required access is unconfirmed.")
            if unavailable:
                with st.expander(f"{len(unavailable)} services do not fit"):
                    for row in unavailable:
                        st.markdown(f"**{row['name']}**")
                        st.caption(row.get("unavailable_reason", "Does not fit the selected trip or access limits."))
        st.caption("Private session · no account or saved location history.")
    with map_area:
        if metadata["status"] != "connected":
            st.warning("Demo mode · the live directory is unavailable.")
        st.markdown(f'<div class="map-topline"><span class="map-shell">{html.escape(selected["name"] if selected else "Your connections")}</span><span>{len(ranked)} matches · Gainesville, FL</span></div>', unsafe_allow_html=True)
        show_network = st.toggle("RTS network", value=True, help="Show scheduled routes around your search.")
        trip_map(origin, origin_name, ranked, router, selected=selected, show_network=show_network)
        st.markdown('<div class="legend"><span>● Starting point</span><span>① Service · click to inspect</span><span style="color:#23815e">━ Walk / roll</span><span>Colored lines · RTS routes</span></div>', unsafe_allow_html=True)
        st.caption(f"Starting from {origin_name}. " + ("Temporary coordinates stay in this session." if origin_name == "Temporary starting point" else "This is a public preset, not your detected location."))
        if "RTS bus" in modes:
            st.caption(schedule_notice(router.meta))
        with st.expander("Map & data coverage"):
            st.caption(f"{len(catalog)} records in this search catalog. " + ("Includes labeled demonstration records." if include_demo else "Live directory records only; demonstration records are off."))
            st.caption("Geographic routes follow local OpenStreetMap paths and RTS shapes. Short entrance connections may be estimated. Path data does not verify curb cuts or surface conditions.")
            st.caption("Basemap: © CARTO, © OpenStreetMap contributors. Map providers receive the viewed area and browser IP; your origin is not sent to the resource directory.")
            if metadata["status"] != "connected":
                st.warning("The live directory is unavailable. This session uses demonstration records.")


@st.cache_data(ttl=3600, show_spinner=False)
def cached_gap_payload(resource_json: str, category: str) -> dict:
    router = TransitRouter.from_json(DATA / "transit_network.json")
    resource_records = json.loads(resource_json)
    origins = synthetic_origins(router)
    profiles = {}
    for profile in MOBILITY_PROFILES:
        rows = profile_access_grid(router, resource_records, origins, profile, category=category, max_minutes=30)
        profiles[profile.id] = {"rows": rows, "summary": summarize_grid(rows), "label": profile.label}
    return {"origins": origins, "profiles": profiles}


def access_color(value: float) -> list[int]:
    if value <= 0:
        return [225, 72, 62]
    if value < 25:
        return [225, 112, 47]
    if value < 50:
        return [244, 185, 43]
    return [47, 158, 108]


def gap_map(rows: list[dict], router: TransitRouter) -> None:
    points = []
    for row in rows:
        color = access_color(row["resource_share"])
        points.append(
            {
                **row,
                "color": color,
                "fill": PAPER if row["uncertain_count"] else color,
                "detail": f"{row['resource_share']:.0f}% of resources reachable · {row['uncertain_count']} access records uncertain",
                "radius": 120 + min(row["resource_share"], 60) * 2,
            }
        )
    st.pydeck_chart(
        pdk.Deck(
            map_style=None,
            initial_view_state=pdk.ViewState(latitude=29.66, longitude=-82.35, zoom=10.8),
            layers=[
                *network_layers(router, 55),
                pdk.Layer("ScatterplotLayer", data=points, get_position="[lon, lat]", get_fill_color="fill", get_line_color="color", get_radius="radius", radius_min_pixels=8, radius_max_pixels=20, stroked=True, line_width_min_pixels=6, pickable=True),
                pdk.Layer("TextLayer", data=points, get_position="[lon, lat]", get_text="id", get_color=INK, get_size=11, get_text_anchor="'middle'", get_alignment_baseline="'center'"),
            ],
            tooltip={
                "html": "<b>{name}</b><br/>{detail}",
                "style": {"backgroundColor": "#181b19", "color": "#fffefa", "borderRadius": "12px", "padding": "10px 12px", "fontSize": "13px"},
            },
        ),
        width="stretch",
        height=610,
    )


def profile_cards(profiles: dict, selected_id: str) -> None:
    parts = ['<div class="profile-list">']
    for profile in MOBILITY_PROFILES:
        result = profiles[profile.id]
        summary = result["summary"]
        color = rgb_css(PROFILE_COLORS[profile.id])
        selected = " active" if profile.id == selected_id else ""
        parts.append(
            f'<div class="profile-row{selected}" style="--profile:{color}"><span class="profile-dot"></span>'
            f'<div class="profile-copy"><strong>{html.escape(profile.label)}</strong>'
            f'<span>{summary["mean_resource_share"]:.0f}% average resource share</span></div>'
            f'<div class="profile-value">{summary["cell_access_percent"]:.0f}%</div></div>'
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def gaps_view(resources: pd.DataFrame, router: TransitRouter) -> None:
    categories = all_categories(resources)
    page_intro(
        "LINE 02 · COMMUNITY ACCESS",
        "See where access falls short.",
        "FairRoute tests anonymous grid origins across the RTS service area. Switch profiles to reveal where nominal proximity fails to become practical access.",
        "var(--red)",
    )
    controls = st.columns([1, 2], gap="large")
    with controls[0]:
        category = st.selectbox("Essential resource type", categories, index=categories.index("Food assistance") if "Food assistance" in categories else 0)
    with st.spinner("Running the 30-minute test across the city…"):
        payload = cached_gap_payload(resources.to_json(orient="records"), category)
    profile_labels = {profile.label: profile.id for profile in MOBILITY_PROFILES}
    with controls[1]:
        selected_label = st.segmented_control(
            "Mobility profile",
            list(profile_labels),
            default=list(profile_labels)[0],
            key="gap_profile",
        )
    selected_id = profile_labels.get(selected_label, "typical")
    profiles = payload["profiles"]
    typical = profiles["typical"]["summary"]
    selected = profiles[selected_id]["summary"]
    lost_cells = typical["cells_with_access"] - selected["cells_with_access"]
    if selected_id == "typical":
        change_copy = "This is the baseline profile for comparison."
    elif lost_cells > 0:
        change_copy = f"{lost_cells} fewer grid cells meet the threshold than under typical walking and transit."
    elif lost_cells < 0:
        change_copy = f"{-lost_cells} more grid cells meet the threshold than under typical walking and transit."
    else:
        change_copy = "The number of qualifying grid cells is unchanged from the typical profile."
    insight, map_column = st.columns([0.82, 2.18], gap="large")
    with insight:
        st.markdown(
            f'<div class="city-reveal" style="--profile:{rgb_css(PROFILE_COLORS[selected_id])}">'
            f'<div class="page-kicker">Citywide reveal · {len(payload["origins"])} cells</div>'
            f'<div class="city-number">{selected["cell_access_percent"]:.0f}%</div>'
            f'<div class="city-statement">can reach {html.escape(category.lower())} within 30 minutes</div>'
            f'<div class="city-detail">{html.escape(change_copy)} Hollow stations preserve uncertainty instead of implying confirmed access.</div></div>',
            unsafe_allow_html=True,
        )
        profile_cards(profiles, selected_id)
    with map_column:
        st.markdown('<div class="map-shell">Gainesville accessibility inequality map</div>', unsafe_allow_html=True)
        gap_map(profiles[selected_id]["rows"], router)
    st.caption("This research view includes live directory and labeled demonstration records.")
    st.caption("Each station is a generated test origin located in a grid cell containing RTS service—not a resident search or population claim. Route lines follow literal GTFS shapes. Basemap: [© OpenStreetMap contributors](https://www.openstreetmap.org/copyright).")
    st.markdown("## The measurable gap")
    table_rows = []
    for profile in MOBILITY_PROFILES:
        summary = profiles[profile.id]["summary"]
        table_rows.append(
            f'<tr><td>{html.escape(profiles[profile.id]["label"])}</td>'
            f'<td>{summary["cell_access_percent"]:.0f}%</td>'
            f'<td>{summary["mean_resource_share"]:.0f}%</td>'
            f'<td>{summary["mean_confirmed_share"]:.0f}%</td></tr>'
        )
    st.markdown(
        '<table class="measure-table"><thead><tr><th>Mobility profile</th><th>Origins with access</th>'
        '<th>Average resource share</th><th>Confirmed-access share</th></tr></thead><tbody>'
        + "".join(table_rows)
        + "</tbody></table>",
        unsafe_allow_html=True,
    )
    st.info("A low confirmed-access share can reveal a data gap as well as a transportation gap. FairRoute keeps those two failures separate.")


def intervention_summary(result: dict) -> None:
    intervention = result["intervention"]
    parts = [
        f'<div class="intervention-card" style="--route:{intervention["color"]}">'
        f'<div class="page-kicker">Selected what-if · {intervention["cost_units"]} illustrative budget units</div>'
        f'<h3>{html.escape(intervention["label"])}</h3><p>{html.escape(intervention["rationale"])}</p></div>',
        '<div class="profile-list">',
    ]
    for profile in MOBILITY_PROFILES:
        profile_result = result["profiles"][profile.id]
        before = profile_result["before_summary"]
        after = profile_result["after_summary"]
        delta = after["cell_access_percent"] - before["cell_access_percent"]
        extra_cells = after["cells_with_access"] - before["cells_with_access"]
        color = rgb_css(PROFILE_COLORS[profile.id])
        parts.append(
            f'<div class="profile-row" style="--profile:{color}"><span class="profile-dot"></span>'
            f'<div class="profile-copy"><strong>{html.escape(profile.label)}</strong>'
            f'<span>{extra_cells:+d} cells meet the 30-minute threshold</span></div>'
            f'<div class="delta">{delta:+.0f} pts</div></div>'
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def intervention_map(result: dict, router: TransitRouter, profile_id: str) -> None:
    profile = result["profiles"][profile_id]
    before = {row["id"]: row for row in profile["before"]}
    points = []
    for row in profile["after"]:
        delta = row["resource_share"] - before[row["id"]]["resource_share"]
        color = [47, 158, 108] if delta > 0 else ([225, 72, 62] if delta < 0 else GRAY)
        points.append({**row, "delta": delta, "color": color, "detail": f"{row['resource_share']:.0f}% after · {delta:+.0f} points", "radius": 115 + abs(delta) * 3})
    route_ids = {result["intervention"]["route_id"]} if result["intervention"]["kind"] == "frequency" else set()
    layers = [*network_layers(router, 45)]
    if route_ids:
        layers.extend(network_layers(router, 245, route_ids))
    mobility_hub = result.get("mobility_hub")
    hub_points = []
    if mobility_hub:
        hub_points.append(
            {
                "name": result["intervention"]["target_location"],
                "detail": "Proposed micromobility hub",
                "lat": mobility_hub[0],
                "lon": mobility_hub[1],
                "color": hex_rgb(result["intervention"]["color"]),
                "radius": 240,
            }
        )
    layers.extend(
        [
            pdk.Layer("ScatterplotLayer", data=points, get_position="[lon, lat]", get_fill_color=PAPER, get_line_color="color", get_radius="radius", radius_min_pixels=8, radius_max_pixels=22, stroked=True, line_width_min_pixels=6, pickable=True),
            pdk.Layer("ScatterplotLayer", data=hub_points, get_position="[lon, lat]", get_fill_color="color", get_line_color=INK, get_radius="radius", radius_min_pixels=15, radius_max_pixels=28, stroked=True, line_width_min_pixels=5, pickable=True),
            pdk.Layer("TextLayer", data=points, get_position="[lon, lat]", get_text="id", get_color=INK, get_size=11, get_text_anchor="'middle'", get_alignment_baseline="'center'"),
        ]
    )
    st.pydeck_chart(
        pdk.Deck(
            map_style=None,
            initial_view_state=pdk.ViewState(latitude=29.66, longitude=-82.35, zoom=10.8),
            layers=layers,
            tooltip={
                "html": "<b>{name}</b><br/>{detail}",
                "style": {"backgroundColor": "#181b19", "color": "#fffefa", "borderRadius": "12px", "padding": "10px 12px", "fontSize": "13px"},
            },
        ),
        width="stretch",
        height=440,
    )


def planner_view(resources: pd.DataFrame, locations: pd.DataFrame, router: TransitRouter) -> None:
    page_intro(
        "LINE 03 · SCENARIO LAB · ILLUSTRATIVE ONLY",
        "Better connections. Broader access.",
        "Test a small intervention against the same 30-minute access measure. The model shows who benefits before any optimizer searches for a bundle.",
        "var(--orange)",
    )
    st.caption("Research scenario · includes labeled demonstration records. Costs and interventions are illustrative.")
    labels = {intervention.label: intervention for intervention in INTERVENTIONS}
    with st.form("manual_what_if"):
        label_options = list(labels)
        default_intervention = label_options.index("SWAG mobility hub") if "SWAG mobility hub" in label_options else 0
        form_columns = st.columns([3, 1], vertical_alignment="bottom")
        with form_columns[0]:
            selected_label = st.selectbox("Test an intervention", label_options, index=default_intervention)
        with form_columns[1]:
            submitted = st.form_submit_button("Recompute access", type="primary", width="stretch")
    if submitted:
        with st.spinner("Recomputing every synthetic origin before and after…"):
            st.session_state["manual_result"] = evaluate_manual_intervention(
                router,
                resources.to_dict(orient="records"),
                synthetic_origins(router),
                locations.to_dict(orient="records"),
                labels[selected_label],
            )
    result = st.session_state.get("manual_result")
    if result:
        profile_by_label = {profile.label: profile.id for profile in MOBILITY_PROFILES}
        summary_column, map_column = st.columns([0.82, 2.18], gap="large")
        with summary_column:
            intervention_summary(result)
        with map_column:
            selected_profile_label = st.segmented_control(
                "Inspect the before / after map",
                list(profile_by_label),
                default=list(profile_by_label)[0],
                key="planner_profile",
            )
            st.markdown('<div class="map-shell">Where access changes</div>', unsafe_allow_html=True)
            intervention_map(result, router, profile_by_label.get(selected_profile_label, "typical"))
        st.caption("Green stations improve, gray stations are unchanged, and red would indicate a loss. Candidate costs and interventions are illustrative—not RTS recommendations. Basemap: [© OpenStreetMap contributors](https://www.openstreetmap.org/copyright).")
    else:
        st.info("Choose one intervention to create a transparent before-and-after comparison.")

    with st.expander("Advanced: let the optimizer compare intervention bundles"):
        st.write("After the manual what-if is understandable, PuLP can search the six explicit candidates. Efficiency maximizes average category access; fairness also protects the lowest-served sample location.")
        budget = st.slider("Illustrative intervention budget", 12, 56, 28, 2)
        if st.button("Compare optimized bundles"):
            with st.spinner("Evaluating every feasible bundle…"):
                st.session_state["planner_result"] = optimize_interventions(router, resources.to_dict(orient="records"), locations.to_dict(orient="records"), budget)
        optimized = st.session_state.get("planner_result")
        if optimized:
            baseline = optimized["baseline"]
            efficiency = optimized["efficiency"]
            fairness = optimized["fairness"]
            table = pd.DataFrame(
                [
                    {"Objective": "Efficiency", "Average access": f"{efficiency['average_score']:.0f}%", "Lowest access": f"{efficiency['minimum_score']:.0f}%", "Interventions": ", ".join(item["label"] for item in efficiency["interventions"]) or "Baseline"},
                    {"Objective": "Fairness-aware", "Average access": f"{fairness['average_score']:.0f}%", "Lowest access": f"{fairness['minimum_score']:.0f}%", "Interventions": ", ".join(item["label"] for item in fairness["interventions"]) or "Baseline"},
                ]
            )
            st.dataframe(table, hide_index=True, width="stretch")
            st.caption(f"{optimized['scenario_count']} feasible bundles evaluated. Baseline average: {baseline['average_score']:.0f}%. Fairness formula: 55% mean access + 45% minimum access.")


def methods_view(resources: pd.DataFrame, metadata: dict, router: TransitRouter) -> None:
    street_router = load_street_router()
    page_intro(
        "LINE 04 · METHODS & PRIVACY",
        "Clarity at every step.",
        "The product separates source data, mobility calculations, burden policy, and citywide diagnosis so every conclusion can be traced.",
        "var(--purple)",
    )
    st.markdown(
        '<div class="method-rail">'
        '<div class="method-step" style="--route:var(--blue)"><strong>Directory</strong><span>FCI supplies what services exist. A resident origin is never sent upstream.</span></div>'
        '<div class="method-step" style="--route:var(--green)"><strong>Mobility</strong><span>Local OSM paths and official GTFS shapes produce inspectable trip geometry.</span></div>'
        '<div class="method-step" style="--route:var(--yellow)"><strong>Burden</strong><span>Time, walking or rolling, transfers, waiting, and unknowns become one visible measure.</span></div>'
        '<div class="method-step" style="--route:var(--purple)"><strong>Citywide</strong><span>Synthetic origins compare profiles without reusing anyone’s search history.</span></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown("### Current coverage")
    status_strip(
        [
            ("Routable FCI records", metadata.get("loaded", 0), PROFILE_COLORS["typical"]),
            ("Weekday RTS routes", len(router.routes), BURDEN_COLORS["low"]),
            ("GTFS route shapes", sum(len(values) for values in router.shapes_by_route.values()), BURDEN_COLORS["moderate"]),
            ("Local OSM nodes", f"{len(street_router.nodes) // 1000}k", PROFILE_COLORS["mobility_device"]),
        ]
    )
    st.write(f"The app adds {metadata.get('supplement_count', len(resources))} labeled, non-duplicate demonstration records. The transit derivative contains {len(router.stops):,} stops, and the active-travel graph contains {street_router.way_count:,} mapped ways.")
    st.caption(f"RTS feed version: {router.meta.get('feed_version', 'unknown')} · schedule end date: {router.meta.get('feed_end_date', 'unknown')}. This is a static schedule snapshot, not live service.")
    st.warning("This is not a guarantee that every Gainesville resource is listed, currently open, eligible, or accurately tagged. FCI remains the directory owner; FairRoute reports source and freshness so omissions stay visible.")
    privacy_column, ai_column = st.columns(2, gap="large")
    with privacy_column:
        with st.container(border=True):
            st.markdown("### Privacy boundary")
            st.write("No account, name, diagnosis, analytics identifier, or permanent location history is required. Search inputs live only in Streamlit session memory.")
            st.caption("OpenStreetMap tiles may receive the browser IP address and viewed map area. A production deployment should proxy or self-host tiles.")
    with ai_column:
        with st.container(border=True):
            st.markdown("### AI boundary")
            st.write("Gemini is intentionally not integrated yet. A future language layer may explain structured results or translate commands into validated parameters.")
            st.caption("Deterministic code calculates access. PuLP chooses optimization results.")


resources, catalog_metadata = load_catalog()
locations = load_locations()
router = load_router()

st.markdown(
    '<div class="brandbar"><div class="brand-lockup"><span class="brand-mark"></span><div>'
    '<span class="brand-name">FairRoute</span><span class="brand-tag">REAL-WORLD ACCESS · GAINESVILLE</span>'
    '</div></div><span class="privacy-status">Gainesville, FL</span></div>',
    unsafe_allow_html=True,
)
view = st.segmented_control(
    "Product mode",
    ["Find resources", "Access gaps", "Scenario lab", "About the data"],
    default="Find resources",
    required=True,
    label_visibility="collapsed",
    key="product_mode",
)

if view == "Find resources":
    with st.container(key="finder"):
        search_view(resources, catalog_metadata, locations, router)
elif view == "Access gaps":
    gaps_view(resources, router)
elif view == "Scenario lab":
    planner_view(resources, locations, router)
else:
    methods_view(resources, catalog_metadata, router)


st.markdown('<footer class="site-footer"><span><strong>FairRoute</strong> · Built around real-world access.</span><span>Gainesville, Florida · Research prototype</span></footer>', unsafe_allow_html=True)
