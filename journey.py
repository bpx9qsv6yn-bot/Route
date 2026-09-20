"""Presentation-ready journey choices; all reachability still comes from the engine."""
from __future__ import annotations

from datetime import date, datetime
from fairroute import access_burden

SORT_OPTIONS = ("Lowest burden", "Shortest trip", "Least walking / rolling")


def option_result(row: dict, option, wheelchair_required: bool = False) -> dict:
    """Recompute uncertainty for the selected option, not an unrelated bus trip."""
    result = dict(row)
    reasons = []
    if row["access_status"] == "confirm":
        reasons.append("facility")
    if wheelchair_required and option.mode == "RTS" and option.accessibility_uncertain:
        reasons.append("transit")
    result.update(best_option=option, confirmation_reasons=reasons, burden=access_burden(option, reasons))
    result["status"] = "does_not_match" if row["access_status"] == "does_not_match" else ("confirm" if reasons else "reachable")
    return result


def rank_results(rows: list[dict], sort: str, wheelchair_required: bool = False) -> list[dict]:
    def key(row):
        option = row["best_option"]
        metric = {"Lowest burden": row["burden"]["points"], "Shortest trip": option.minutes,
                  "Least walking / rolling": option.walking_minutes}[sort]
        return (row["status"] == "confirm", metric, row["burden"]["points"], option.minutes, row["name"])
    ranked = []
    for row in rows:
        if row["status"] in {"outside_limit", "does_not_match"}:
            continue
        choices = [option_result(row, option, wheelchair_required) for option in row["travel_options"]]
        if choices:
            ranked.append(min(choices, key=key))
    return sorted(ranked, key=key)


def category_matches(row: dict, category: str) -> bool:
    return category == "All resource types" or category in {
        value.strip() for value in str(row.get("categories") or row.get("category", "")).split("|")
    }


def schedule_notice(meta: dict, today: date | None = None) -> str:
    raw = str(meta.get("feed_end_date", ""))
    try:
        end = datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        return "Schedule validity is unknown. Confirm RTS service before traveling."
    if end < (today or date.today()):
        return f"The bundled RTS schedule ended {end:%b %d, %Y}. These are planning estimates; confirm current service before traveling."
    return f"Scheduled estimates through {end:%b %d, %Y}, not live departures. Confirm current service before traveling."


def itinerary_steps(option, router) -> list[dict]:
    steps = []
    for leg in option.legs:
        detail = ""
        if leg.kind in {"bus", "transfer"}:
            start = router.stops.get(leg.from_stop_id, {}).get("name", "Boarding stop")
            end = router.stops.get(leg.to_stop_id, {}).get("name", "Arrival stop")
            detail = f"{start} → {end}"
        steps.append({"kind": leg.kind, "label": leg.label, "detail": detail, "minutes": round(leg.minutes)})
    return steps


def trip_summary(search: dict, row: dict, router) -> str:
    option = row["best_option"]
    lines = ["FAIRROUTE · TRIP SUMMARY", "", f"From: {search['origin_name']}", f"To: {row['name']}",
             f"Address: {row.get('address', '')}", f"Travel: {option.mode} · {option.minutes} min estimated",
             f"Walking / rolling: {option.walking_minutes:.0f} min · {option.walking_distance_miles:.2f} mi",
             f"Transfers: {option.transfers} · Expected waiting: {option.wait_minutes:.0f} min",
             f"Access Burden: {row['burden']['points']}/100 (lower is easier)", "", "JOURNEY"]
    for i, step in enumerate(itinerary_steps(option, router), 1):
        lines.append(f"{i}. {step['label']} · about {step['minutes']} min" + (f" — {step['detail']}" if step['detail'] else ""))
    lines += ["", "Step times are approximate. Expected waiting is listed separately; totals are rounded.",
              "", "BEFORE YOU GO", f"Hours: {row.get('hours') or 'Confirm with the service'}",
              f"Phone: {row.get('phone') or 'Not listed'}", f"Website: {row.get('website') or 'Not listed'}",
              f"Access needs: {', '.join(search['access_needs']) or 'None selected; facility access has not been verified for your needs.'}",
              f"Accessibility: {row.get('accessibility_notes') or 'Confirm the facilities you need.'}",
              "Confirm opening hours, eligibility, availability, and required documents.",
              schedule_notice(router.meta), f"Source: {row.get('source', '')}",
              "Local route geometry is not a guarantee of sidewalk or curb-cut conditions."]
    if row["confirmation_reasons"]:
        lines.append("Access to confirm: " + ", ".join(row["confirmation_reasons"]))
    return "\n".join(lines) + "\n"
