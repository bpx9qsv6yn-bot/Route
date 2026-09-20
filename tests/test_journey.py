import unittest
from datetime import date
from types import SimpleNamespace

from fairroute import TravelOption, TravelLeg, evaluate_resource
from journey import category_matches, itinerary_steps, option_result, rank_results, schedule_notice, trip_summary


class JourneyTests(unittest.TestCase):
    def row(self, options, access="confirmed", name="Service"):
        return dict(name=name, status="reachable", access_status=access, travel_options=options,
                    resource_id=name, address="Public service address", hours="Call for hours", source="Test directory")

    def test_ranking_chooses_option_by_user_priority(self):
        walk = TravelOption("Walk", 20, walking_minutes=20)
        bus = TravelOption("RTS", 22, walking_minutes=2, wait_minutes=2)
        rows = [self.row([walk, bus])]
        self.assertEqual(rank_results(rows, "Lowest burden")[0]["best_option"], bus)
        self.assertEqual(rank_results(rows, "Shortest trip")[0]["best_option"], walk)
        self.assertEqual(rank_results(rows, "Least walking / rolling")[0]["best_option"], bus)

    def test_switching_mode_recomputes_transit_uncertainty(self):
        walk = TravelOption("Walk", 20)
        bus = TravelOption("RTS", 10, accessibility_uncertain=True)
        row = self.row([walk, bus])
        self.assertEqual(option_result(row, bus, True)["status"], "confirm")
        self.assertEqual(option_result(row, walk, True)["confirmation_reasons"], [])
        self.assertEqual(rank_results([row], "Shortest trip", True)[0]["best_option"], walk)

    def test_facility_uncertainty_cannot_disappear_on_mode_change(self):
        walk = TravelOption("Walk", 5)
        result = option_result(self.row([walk], access="confirm"), walk)
        self.assertEqual(result["status"], "confirm")
        self.assertEqual(result["burden"]["uncertainty_reasons"], ("facility",))

    def test_sort_never_includes_incompatible_or_unreachable_results(self):
        row = self.row([TravelOption("Walk", 5)])
        blocked = {**row, "status": "does_not_match"}
        distant = {**row, "status": "outside_limit"}
        self.assertEqual(rank_results([blocked, distant], "Lowest burden"), [])

    def test_secondary_category_is_searchable(self):
        row = {"category": "Food assistance", "categories": "Food assistance|Health care"}
        self.assertTrue(category_matches(row, "Health care"))
        self.assertFalse(category_matches(row, "Housing"))
        self.assertTrue(category_matches(row, "All resource types"))

    def test_expired_schedule_is_explicit(self):
        self.assertIn("ended", schedule_notice({"feed_end_date": "20260816"}, date(2026, 9, 20)))
        self.assertIn("through", schedule_notice({"feed_end_date": "20261231"}, date(2026, 9, 20)))
        self.assertIn("unknown", schedule_notice({}))

    def test_itinerary_exports_stop_names_and_uncertainty_without_coordinates(self):
        router = SimpleNamespace(stops={"a": {"name": "First stop"}, "b": {"name": "Last stop"}}, meta={})
        option = TravelOption("RTS", 20, wait_minutes=5, legs=(TravelLeg("bus", 15, (), "RTS Route 1", from_stop_id="a", to_stop_id="b"),))
        row = option_result(self.row([option], access="confirm"), option)
        search = {"origin_name": "Temporary starting point", "origin": (29.123456, -82.654321), "access_needs": ["Step-free entrance"]}
        output = trip_summary(search, row, router)
        self.assertIn("First stop → Last stop", output)
        self.assertIn("Access to confirm: facility", output)
        self.assertIn("Expected waiting: 5", output)
        self.assertNotIn("29.123456", output)
        self.assertEqual(itinerary_steps(option, router)[0]["minutes"], 15)

    def test_no_match_reason_explains_time_limit(self):
        resource = dict(name="Far service", latitude=29.70, longitude=-82.32, step_free="yes", accessible_restroom="yes")
        result = evaluate_resource(resource, (29.65, -82.32), ["Walk"], 10, 5, 3, [])
        self.assertIn("above your 5-minute limit", result["unavailable_reason"])

class RoutingConsistencyTests(unittest.TestCase):
    def router(self):
        from fairroute import TransitRouter
        return TransitRouter({"routes": [{"id": "1", "short_name": "1", "headway_minutes": 20, "wheelchair": "yes"}],
            "stops": [{"id": "a", "name": "A", "lat": 29.65, "lon": -82.32},
                      {"id": "b", "name": "B", "lat": 29.67, "lon": -82.32}],
            "edges": [{"from": "a", "to": "b", "route": "1", "minutes": 8}]})

    def test_step_times_and_wait_match_total(self):
        router = self.router()
        plan = router.build_plan((29.649, -82.32), .25, 2)
        option = router.option_to(plan, (29.671, -82.32))
        self.assertIsNotNone(option)
        self.assertAlmostEqual(sum(leg.minutes for leg in option.legs) + option.wait_minutes, option.minutes, delta=.51)
        self.assertAlmostEqual(option.walking_minutes, sum(leg.minutes for leg in option.legs if leg.kind == 'walk'))
        self.assertAlmostEqual(option.walking_minutes, option.walking_distance_miles / 2 * 60)

    def test_transit_access_walk_uses_adjusted_distance_limit(self):
        router = self.router()
        plan = router.build_plan((29.6481, -82.32), .15, 3)
        self.assertIsNone(router.option_to(plan, (29.67, -82.32)))

    def test_zero_ride_is_not_a_bus_option(self):
        router = self.router()
        plan = router.build_plan((29.65, -82.32), .25, 3)
        self.assertIsNone(router.option_to(plan, (29.6501, -82.32)))

    def test_basic_needs_do_not_imply_food_service(self):
        record = {"name": "General service", "tags": ["basic needs"], "latitude":29.65,"longitude":-82.32}
        # Tag mapping is independent of geocoding and missing address fields.
        from resource_adapter import _categories
        self.assertEqual(_categories(record['tags']), ['Everyday essentials'])
        self.assertEqual(_categories(['food','basic needs']), ['Food assistance','Everyday essentials'])


if __name__ == "__main__":
    unittest.main()
