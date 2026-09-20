"""Deterministic mobility and accessibility calculations for FairRoute.

No user input is persisted here. Directory records and the transit network are
inputs, so the same engine can sit beside other community-resource directories.
"""

from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


EARTH_RADIUS_MILES = 3958.7613
WALK_CIRCUITY = 1.18
BIKE_CIRCUITY = 1.15


def haversine_miles(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    lat1, lat2 = math.radians(a_lat), math.radians(b_lat)
    dlat = math.radians(b_lat - a_lat)
    dlon = math.radians(b_lon - a_lon)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(value))


def walking_minutes(distance_miles: float, speed_mph: float = 3.0) -> float:
    return distance_miles * WALK_CIRCUITY / max(speed_mph, 0.5) * 60


@dataclass(frozen=True)
class TravelLeg:
    """One inspectable part of a trip, including its literal map geometry."""

    kind: str
    minutes: float
    geometry: tuple[tuple[float, float], ...]
    label: str
    route_id: str = ""
    from_stop_id: str = ""
    to_stop_id: str = ""
    geometry_source: str = "estimated connector"


@dataclass(frozen=True)
class TravelOption:
    mode: str
    minutes: int
    distance_miles: float | None = None
    routes: tuple[str, ...] = ()
    route_ids: tuple[str, ...] = ()
    transfers: int = 0
    accessibility_uncertain: bool = False
    walking_minutes: float = 0
    walking_distance_miles: float = 0
    wait_minutes: float = 0
    in_vehicle_minutes: float = 0
    transfer_penalty_minutes: float = 0
    legs: tuple[TravelLeg, ...] = ()


@dataclass
class TransitPlan:
    origin: tuple[float, float]
    max_walk_miles: float
    walk_speed_mph: float
    distances: dict[tuple[str, str, int], float]
    previous: dict[tuple[str, str, int], tuple[str, str, int] | None]
    wheelchair_needed: bool = False


@dataclass(frozen=True)
class StreetRoute:
    distance_miles: float
    geometry: tuple[tuple[float, float], ...]
    accessibility_uncertain: bool
    path_types: tuple[str, ...]


class TransitRouter:
    def __init__(self, network: dict):
        self.meta = network.get("meta", {})
        self.stops = {stop["id"]: stop for stop in network.get("stops", [])}
        self.routes = {route["id"]: route for route in network.get("routes", [])}
        self.shapes_by_route: dict[str, list[dict]] = defaultdict(list)
        for shape in network.get("shapes", []):
            if len(shape.get("path", [])) >= 2:
                self.shapes_by_route[shape["route"]].append(shape)
        self.outgoing: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
        self.routes_by_stop: dict[str, set[str]] = defaultdict(set)
        for edge in network.get("edges", []):
            route_id = edge["route"]
            self.outgoing[(edge["from"], route_id)].append((edge["to"], float(edge["minutes"])))
            self.routes_by_stop[edge["from"]].add(route_id)
            self.routes_by_stop[edge["to"]].add(route_id)
        self.stop_cell_size = 0.01
        self.stop_cells: dict[tuple[int, int], list[str]] = defaultdict(list)
        for stop_id, stop in self.stops.items():
            self.stop_cells[
                (int(float(stop["lat"]) / self.stop_cell_size), int(float(stop["lon"]) / self.stop_cell_size))
            ].append(stop_id)
        self.transfer_neighbors = self._make_transfer_neighbors(0.14)

    @classmethod
    def from_json(cls, path: str | Path) -> "TransitRouter":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def with_route_headways(self, changes: dict[str, float]) -> "TransitRouter":
        """Reuse one network topology with a small set of changed frequencies."""
        clone = object.__new__(TransitRouter)
        clone.meta = dict(self.meta)
        clone.stops = self.stops
        clone.routes = {
            route_id: {
                **route,
                "headway_minutes": float(changes.get(route_id, route.get("headway_minutes", 60))),
            }
            for route_id, route in self.routes.items()
        }
        clone.outgoing = self.outgoing
        clone.routes_by_stop = self.routes_by_stop
        clone.stop_cell_size = self.stop_cell_size
        clone.stop_cells = self.stop_cells
        clone.transfer_neighbors = self.transfer_neighbors
        clone.shapes_by_route = self.shapes_by_route
        return clone

    @staticmethod
    def _nearest_path_index(path: Sequence[Sequence[float]], stop: dict) -> tuple[int, float]:
        best_index = 0
        best_distance = math.inf
        for index, point in enumerate(path):
            distance = haversine_miles(stop["lat"], stop["lon"], float(point[1]), float(point[0]))
            if distance < best_distance:
                best_index, best_distance = index, distance
        return best_index, best_distance

    def route_geometry(self, route_id: str, from_stop_id: str, to_stop_id: str) -> tuple[tuple[float, float], ...]:
        """Return the GTFS shape segment that best matches a directed stop pair."""
        start = self.stops[from_stop_id]
        end = self.stops[to_stop_id]
        best: tuple[float, tuple[tuple[float, float], ...]] | None = None
        for shape in self.shapes_by_route.get(route_id, []):
            path = shape["path"]
            start_index, start_gap = self._nearest_path_index(path, start)
            end_index, end_gap = self._nearest_path_index(path, end)
            if start_index > end_index:
                continue
            segment = tuple((float(lon), float(lat)) for lon, lat in path[start_index : end_index + 1])
            if len(segment) < 2:
                continue
            candidate = (start_gap + end_gap, segment)
            if best is None or candidate[0] < best[0]:
                best = candidate
        if best:
            return best[1]
        return ((start["lon"], start["lat"]), (end["lon"], end["lat"]))

    def route_shapes(self, route_ids: Iterable[str] | None = None) -> list[dict]:
        selected = set(route_ids) if route_ids is not None else set(self.shapes_by_route)
        return [shape for route_id in selected for shape in self.shapes_by_route.get(route_id, [])]

    def _make_transfer_neighbors(self, radius_miles: float) -> dict[str, list[tuple[str, float]]]:
        cell_size = 0.004
        cells: dict[tuple[int, int], list[str]] = defaultdict(list)
        for stop_id, stop in self.stops.items():
            key = (int(stop["lat"] / cell_size), int(stop["lon"] / cell_size))
            cells[key].append(stop_id)

        neighbors: dict[str, list[tuple[str, float]]] = {}
        for stop_id, stop in self.stops.items():
            row, col = int(stop["lat"] / cell_size), int(stop["lon"] / cell_size)
            candidates: list[tuple[str, float]] = [(stop_id, 0.0)]
            for drow in (-1, 0, 1):
                for dcol in (-1, 0, 1):
                    for other_id in cells.get((row + drow, col + dcol), []):
                        if other_id == stop_id:
                            continue
                        other = self.stops[other_id]
                        distance = haversine_miles(stop["lat"], stop["lon"], other["lat"], other["lon"])
                        if distance <= radius_miles:
                            candidates.append((other_id, distance))
            neighbors[stop_id] = sorted(candidates, key=lambda item: item[1])[:16]
        return neighbors

    def _nearby_stops(self, lat: float, lon: float, max_miles: float) -> list[tuple[str, float]]:
        found = []
        row = int(lat / self.stop_cell_size)
        column = int(lon / self.stop_cell_size)
        # One 0.01-degree cell is roughly 0.6 miles at Gainesville's latitude.
        reach = max(1, math.ceil(max_miles / 0.5))
        for drow in range(-reach, reach + 1):
            for dcolumn in range(-reach, reach + 1):
                for stop_id in self.stop_cells.get((row + drow, column + dcolumn), []):
                    stop = self.stops[stop_id]
                    distance = haversine_miles(lat, lon, stop["lat"], stop["lon"])
                    if distance <= max_miles:
                        found.append((stop_id, distance))
        return sorted(found, key=lambda item: item[1])

    def build_plan(
        self,
        origin: tuple[float, float],
        max_walk_miles: float,
        walk_speed_mph: float,
        wheelchair_needed: bool = False,
        max_transfers: int = 2,
        max_minutes: float = 150,
    ) -> TransitPlan:
        distances: dict[tuple[str, str, int], float] = {}
        previous: dict[tuple[str, str, int], tuple[str, str, int] | None] = {}
        queue: list[tuple[float, tuple[str, str, int]]] = []

        for stop_id, distance in self._nearby_stops(*origin, max_walk_miles / WALK_CIRCUITY):
            if wheelchair_needed and self.stops[stop_id].get("wheelchair") == "no":
                continue
            access_minutes = walking_minutes(distance, walk_speed_mph)
            for route_id in self.routes_by_stop[stop_id]:
                route = self.routes.get(route_id, {})
                if wheelchair_needed and route.get("wheelchair") == "no":
                    continue
                cost = access_minutes + float(route.get("headway_minutes", 60)) / 2
                state = (stop_id, route_id, 0)
                if cost < distances.get(state, math.inf):
                    distances[state] = cost
                    previous[state] = None
                    heapq.heappush(queue, (cost, state))

        while queue:
            cost, state = heapq.heappop(queue)
            if cost != distances.get(state) or cost > max_minutes:
                continue
            stop_id, route_id, transfers = state

            for next_stop, ride_minutes in self.outgoing.get((stop_id, route_id), []):
                next_state = (next_stop, route_id, transfers)
                next_cost = cost + ride_minutes
                if next_cost < distances.get(next_state, math.inf):
                    distances[next_state] = next_cost
                    previous[next_state] = state
                    heapq.heappush(queue, (next_cost, next_state))

            if transfers >= max_transfers:
                continue
            for transfer_stop, transfer_distance in self.transfer_neighbors.get(stop_id, []):
                if transfer_distance * WALK_CIRCUITY > max_walk_miles:
                    continue
                if wheelchair_needed and any(self.stops[s].get("wheelchair") == "no" for s in (stop_id,transfer_stop)):
                    continue
                transfer_walk = walking_minutes(transfer_distance, walk_speed_mph)
                for next_route in self.routes_by_stop[transfer_stop]:
                    if next_route == route_id:
                        continue
                    route = self.routes.get(next_route, {})
                    if wheelchair_needed and route.get("wheelchair") == "no":
                        continue
                    wait = float(route.get("headway_minutes", 60)) / 2
                    next_state = (transfer_stop, next_route, transfers + 1)
                    next_cost = cost + transfer_walk + 4 + wait
                    if next_cost < distances.get(next_state, math.inf):
                        distances[next_state] = next_cost
                        previous[next_state] = state
                        heapq.heappush(queue, (next_cost, next_state))

        return TransitPlan(origin, max_walk_miles, walk_speed_mph, distances, previous, wheelchair_needed)

    def option_to(
        self,
        plan: TransitPlan,
        destination: tuple[float, float],
        include_geometry: bool = True,
    ) -> TravelOption | None:
        best_state: tuple[str, str, int] | None = None
        best_minutes = math.inf
        for stop_id, distance in self._nearby_stops(*destination, plan.max_walk_miles / WALK_CIRCUITY):
            if plan.wheelchair_needed and self.stops[stop_id].get("wheelchair") == "no":
                continue
            egress = walking_minutes(distance, plan.walk_speed_mph)
            for route_id in self.routes_by_stop[stop_id]:
                for transfers in (0, 1, 2):
                    state = (stop_id, route_id, transfers)
                    total = plan.distances.get(state, math.inf) + egress
                    if total < best_minutes:
                        best_minutes, best_state = total, state
        if best_state is None:
            return None

        state_path: list[tuple[str, str, int]] = []
        cursor: tuple[str, str, int] | None = best_state
        while cursor is not None:
            state_path.append(cursor)
            cursor = plan.previous.get(cursor)
        state_path.reverse()

        first_stop = self.stops[state_path[0][0]]
        final_stop = self.stops[state_path[-1][0]]
        access_distance = haversine_miles(*plan.origin, first_stop["lat"], first_stop["lon"]) * WALK_CIRCUITY
        egress_distance = haversine_miles(final_stop["lat"], final_stop["lon"], *destination) * WALK_CIRCUITY
        transfer_distance = 0.0
        wait_minutes = float(self.routes.get(state_path[0][1], {}).get("headway_minutes", 60)) / 2
        in_vehicle_minutes = 0.0
        route_ids: list[str] = [state_path[0][1]]
        bus_groups: list[tuple[str, str, str, float]] = []
        group_route = state_path[0][1]
        group_start = state_path[0][0]
        group_end = group_start
        group_minutes = 0.0

        for previous_state, next_state in zip(state_path, state_path[1:]):
            previous_stop, previous_route, _previous_transfers = previous_state
            next_stop, next_route, _next_transfers = next_state
            if previous_route == next_route:
                edge_minutes = next(
                    (
                        minutes
                        for candidate_stop, minutes in self.outgoing.get((previous_stop, previous_route), [])
                        if candidate_stop == next_stop
                    ),
                    0.0,
                )
                group_end = next_stop
                group_minutes += edge_minutes
                in_vehicle_minutes += edge_minutes
                continue

            bus_groups.append((group_route, group_start, group_end, group_minutes))
            transfer_distance += haversine_miles(
                self.stops[previous_stop]["lat"],
                self.stops[previous_stop]["lon"],
                self.stops[next_stop]["lat"],
                self.stops[next_stop]["lon"],
            ) * WALK_CIRCUITY
            wait_minutes += float(self.routes.get(next_route, {}).get("headway_minutes", 60)) / 2
            route_ids.append(next_route)
            group_route, group_start, group_end, group_minutes = next_route, next_stop, next_stop, 0.0
        bus_groups.append((group_route, group_start, group_end, group_minutes))

        if in_vehicle_minutes <= 0:
            return None
        walk_distance = access_distance + transfer_distance + egress_distance
        # Distances here already include circuity; do not apply it twice.
        walk_minutes = walk_distance / max(plan.walk_speed_mph, 0.5) * 60
        route_names = tuple(self.routes.get(route_id, {}).get("short_name", route_id) for route_id in route_ids)
        uncertain = any(self.routes.get(route_id, {}).get("wheelchair") != "yes" for route_id in route_ids)
        uncertain = uncertain or any(self.stops[s].get("wheelchair") != "yes" for _,start,end,_ in bus_groups for s in (start,end))
        legs: list[TravelLeg] = [
            TravelLeg(
                kind="walk",
                minutes=access_distance / max(plan.walk_speed_mph, 0.5) * 60,
                geometry=((plan.origin[1], plan.origin[0]), (first_stop["lon"], first_stop["lat"])),
                label=f"Walk or roll to {first_stop['name']}",
                to_stop_id=state_path[0][0],
            )
        ]
        for index, (route_id, from_stop_id, to_stop_id, ride_minutes) in enumerate(bus_groups):
            route_name = self.routes.get(route_id, {}).get("short_name", route_id)
            from_stop = self.stops[from_stop_id]
            to_stop = self.stops[to_stop_id]
            geometry = (
                self.route_geometry(route_id, from_stop_id, to_stop_id)
                if include_geometry
                else ((from_stop["lon"], from_stop["lat"]), (to_stop["lon"], to_stop["lat"]))
            )
            legs.append(
                TravelLeg(
                    kind="bus",
                    minutes=ride_minutes,
                    geometry=geometry,
                    label=f"RTS Route {route_name}",
                    route_id=route_id,
                    from_stop_id=from_stop_id,
                    to_stop_id=to_stop_id,
                    geometry_source="official GTFS shape" if include_geometry else "route topology",
                )
            )
            if index < len(bus_groups) - 1:
                next_start = bus_groups[index + 1][1]
                from_stop = self.stops[to_stop_id]
                to_stop = self.stops[next_start]
                distance = haversine_miles(from_stop["lat"], from_stop["lon"], to_stop["lat"], to_stop["lon"]) * WALK_CIRCUITY
                legs.append(
                    TravelLeg(
                        kind="transfer",
                        minutes=distance / max(plan.walk_speed_mph, 0.5) * 60 + 4,
                        geometry=((from_stop["lon"], from_stop["lat"]), (to_stop["lon"], to_stop["lat"])),
                        label="Transfer connection",
                        from_stop_id=to_stop_id,
                        to_stop_id=next_start,
                    )
                )
        legs.append(
            TravelLeg(
                kind="walk",
                minutes=egress_distance / max(plan.walk_speed_mph, 0.5) * 60,
                geometry=((final_stop["lon"], final_stop["lat"]), (destination[1], destination[0])),
                label="Final walk or roll",
                from_stop_id=state_path[-1][0],
            )
        )
        return TravelOption(
            mode="RTS",
            minutes=max(1, round(best_minutes)),
            routes=route_names,
            route_ids=tuple(route_ids),
            transfers=max(0, len(route_names) - 1),
            accessibility_uncertain=uncertain,
            walking_minutes=walk_minutes,
            walking_distance_miles=walk_distance,
            wait_minutes=wait_minutes,
            in_vehicle_minutes=in_vehicle_minutes,
            transfer_penalty_minutes=4 * max(0, len(route_names) - 1),
            legs=tuple(legs),
        )


class StreetRouter:
    """Small local OSM graph used only to make active-travel geometry literal."""

    FOOT = 1
    BIKE = 2

    def __init__(self, network: dict):
        self.meta = network.get("meta", {})
        self.way_count = len(network.get("ways", []))
        self.nodes = {node_id: (float(point[0]), float(point[1])) for node_id, point in network.get("nodes", {}).items()}
        self.adjacency: dict[str, list[tuple[str, float, int, str, str]]] = defaultdict(list)
        active_nodes: set[str] = set()
        for way in network.get("ways", []):
            node_ids = [str(node_id) for node_id in way.get("nodes", []) if str(node_id) in self.nodes]
            modes = int(way.get("modes", 0))
            wheelchair = str(way.get("wheelchair") or "unknown")
            kind = str(way.get("kind") or "street")
            for from_id, to_id in zip(node_ids, node_ids[1:]):
                from_point, to_point = self.nodes[from_id], self.nodes[to_id]
                distance = haversine_miles(from_point[1], from_point[0], to_point[1], to_point[0])
                if distance <= 0 or distance > 1.0:
                    continue
                self.adjacency[from_id].append((to_id, distance, modes, wheelchair, kind))
                reverse_modes = modes & ~self.BIKE if way.get("oneway_bike") else modes
                if reverse_modes:
                    self.adjacency[to_id].append((from_id, distance, reverse_modes, wheelchair, kind))
                active_nodes.update((from_id, to_id))
        self.cell_size = 0.005
        self.cells: dict[tuple[int, int], list[str]] = defaultdict(list)
        for node_id in active_nodes:
            lon, lat = self.nodes[node_id]
            self.cells[(int(lat / self.cell_size), int(lon / self.cell_size))].append(node_id)

    @classmethod
    def from_json(cls, path: str | Path) -> "StreetRouter":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def _nearest_node(self, point: tuple[float, float], mode_flag: int, max_miles: float = 0.35) -> tuple[str, float] | None:
        lat, lon = point
        row, column = int(lat / self.cell_size), int(lon / self.cell_size)
        reach = max(1, math.ceil(max_miles / 0.25))
        best: tuple[str, float] | None = None
        for drow in range(-reach, reach + 1):
            for dcolumn in range(-reach, reach + 1):
                for node_id in self.cells.get((row + drow, column + dcolumn), []):
                    if not any(edge[2] & mode_flag for edge in self.adjacency.get(node_id, [])):
                        continue
                    node_lon, node_lat = self.nodes[node_id]
                    distance = haversine_miles(lat, lon, node_lat, node_lon)
                    if distance <= max_miles and (best is None or distance < best[1]):
                        best = (node_id, distance)
        return best

    def route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        mode: str = "walk",
        wheelchair: bool = False,
        max_miles: float = 12.0,
    ) -> StreetRoute | None:
        flag = self.BIKE if mode == "bike" else self.FOOT
        start = self._nearest_node(origin, flag)
        end = self._nearest_node(destination, flag)
        if not start or not end:
            return None
        start_id, start_gap = start
        end_id, end_gap = end
        queue: list[tuple[float, str]] = [(start_gap, start_id)]
        distances = {start_id: start_gap}
        previous: dict[str, tuple[str, str, str] | None] = {start_id: None}
        uncertain_nodes: dict[str, bool] = {start_id: False}
        while queue:
            cost, node_id = heapq.heappop(queue)
            if cost != distances.get(node_id) or cost > max_miles:
                continue
            if node_id == end_id:
                break
            for next_id, edge_distance, modes, wheelchair_status, kind in self.adjacency.get(node_id, []):
                if not modes & flag:
                    continue
                if wheelchair and wheelchair_status == "no":
                    continue
                next_cost = cost + edge_distance
                if next_cost >= distances.get(next_id, math.inf):
                    continue
                distances[next_id] = next_cost
                previous[next_id] = (node_id, wheelchair_status, kind)
                uncertain_nodes[next_id] = uncertain_nodes[node_id] or (wheelchair and wheelchair_status not in {"yes", "likely"})
                heapq.heappush(queue, (next_cost, next_id))
        if end_id not in distances:
            return None

        node_path = []
        kinds = []
        cursor = end_id
        uncertain = uncertain_nodes.get(end_id, False)
        while cursor:
            node_path.append(cursor)
            step = previous.get(cursor)
            if step is None:
                break
            cursor, _wheelchair_status, kind = step
            kinds.append(kind)
        node_path.reverse()
        geometry = [(origin[1], origin[0])]
        geometry.extend(self.nodes[node_id] for node_id in node_path)
        geometry.append((destination[1], destination[0]))
        total_distance = distances[end_id] + end_gap
        return StreetRoute(total_distance, tuple(geometry), uncertain, tuple(dict.fromkeys(reversed(kinds))))


def with_literal_street_legs(option: TravelOption, street_router: StreetRouter, wheelchair: bool = False) -> TravelOption:
    """Replace estimated active-travel connectors with local OSM graph paths."""
    replaced = []
    for leg in option.legs:
        if leg.kind not in {"walk", "transfer", "bike"} or len(leg.geometry) < 2:
            replaced.append(leg)
            continue
        origin_lon, origin_lat = leg.geometry[0]
        destination_lon, destination_lat = leg.geometry[-1]
        route = street_router.route(
            (origin_lat, origin_lon),
            (destination_lat, destination_lon),
            mode="bike" if leg.kind == "bike" else "walk",
            wheelchair=wheelchair and leg.kind != "bike",
            max_miles=max(2.0, (option.distance_miles or option.walking_distance_miles or 1.0) * 2.5),
        )
        if route:
            replaced.append(
                TravelLeg(
                    kind=leg.kind,
                    minutes=leg.minutes,
                    geometry=route.geometry,
                    label=leg.label,
                    route_id=leg.route_id,
                    from_stop_id=leg.from_stop_id,
                    to_stop_id=leg.to_stop_id,
                    geometry_source="local OSM street/path graph",
                )
            )
        else:
            replaced.append(leg)
    return TravelOption(**{**option.__dict__, "legs": tuple(replaced)})


def direct_options(
    origin: tuple[float, float],
    destination: tuple[float, float],
    modes: Iterable[str],
    max_walk_miles: float,
    walk_speed_mph: float,
) -> list[TravelOption]:
    distance = haversine_miles(*origin, *destination)
    options: list[TravelOption] = []
    if "Walk" in modes and distance * WALK_CIRCUITY <= max_walk_miles:
        routed_distance = distance * WALK_CIRCUITY
        minutes = walking_minutes(distance, walk_speed_mph)
        options.append(
            TravelOption(
                "Walk",
                max(1, round(minutes)),
                routed_distance,
                walking_minutes=minutes,
                walking_distance_miles=routed_distance,
                legs=(
                    TravelLeg(
                        kind="walk",
                        minutes=minutes,
                        geometry=((origin[1], origin[0]), (destination[1], destination[0])),
                        label="Walk or roll",
                    ),
                ),
            )
        )
    if "Bike / micromobility" in modes:
        routed_distance = distance * BIKE_CIRCUITY
        minutes = routed_distance / 9.5 * 60
        options.append(
            TravelOption(
                "Bike / micromobility",
                max(1, round(minutes)),
                routed_distance,
                legs=(
                    TravelLeg(
                        kind="bike",
                        minutes=minutes,
                        geometry=((origin[1], origin[0]), (destination[1], destination[0])),
                        label="Bike or micromobility",
                    ),
                ),
            )
        )
    return options


def access_burden(option: TravelOption, uncertainty_reasons: Iterable[str] = ()) -> dict:
    """Return an explicit effort score without concealing access uncertainty.

    Total time already includes walking, waiting, riding, and transfer time. The
    remaining terms are visible friction weights: active travel receives 0.75
    extra point per minute, each transfer adds eight points, expected waiting
    adds 0.5 point per minute, and each relevant unknown adds fifteen points.
    These prototype weights are policy settings, not clinical measurements.
    """
    reasons = tuple(dict.fromkeys(uncertainty_reasons))
    travel_points = float(option.minutes)
    active_points = 0.75 * float(option.walking_minutes)
    transfer_points = 8.0 * int(option.transfers)
    wait_points = 0.5 * float(option.wait_minutes)
    uncertainty_points = 15.0 * len(reasons)
    raw = travel_points + active_points + transfer_points + wait_points + uncertainty_points
    points = max(0, min(100, round(raw)))
    if reasons:
        level = "High / uncertain"
        key = "uncertain"
    elif points < 35:
        level = "Low burden"
        key = "low"
    elif points < 60:
        level = "Moderate burden"
        key = "moderate"
    else:
        level = "High burden"
        key = "high"
    return {
        "points": points,
        "level": level,
        "key": key,
        "uncertainty_reasons": reasons,
        "breakdown": {
            "travel_time": round(travel_points, 1),
            "walking_or_rolling": round(active_points, 1),
            "transfers": round(transfer_points, 1),
            "expected_wait": round(wait_points, 1),
            "access_uncertainty": round(uncertainty_points, 1),
        },
    }


def facility_access_status(resource: dict, needs: Iterable[str]) -> str:
    columns = {
        "Step-free entrance": "step_free",
        "Accessible restroom": "accessible_restroom",
    }
    values = [str(resource.get(columns[need], "unknown")).strip().lower() for need in needs if need in columns]
    if any(value == "no" for value in values):
        return "does_not_match"
    if any(value != "yes" for value in values):
        return "confirm"
    return "confirmed"


def accessibility_data_confidence(resource: dict) -> str:
    values = {
        str(resource.get("step_free", "unknown")).strip().lower(),
        str(resource.get("accessible_restroom", "unknown")).strip().lower(),
    }
    if values <= {"yes", "no"}:
        return "documented"
    if "yes" in values or "no" in values:
        return "partial"
    return "unknown"


def evaluate_resource(
    resource: dict,
    origin: tuple[float, float],
    modes: Iterable[str],
    max_walk_miles: float,
    max_trip_minutes: int,
    walk_speed_mph: float,
    access_needs: Iterable[str],
    router: TransitRouter | None = None,
    transit_plan: TransitPlan | None = None,
    wheelchair_transit_needed: bool = False,
    include_geometry: bool = True,
) -> dict:
    destination = (float(resource["latitude"]), float(resource["longitude"]))
    mode_set = set(modes)
    options = direct_options(origin, destination, mode_set, max_walk_miles, walk_speed_mph)
    if "RTS bus" in mode_set and router and transit_plan:
        transit = router.option_to(transit_plan, destination, include_geometry=include_geometry)
        if transit:
            options.append(transit)
    options.sort(key=lambda option: option.minutes)
    reachable = [option for option in options if option.minutes <= max_trip_minutes]
    access_status = facility_access_status(resource, access_needs)
    best_option = reachable[0] if reachable else None
    confirmation_reasons: list[str] = []
    if access_status == "confirm":
        confirmation_reasons.append("facility")
    if (
        wheelchair_transit_needed
        and best_option
        and best_option.mode == "RTS"
        and best_option.accessibility_uncertain
    ):
        confirmation_reasons.append("transit")

    if not reachable:
        status = "outside_limit"
    elif access_status == "does_not_match":
        status = "does_not_match"
    elif confirmation_reasons:
        status = "confirm"
    else:
        status = "reachable"

    burden = access_burden(best_option, confirmation_reasons) if best_option else None

    if access_status == "does_not_match":
        unavailable_reason = "The facility record conflicts with a required accessibility feature."
    elif not reachable and options:
        unavailable_reason = f"The quickest modeled trip takes {options[0].minutes} min, above your {max_trip_minutes}-minute limit."
    elif not reachable:
        unavailable_reason = "No modeled route fits your travel modes and walking / rolling limit. Coverage may also be incomplete."
    else:
        unavailable_reason = ""

    result = dict(resource)
    result.update(
        {
            "status": status,
            "access_status": access_status,
            "unavailable_reason": unavailable_reason,
            "confirmation_reasons": confirmation_reasons,
            "accessibility_confidence": accessibility_data_confidence(resource),
            "best_option": best_option,
            "burden": burden,
            "travel_options": reachable,
            "straight_line_miles": haversine_miles(*origin, *destination),
        }
    )
    return result
