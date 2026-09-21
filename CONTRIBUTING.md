# Contributing

FairRoute is currently a prototype, but changes should preserve the project's core trust boundaries: deterministic calculations, explicit uncertainty, and clearly labeled demonstration data.

## Local verification

Before opening a pull request, run:

```bash
python -m unittest discover -s tests
node --check web/app.js
```

## Pull-request guidance

Keep changes focused and explain any effect on:

- routing or mobility assumptions,
- accessibility evidence semantics,
- public or fallback data sources,
- synthetic/demo data,
- Gemini tool permissions or data flow,
- deployment/runtime behavior.

Do not silently relax a user's mobility or access requirement to produce a result.

## Data changes

Document the source and freshness of new external data. Do not present missing accessibility metadata as verified accessibility.

## AI changes

The optional assistant should remain a bounded interface over application tools. Numerical route, access-gap, or planning claims should continue to come from deterministic application logic.
