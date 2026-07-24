# Tests & guardrails

Run from the repo root:

```bash
SECRET_KEY=x DEBUG=true python -m pytest -q
```

## Policy (every feature change)

Tests must catch **real regressions**, not just smoke. When you **add, fix, or remove** a feature, **edit tests in the same PR**. Prefer contracts (auth, isolation, deleted surfaces, fail-closed errors) over brittle HTML snapshots. One focused test per bug beats a flaky mega-suite.

| Concern | Where it lives |
|--------|----------------|
| Product invariants (deleted/required routes, auth, Account structure, clone wording) | `test_guardrails.py` |
| AI opt-in / no bulk rewrite / panel collapsed | `test_ai_policy.py` |
| Multi-library storage + HTTP isolation | `test_libraries.py`, `test_libraries_http.py` |
| Clone codes (not live view; notes/clusters stripped) | `test_shares.py`, `test_shares_http.py` |
| AI settings write gate | `test_ai_settings_write_gate.py` |
| FETCHERS ↔ catalog ↔ citations ↔ URLs | `test_source_catalog.py` |

## Hard rules

1. **Enumerate routes** with `conftest.route_paths(app)` (OpenAPI-backed). Never loop bare `app.routes` — FastAPI stores `include_router` results as wrappers, so that list is almost empty and guardrails would pass vacuously.
2. **Delete a route** → add it to the deleted set in `test_guardrails.py` (or drop required asserts). **Add a route** → assert it exists + unauth → 401/403 where it matters.
3. **Clone codes** are clone-only: no notes/stars/clusters; owner data must not change if the joiner mutates their copy; user-facing errors say **library code**.
4. **Multi-library**: work binds to the **active** library; no cross-account leak; cannot delete the last library.
5. If a guardrail fails, restore the invariant or deliberately update the test *and* product intent — do not delete a guardrail just to go green.

Patch `core.*` in HTTP tests (e.g. `user_db`), not a stale `from app.core import user_db` binding, so monkeypatches reach the handlers.
