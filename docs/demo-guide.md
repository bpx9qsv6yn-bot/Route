# FairRoute desktop demo

Start with `python server.py`, then open http://localhost:8501 at desktop width.

## A two-minute walkthrough

1. **The problem:** A nearby resource is not necessarily a reachable resource. Start at Rosa Parks Downtown Station with Food selected.
2. **Find a journey:** Select Working Food. Point out the route on the map, the actual boarding/alighting stops, estimated waiting, and walking distance. The burden score exposes the effort hidden by distance alone.
3. **Compare choices:** Select two Compare checkboxes and open Compare trips. Show the same preferences applied to both journeys.
4. **Personalize access:** Open Preferences, choose a slower walking pace or step-free entrance, and update results. Unknown facility access is explicitly labeled; it is not treated as verified.
5. **See the wider problem:** Open Access gaps. Switch between typical walking and limited walking profiles. Sample points show how much the reachable network changes.
6. **Test a response:** Open Scenario lab. Compare more Route 26 trips with a mobility hub, and inspect the before/after results for different profiles.

## Be precise with judges

- This is an AI-assisted build with deterministic routing and transparent scoring. Do not describe it as an AI prediction system.
- Directory information comes from the Florida Community Resource Map; it is not a guarantee of eligibility or service availability.
- The bundled official fall feed is current; modeled selected-weekday service remains a planning estimate, not current departures.
- Scenario lab includes labeled demonstration data and synthetic origins. Percentages describe sample points, not residents.
- Accessibility metadata needs confirmation. Street geometry does not establish curb-cut or sidewalk quality.

## Next validation priorities

Maintain transit refreshes, verify resource eligibility and physical access with providers, and observe residents and caseworkers completing real tasks. These improve decision quality more than adding another dashboard.

## Final showcase sequence

Use the footer’s guided access example, then apply the step-free entrance requirement. The nearby fictional pantry is excluded and the farther fictional pantry becomes the candidate. Next switch Access gaps from Typical to Limited walking/rolling (17 of 44 points → 2 of 44). Finally open Planning lab at a 24-unit cap: average access 52.8% → 51.4%, least-served location 0% → 11.1%. The cap is equal; actual spend differs. All figures are modeled, not measured resident outcomes.
