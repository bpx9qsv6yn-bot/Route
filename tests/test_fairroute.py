import unittest
import csv
from pathlib import Path

from fairroute import (
    StreetRouter,
    TravelLeg,
    TravelOption,
    TransitRouter,
    access_burden,
    direct_options,
    evaluate_resource,
    facility_access_status,
    haversine_miles,
    with_literal_street_legs,
)
from planner import choose_scenario
from resource_adapter import normalize_fci_resource


class FairRouteTests(unittest.TestCase):
    ROOT = Path(__file__).parents[1]

    def test_distance_is_symmetric(self):
        a = (29.6516, -82.3248)
        b = (29.6463, -82.3477)
        self.assertAlmostEqual(haversine_miles(*a, *b), haversine_miles(*b, *a), places=8)

    def test_walk_respects_distance_tolerance(self):
        origin = (29.65, -82.32)
        close = (29.653, -82.32)
        self.assertTrue(direct_options(origin, close, ["Walk"], 0.5, 3.0))
        self.assertFalse(direct_options(origin, close, ["Walk"], 0.1, 3.0))

    def test_unknown_accessibility_is_not_reported_as_confirmed(self):
        resource = {"step_free": "unknown", "accessible_restroom": "yes"}
        self.assertEqual(facility_access_status(resource, ["Step-free entrance"]), "confirm")
        self.assertEqual(facility_access_status(resource, []), "confirmed")

    def test_outside_time_limit_is_not_reachable(self):
        resource = {
            "name": "Test",
            "latitude": "29.70",
            "longitude": "-82.32",
            "step_free": "yes",
            "accessible_restroom": "yes",
        }
        result = evaluate_resource(resource, (29.65, -82.32), ["Walk"], 10, 5, 3.0, [])
        self.assertEqual(result["status"], "outside_limit")
        self.assertIsNone(result["best_option"])

    def test_transit_route_uses_wait_ride_and_egress(self):
        network = {
            "routes": [{"id": "1", "short_name": "1", "headway_minutes": 20, "wheelchair": "yes"}],
            "stops": [
                {"id": "a", "name": "A", "lat": 29.65, "lon": -82.32},
                {"id": "b", "name": "B", "lat": 29.66, "lon": -82.32},
            ],
            "edges": [{"from": "a", "to": "b", "route": "1", "minutes": 8}],
        }
        router = TransitRouter(network)
        plan = router.build_plan((29.65, -82.32), 0.25, 3.0)
        option = router.option_to(plan, (29.66, -82.32))
        self.assertIsNotNone(option)
        self.assertEqual(option.routes, ("1",))
        self.assertGreaterEqual(option.minutes, 18)
        self.assertGreater(option.wait_minutes, 0)
        self.assertTrue(option.legs)

    def test_access_burden_is_explicit_and_uncertainty_cannot_hide(self):
        option = TravelOption("RTS", 24, routes=("5",), transfers=1, walking_minutes=8, wait_minutes=6)
        known = access_burden(option)
        uncertain = access_burden(option, ["facility"])
        self.assertEqual(known["breakdown"]["transfers"], 8)
        self.assertGreater(uncertain["points"], known["points"])
        self.assertEqual(uncertain["key"], "uncertain")
        self.assertIn("facility", uncertain["uncertainty_reasons"])

    def test_gtfs_shape_geometry_is_used_for_literal_route_line(self):
        network = {
            "routes": [{"id": "1", "short_name": "1", "headway_minutes": 20, "wheelchair": "yes"}],
            "stops": [
                {"id": "a", "name": "A", "lat": 29.65, "lon": -82.32},
                {"id": "b", "name": "B", "lat": 29.66, "lon": -82.30},
            ],
            "edges": [{"from": "a", "to": "b", "route": "1", "minutes": 8}],
            "shapes": [{"id": "shape", "route": "1", "path": [[-82.32, 29.65], [-82.31, 29.655], [-82.30, 29.66]]}],
        }
        geometry = TransitRouter(network).route_geometry("1", "a", "b")
        self.assertEqual(len(geometry), 3)
        self.assertEqual(geometry[1], (-82.31, 29.655))

    def test_local_street_graph_replaces_straight_active_travel_line(self):
        network = {
            "nodes": {
                "a": [-82.3200, 29.6500],
                "b": [-82.3190, 29.6510],
                "c": [-82.3180, 29.6500],
            },
            "ways": [
                {"nodes": ["a", "b", "c"], "modes": 3, "wheelchair": "likely", "kind": "footway"}
            ],
        }
        option = TravelOption(
            "Walk",
            5,
            distance_miles=0.2,
            walking_minutes=5,
            walking_distance_miles=0.2,
            legs=(
                TravelLeg(
                    kind="walk",
                    minutes=5,
                    geometry=((-82.3200, 29.6500), (-82.3180, 29.6500)),
                    label="Walk or roll",
                ),
            ),
        )
        routed = with_literal_street_legs(option, StreetRouter(network), wheelchair=True)
        self.assertEqual(routed.legs[0].geometry_source, "local OSM street/path graph")
        self.assertGreater(len(routed.legs[0].geometry), 2)
        self.assertIn((-82.3190, 29.6510), routed.legs[0].geometry)

    def test_headway_scenario_does_not_mutate_baseline_router(self):
        network = {
            "routes": [{"id": "1", "short_name": "1", "headway_minutes": 30, "wheelchair": "yes"}],
            "stops": [
                {"id": "a", "name": "A", "lat": 29.65, "lon": -82.32},
                {"id": "b", "name": "B", "lat": 29.66, "lon": -82.32},
            ],
            "edges": [{"from": "a", "to": "b", "route": "1", "minutes": 8}],
        }
        baseline = TransitRouter(network)
        scenario = baseline.with_route_headways({"1": 12})
        self.assertEqual(baseline.routes["1"]["headway_minutes"], 30)
        self.assertEqual(scenario.routes["1"]["headway_minutes"], 12)

    def test_optimizer_objectives_can_choose_different_bundles(self):
        scenarios = [
            {"id": "average", "average_score": 70, "minimum_score": 0, "fairness_score": 38.5, "cost_units": 10},
            {"id": "floor", "average_score": 60, "minimum_score": 40, "fairness_score": 51, "cost_units": 10},
        ]
        self.assertEqual(choose_scenario(scenarios, "efficiency")["id"], "average")
        self.assertEqual(choose_scenario(scenarios, "fairness")["id"], "floor")

    def test_unverified_transit_is_flagged_for_mobility_device_user(self):
        network = {
            "routes": [{"id": "1", "short_name": "1", "headway_minutes": 10, "wheelchair": "unknown"}],
            "stops": [
                {"id": "a", "name": "A", "lat": 29.65, "lon": -82.32},
                {"id": "b", "name": "B", "lat": 29.66, "lon": -82.32},
            ],
            "edges": [{"from": "a", "to": "b", "route": "1", "minutes": 5}],
        }
        router = TransitRouter(network)
        plan = router.build_plan((29.65, -82.32), 0.25, 3.0, wheelchair_needed=True)
        resource = {
            "name": "Test",
            "latitude": "29.66",
            "longitude": "-82.32",
            "step_free": "yes",
            "accessible_restroom": "yes",
        }
        result = evaluate_resource(
            resource,
            (29.65, -82.32),
            ["RTS bus"],
            0.25,
            30,
            3.0,
            [],
            router,
            plan,
            wheelchair_transit_needed=True,
        )
        self.assertEqual(result["status"], "confirm")
        self.assertIn("transit", result["confirmation_reasons"])

    def test_bundled_resource_data_has_generic_required_fields(self):
        with (self.ROOT / "data" / "resources.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        required = {"resource_id", "name", "category", "latitude", "longitude", "address"}
        self.assertTrue(rows)
        self.assertTrue(required.issubset(rows[0]))
        self.assertEqual(len(rows), len({row["resource_id"] for row in rows}))
        for row in rows:
            self.assertGreaterEqual(float(row["latitude"]), -90)
            self.assertLessEqual(float(row["latitude"]), 90)
            self.assertGreaterEqual(float(row["longitude"]), -180)
            self.assertLessEqual(float(row["longitude"]), 180)

    def test_bundled_gtfs_derivative_loads(self):
        router = TransitRouter.from_json(self.ROOT / "data" / "transit_network.json")
        self.assertGreater(len(router.stops), 100)
        self.assertGreater(len(router.routes), 10)
        self.assertGreater(sum(len(shapes) for shapes in router.shapes_by_route.values()), 10)

    def test_fci_adapter_marks_city_only_locations_as_imprecise(self):
        record = {
            "resourceId": "abc",
            "name": "Example",
            "coords": {"coordinates": [-82.32, 29.65]},
            "address": {"city": "Gainesville", "state": "FL"},
            "tags": ["food"],
        }
        normalized = normalize_fci_resource(record)
        self.assertEqual(normalized["category"], "Food assistance")
        self.assertEqual(normalized["location_precision"], "city-level / verify location")


if __name__ == "__main__":
    unittest.main()
