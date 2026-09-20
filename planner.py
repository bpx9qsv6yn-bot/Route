"""Small, transparent intervention optimizer built on FairRoute access scores."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from itertools import combinations
from statistics import mean
from typing import Iterable

import pulp
from pulp.apis.coin_api import pulp_cbc_path

from fairroute import TransitRouter, evaluate_resource, haversine_miles


@dataclass(frozen=True)
class Intervention:
    id: str
    kind: str
    label: str
    cost_units: int
    color: str
    rationale: str
    route_id: str = ""
    target_headway: float = 0
    target_location: str = ""


INTERVENTIONS = (
    Intervention("route-26", "frequency", "More Route 26 trips", 12, "#E84C3D", "Improve the long-wait link between downtown, GRACE, and the airport area.", route_id="26", target_headway=30),
    Intervention("route-7", "frequency", "More Route 7 trips", 12, "#349B68", "Strengthen the east Gainesville corridor to Eastwood Meadows.", route_id="7", target_headway=30),
    Intervention("route-15", "frequency", "More Route 15 trips", 14, "#F2B705", "Improve access along NW 13th Street and NW 23rd Avenue.", route_id="15", target_headway=20),
    Intervention("hub-santa-fe", "mobility_hub", "Santa Fe mobility hub", 12, "#2A6FBB", "Add a first/last-mile micromobility option at the northwest campus.", target_location="Santa Fe College NW Campus"),
    Intervention("hub-northwood", "mobility_hub", "Northwood mobility hub", 16, "#915BA6", "Add a first/last-mile micromobility option in north Gainesville.", target_location="Northwood neighborhood"),
    Intervention("hub-swag", "mobility_hub", "SWAG mobility hub", 12, "#E7782B", "Add a first/last-mile micromobility option near the family resource center.", target_location="SWAG Family Resource Center"),
)


@dataclass(frozen=True)
class MobilityProfile:
    id: str
    label: str
    max_walk_miles: float
    walk_speed_mph: float
    wheelchair_transit: bool = False
    access_needs: tuple[str, ...] = ()


MOBILITY_PROFILES = (
    MobilityProfile("typical", "Typical walking + RTS", 0.5, 3.0),
    MobilityProfile("limited", "Limited walking / rolling", 0.15, 1.25),
    MobilityProfile(
        "mobility_device",
        "Mobility-device requirements",
        0.15,
        1.25,
        wheelchair_transit=True,
        access_needs=("Step-free entrance",),
    ),
)


def synthetic_origins(router: TransitRouter, rows: int = 6, columns: int = 8) -> list[dict]:
    """Create anonymous citywide test points in cells that contain RTS stops."""
    stops = list(router.stops.values())
    latitudes = sorted(float(stop["lat"]) for stop in stops)
    longitudes = sorted(float(stop["lon"]) for stop in stops)
    # Trim extreme service points so one distant stop does not flatten the map.
    lower = max(0, round(len(stops) * 0.02))
    upper = min(len(stops) - 1, round(len(stops) * 0.98))
    min_lat, max_lat = latitudes[lower], latitudes[upper]
    min_lon, max_lon = longitudes[lower], longitudes[upper]
    lat_step = (max_lat - min_lat) / rows
    lon_step = (max_lon - min_lon) / columns
    origins = []
    for row in range(rows):
        for column in range(columns):
            south, north = min_lat + row * lat_step, min_lat + (row + 1) * lat_step
            west, east = min_lon + column * lon_step, min_lon + (column + 1) * lon_step
            stop_count = sum(
                south <= float(stop["lat"]) <= north and west <= float(stop["lon"]) <= east
                for stop in stops
            )
            if not stop_count:
                continue
            origins.append(
                {
                    "id": f"{chr(65 + row)}{column + 1}",
                    "name": f"Grid {chr(65 + row)}{column + 1}",
                    "lat": (south + north) / 2,
                    "lon": (west + east) / 2,
                    "stop_count": stop_count,
                }
            )
    return origins


def profile_access_grid(
    router: TransitRouter,
    resources: list[dict],
    origins: list[dict],
    profile: MobilityProfile,
    category: str | None = None,
    max_minutes: int = 30,
    mobility_hub: tuple[float, float] | None = None,
) -> list[dict]:
    candidates = [resource for resource in resources if not category or resource.get("category") == category]
    categories = sorted({resource.get("category", "Other") for resource in candidates})
    rows = []
    for origin_row in origins:
        origin = (float(origin_row["lat"]), float(origin_row["lon"]))
        plan = router.build_plan(
            origin,
            max_walk_miles=profile.max_walk_miles,
            walk_speed_mph=profile.walk_speed_mph,
            wheelchair_needed=profile.wheelchair_transit,
            max_minutes=max_minutes + 35,
        )
        modes = ["RTS bus", "Walk"]
        if mobility_hub and haversine_miles(*origin, *mobility_hub) <= 1.25:
            modes.append("Bike / micromobility")
        reachable = []
        confirmed = []
        reached_categories = set()
        for resource in candidates:
            result = evaluate_resource(
                resource,
                origin,
                modes,
                profile.max_walk_miles,
                max_minutes,
                profile.walk_speed_mph,
                profile.access_needs,
                router,
                plan,
                profile.wheelchair_transit,
                False,
            )
            if result["best_option"] and result["status"] != "does_not_match":
                reachable.append(result)
                reached_categories.add(result.get("category", "Other"))
                if result["status"] == "reachable":
                    confirmed.append(result)
        resource_share = 100 * len(reachable) / len(candidates) if candidates else 0
        confirmed_share = 100 * len(confirmed) / len(candidates) if candidates else 0
        category_share = 100 * len(reached_categories) / len(categories) if categories else 0
        rows.append(
            {
                **origin_row,
                "profile_id": profile.id,
                "profile_label": profile.label,
                "resources_reachable": len(reachable),
                "resources_confirmed": len(confirmed),
                "resource_share": resource_share,
                "confirmed_share": confirmed_share,
                "category_share": category_share,
                "meets_threshold": bool(reachable),
                "uncertain_count": len(reachable) - len(confirmed),
            }
        )
    return rows


def summarize_grid(rows: list[dict]) -> dict:
    if not rows:
        return {"mean_resource_share": 0.0, "cells_with_access": 0, "cell_access_percent": 0.0, "mean_confirmed_share": 0.0}
    cells_with_access = sum(row["meets_threshold"] for row in rows)
    return {
        "mean_resource_share": mean(row["resource_share"] for row in rows),
        "mean_confirmed_share": mean(row["confirmed_share"] for row in rows),
        "cells_with_access": cells_with_access,
        "cell_access_percent": 100 * cells_with_access / len(rows),
    }


def evaluate_manual_intervention(
    base_router: TransitRouter,
    resources: list[dict],
    origins: list[dict],
    locations: list[dict],
    intervention: Intervention,
    max_minutes: int = 30,
) -> dict:
    changes = {intervention.route_id: intervention.target_headway} if intervention.kind == "frequency" else {}
    scenario_router = base_router.with_route_headways(changes)
    location_by_name = {location["name"]: location for location in locations}
    mobility_hub = None
    if intervention.kind == "mobility_hub" and intervention.target_location in location_by_name:
        target = location_by_name[intervention.target_location]
        mobility_hub = (float(target["latitude"]), float(target["longitude"]))
    profiles = {}
    for profile in MOBILITY_PROFILES:
        before_rows = profile_access_grid(base_router, resources, origins, profile, max_minutes=max_minutes)
        after_rows = profile_access_grid(
            scenario_router,
            resources,
            origins,
            profile,
            max_minutes=max_minutes,
            mobility_hub=mobility_hub,
        )
        profiles[profile.id] = {
            "profile": asdict(profile),
            "before": before_rows,
            "after": after_rows,
            "before_summary": summarize_grid(before_rows),
            "after_summary": summarize_grid(after_rows),
        }
    return {
        "intervention": asdict(intervention),
        "profiles": profiles,
        "max_minutes": max_minutes,
        "mobility_hub": mobility_hub,
    }


def score_locations(
    router: TransitRouter,
    resources: list[dict],
    locations: list[dict],
    mobility_hubs: set[str] | None = None,
) -> list[dict]:
    categories = sorted({resource["category"] for resource in resources})
    mobility_hubs = mobility_hubs or set()
    scores = []
    for location in locations:
        origin = (float(location["latitude"]), float(location["longitude"]))
        plan = router.build_plan(origin, max_walk_miles=0.5, walk_speed_mph=3.0, max_minutes=80)
        reached: set[str] = set()
        best_times: dict[str, int] = {}
        modes = ["RTS bus", "Walk"]
        if location["name"] in mobility_hubs:
            modes.append("Bike / micromobility")
        for resource in resources:
            result = evaluate_resource(resource, origin, modes, 0.5, 45, 3.0, [], router, plan, include_geometry=False)
            option = result["best_option"]
            if option:
                reached.add(resource["category"])
                best_times[resource["category"]] = min(option.minutes, best_times.get(resource["category"], 10_000))
        scores.append(
            {
                "location": location["name"],
                "area": location["area"],
                "lat": float(location["latitude"]),
                "lon": float(location["longitude"]),
                "score": 100 * len(reached) / len(categories),
                "categories_reached": len(reached),
                "mean_best_time": mean(best_times.values()) if best_times else None,
            }
        )
    return scores


def summarize_scores(scores: list[dict]) -> dict:
    values = [row["score"] for row in scores]
    return {
        "average_score": mean(values),
        "minimum_score": min(values),
        "maximum_score": max(values),
        "access_gap": max(values) - min(values),
    }


def evaluate_scenarios(
    base_router: TransitRouter,
    resources: list[dict],
    locations: list[dict],
    budget_units: int,
    interventions: Iterable[Intervention] = INTERVENTIONS,
) -> list[dict]:
    candidates = tuple(interventions)
    scenarios = []
    for size in range(len(candidates) + 1):
        for selected in combinations(candidates, size):
            cost = sum(item.cost_units for item in selected)
            if cost > budget_units:
                continue
            changes = {item.route_id: item.target_headway for item in selected if item.kind == "frequency"}
            mobility_hubs = {item.target_location for item in selected if item.kind == "mobility_hub"}
            router = base_router.with_route_headways(changes)
            location_scores = score_locations(router, resources, locations, mobility_hubs)
            summary = summarize_scores(location_scores)
            scenarios.append(
                {
                    "id": "+".join(item.id for item in selected) or "baseline",
                    "interventions": [asdict(item) for item in selected],
                    "cost_units": cost,
                    "location_scores": location_scores,
                    **summary,
                    "fairness_score": 0.55 * summary["average_score"] + 0.45 * summary["minimum_score"],
                }
            )
    return scenarios


def choose_scenario(scenarios: list[dict], objective: str) -> dict:
    """Select one exactly evaluated intervention bundle with a tiny cost tie-break."""
    if objective not in {"efficiency", "fairness"}:
        raise ValueError("objective must be 'efficiency' or 'fairness'")
    problem = pulp.LpProblem(f"fairroute_{objective}", pulp.LpMaximize)
    choices = {
        scenario["id"]: problem.add_variable(f"choose_{index}", cat="Binary")
        for index, scenario in enumerate(scenarios)
    }
    problem += pulp.lpSum(choices.values()) == 1
    if objective == "efficiency":
        problem += pulp.lpSum(
            choices[scenario["id"]]
            * (scenario["average_score"] + 0.001 * scenario["minimum_score"] - 0.0001 * scenario["cost_units"])
            for scenario in scenarios
        )
    else:
        problem += pulp.lpSum(
            choices[scenario["id"]]
            * (scenario["fairness_score"] - 0.0001 * scenario["cost_units"])
            for scenario in scenarios
        )
    problem.solve(pulp.COIN_CMD(path=pulp_cbc_path, msg=False))
    selected = next((scenario for scenario in scenarios if choices[scenario["id"]].value() and choices[scenario["id"]].value() > 0.5), None)
    if selected is None:
        metric = "average_score" if objective == "efficiency" else "fairness_score"
        selected = max(scenarios, key=lambda scenario: (scenario[metric], -scenario["cost_units"]))
    return {**selected, "objective": objective, "solver_status": pulp.LpStatus[problem.status]}


def optimize_interventions(
    base_router: TransitRouter,
    resources: list[dict],
    locations: list[dict],
    budget_units: int,
) -> dict:
    scenarios = evaluate_scenarios(base_router, resources, locations, budget_units)
    baseline = next(scenario for scenario in scenarios if scenario["id"] == "baseline")
    return {
        "budget_units": budget_units,
        "scenario_count": len(scenarios),
        "baseline": baseline,
        "efficiency": choose_scenario(scenarios, "efficiency"),
        "fairness": choose_scenario(scenarios, "fairness"),
    }
