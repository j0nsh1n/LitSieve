# Plan — Admin panel: tabs, one action model, and the controls that were missing

Build doc, written to be executed by someone who has not seen the design
conversation. Approved 2026-10-14; the mock-up lives outside the repo.

## Goal

Turn the one-column `/admin` page into five tabs, give every action the same
dialog and the same result reporting, and put a screen on the routes that
have none today (tickets, Ollama control, content rollback), plus two new
read-only views (host health, recent admin activity).

Version stays 6.0.0. CHANGELOG entries go under Unreleased.

## Non-goals

- **No roster.** `test_helpdesk_no_roster_dump_or_promote` is a deliberate
  rule: search and queues stay capped at 25 and the overview is counts only.
- **No charts.** Nothing stores history yet; counts are live only.
- **Ship stays on `/ops`.** It is a workbench with its own CSS. Admin links to
  it and shows its last deploy state (`GET /api/ops/deploy-state`, already
  admin-gated).
- **No new write capability on the host** beyond the Ollama start/stop routes
  that already exist.
- **No look changes.** The page keeps inheriting the admin account's look
  from `base.html`; the tab strip and two-pane layout are new shared CSS.

## Target structure

| Tab | Shows | Routes |
|---|---|---|
| Overview | "What needs you" tiles (one per queue, count, click opens the queue), account counts, recent admin activity | `/api/admin/overview` (+ queue counts), new `/api/admin/activity` |
| Accounts | search + queue chips on the left, one account on the right (desktop) or stacked (phone); detail groups: Access, Jobs, Storage, Account, Notes, Tickets, Timeline (paged) | existing user routes; timeline gains `offset` |
| Tickets | status chips (open, waiting on student, investigating, resolved, all), list, thread, reply, status change | `/api/admin/tickets`, `/{id}`, `/{id}/reply`, `/{id}/status` |
| Site | banner (draft, publish, take down, roll back) and copy editor with revision history and roll-back buttons | banner routes, `/api/admin/content*`, `/{key}/rollback` |
| Host | version, uptime, SMTP, quota (from overview); backup, watchdog, disk, Laya (new); source health; Ollama start/stop with state; Ship summary + link | `/api/admin/overview`, new `/api/admin/host`, `/api/ai/ollama/start|stop`, `/api/ops/deploy-state` |

URL hash selects the tab and, where it applies, the queue, ticket or account
(`#accounts/locked`, `#tickets/214`, `#accounts/<id>`), so a link in a note or
a tile lands on the right thing and the browser back button works.

## One action model

- `app/routes/admin.py` keeps one list, `ACTIONS`, each entry `name`,
  `label`, `destructive`, `confirm_word` (username or `publish`). The template
  renders buttons from it (`data-action`, `data-destructive`), and the POST
  routes validate `reason` and the confirm word from the same list, so the
  client and server cannot disagree. The unused `_DESTRUCTIVE` goes away.
- `admin.js` has one `runAction(name, extraFields)`: asks through the
  existing `promptAction` (reason always, the confirm word when destructive),
  posts, shows one toast and one inline status line, then reloads the
  account. The five functions that each repeat the post, status, toast and
  reload steps (`act`, `retryEmbed`, `setEmail`, `quotaBump`,
  `deleteOneLibrary`) collapse into it; `postSelected` becomes its transport.
- A `_admin_post(request)` helper in the routes returns `(user, error)` after
  auth, CSRF and admin checks, replacing the preamble repeated in the 35
  routes that call `_require_admin` today.
- Reset MFA: button and route removed (the host has no MFA; the route also
  skipped CSRF and the reason check).

## Slices, in order (each its own PR off `main`, each green before the next)

1. **Shell and action model.** Tab strip (`.tabs`, `role="tablist"`, arrow
   keys, hash routing) in `style.css`; two-pane Accounts; `ACTIONS` list and
   `runAction`; `_admin_post`; drop Reset MFA; stale docstring and the
   `tomorrow` variable fixed; timeline and notes paged (25, "Show 25 more").
   Timeline, notes and auth events need an `offset` in their three storage
   queries and on the account route (none has one today).
   No new capability. Complete when: every existing admin test passes, a new
   test asserts the template's `data-action` buttons equal `ACTIONS`, and
   the Chromium drive clicks every button once in two looks.
2. **Tickets tab.** List with status filter, thread, reply, status change,
   per-account ticket links. Complete when: the three previously UI-less
   routes have HTTP tests and the drive replies to a ticket and closes it.
3. **Site and Host.** Content revision list with roll-back buttons (the
   revisions and the rollback route already exist; only the screen is new);
   banner confirm dialog; `GET /api/admin/host` (last backup file time and size from
   `BACKUP_DIR`, watchdog state from `logs/watchdog_state.json`, free bytes
   on `USER_DATA_DIR`, Laya `/health`); Ollama start/stop buttons with state;
   Ship summary. Complete when: the host route has a test with a fake backup
   dir and state file, and the drive starts and stops Ollama on the
   throwaway server (or shows the "control disabled" state when it cannot).
4. **Overview.** Tiles with counts (one `GET /api/admin/queue-counts`), and
   `GET /api/admin/activity` (newest 50 admin actions across accounts: a new
   cross-account query over `support_actions`, plus support-view starts
   from `support_views`, both ordered by their shared `created_at` format;
   every existing read of those tables is filtered to one account). Complete when: the
   activity route has a test showing two accounts' actions interleaved by
   time, and the tiles' counts match the queues they open.

## Tests

- Keep every test in `tests/test_admin.py`; add per slice as listed.
- `tests/test_admin_actions_table.py`: buttons in `templates/admin.html` ==
  `ACTIONS`; every destructive route rejects a missing confirm word.
- JS: `tests/test_static_js.py` already parses `admin.js` with esprima; add
  one check that every `data-action` in the template (new in slice 1) has an
  entry in `runAction`'s table.
- Chromium drive on a throwaway server (scratch `users.db`, `ADMIN_USERNAMES`
  set, SMTP off): each slice's "complete when" list, screenshots in the PR,
  light and dark in Workshop and Night.

## Decisions (2026-10-14)

- Tabs and names as above.
- Publishing or taking down the banner requires typing `publish`, since every
  student sees the result.
- Version stays 6.0.0; entries go under Unreleased.
