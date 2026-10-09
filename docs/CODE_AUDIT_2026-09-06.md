# LitSieve code audit — 2026-09-06

> Record of the audit as written. The fixes shipped in 5.4.0 and later; what is
> still open is tracked in `roadmap.md`, Phase 11.

Repository-wide audit starting with `agents.md`, followed by `spec.md` and
`context.md`. Reviewed baseline: `26386741c95c06681ef4c4204507767f4f3b00c9`
on local `main`; audit branch: `audit/full-code-review`. This reviews existing
code, not just a proposed diff. Application version: 5.3.1.

**Verdict:** address the critical findings before another shared deployment.
There are **18 actionable findings: 4 critical, 11 major, 3 minor**. Passing
tests do not cover the failure cases below. No application fixes were made.

## Scope and limits

- Indexed the first-party application, all 17 fetchers, storage, services,
  routes, browser JavaScript, templates, operator tools, deployment configuration,
  and tests. Approximately 31,210 lines in application/JavaScript/tools code.
- Read authentication, authorization, recovery, persistence, library isolation,
  job lifetime, search/cache, AI settings, Reader checks, backup, and deployment
  paths in depth. Scanned the wider tree for credential literals, injection,
  HTML sinks, missing error handling, subprocess boundaries, and logging risks.
- Parsed all application/tool Python files. The tracked text scan covered 148
  Python files, 13 JavaScript files, 23 HTML files, and configuration/documentation.
  No credential candidates matched the key/private-key patterns used; this is
  not proof that all secrets are absent.
- This was a risk-focused whole-repository review, not a claim that every line
  of templates, CSS, tests, fixture data, or informational content was manually
  read. Generated assets, fonts, vendor packages, and Git history were not
  reviewed line by line.
- Sixteen isolated reproduction checks confirmed fifteen findings (the backup
  finding has two checks). Temporary SQLite databases, synthetic users, fake
  credentials, and intercepted outbound calls were used. The other three
  findings use code/configuration analysis, identified explicitly below.
- No production account changes, email, model downloads, service restarts,
  deployment, live Docker build, or live browser end-to-end flow was performed.
  External source behavior was fault-injected rather than tested against all
  live APIs. No claim is made about the current production host configuration.
- Existing untracked `.traceworks/`, `docs/READER_MODE_AUDIT.md`, and
  `opencode.json` were left untouched. No push or pull request was performed.

Source locations below refer to the reviewed baseline.

## Critical findings

### A01 — Ordinary accounts can redirect shared AI credentials

**Location:** `app/routes/ai.py:42`, `app/services/llm.py:420`,
`app/services/llm.py:1130`. **Confidence: high. Reproduced.**

`POST /api/ai/settings` accepts any authenticated account with CSRF and defaults
to allowing writes. It changes server-wide settings, including
`openai_base_url`. `_structured_openai` sends the existing provider key as a
Bearer credential to that URL. With writes enabled, a configured OpenAI key,
and no explicitly pinned base URL, a normal account can redirect calls and
exfiltrate that key. Subsequent calls can also disclose other users' abstract
prompts. This is particularly unsafe on the shared student deployment in the
specification; authentication alone is not authorization to configure the host.

**Evidence:** a synthetic non-admin account received HTTP 200 when setting an
`https://audit-endpoint.invalid/v1` destination. An intercepted provider request
then targeted that destination and carried the fake pre-existing provider key.
No network request or real credential was used.

**Fix:** restrict server-wide configuration and local provider controls to
operators, default writes off for shared hosts, and constrain provider
destinations. If students supply credentials, store and resolve those settings
per account instead of mutating shared configuration. Explicitly disabling
`AI_ALLOW_SETTINGS_WRITE` mitigates this path in the meantime.

### A02 — Reset tokens can take over a newly created account with a reused name

**Location:** `app/storage/user_db.py:818`, `app/storage/user_db.py:1066`.
**Confidence: high. Reproduced.**

Deleting a user leaves their password-reset tokens behind. Tokens are associated
with a reusable username, and consumption updates the account currently bearing
that username. An unexpired token issued to the old owner can therefore change
the password of a different, newly registered account using the same name.

**Evidence:** create account A, issue reset token, delete A, create account B
with the same username and a different ID, then consume A's token. Consumption
succeeded and B's stored password became the supplied replacement hash.

**Fix:** associate recovery tokens with immutable user IDs, invalidate them
atomically on deletion, and enforce deletion through foreign keys/cascades or
equivalent transactional cleanup. Cover delete/re-register cycles in tests.

### A03 — Local Docker builds can include credentials and private state

**Location:** `Dockerfile:22`, `.dockerignore:1`, `run_dev.sh:36`.
**Confidence: high. Static configuration finding.**

`COPY . .` copies the build context, while `.dockerignore` excludes only a few
specific names. It does not exclude `.env.local`, `.secret_key`, `secrets/`,
logs, development metadata, virtual environments, or SQLite WAL/SHM sidecars.
The development launcher writes a signing secret to `.env.local`; the runbooks
also use `secrets/cloudflared.env`. A local build from such a checkout can put
credentials or private state into an image layer and any registry receiving it.
Git ignore rules do not exclude files from Docker's context. This conclusion
follows Docker's documented [build-context rules](https://docs.docker.com/build/concepts/context/).

**Evidence:** compared the complete eight-entry `.dockerignore` with the broad
COPY and the documented/generated local paths. No live image was built and no
secret file contents were inspected. A clean CI checkout may avoid those files;
that does not protect the supported local-build path.

**Fix:** copy an explicit runtime-file allowlist, or comprehensively exclude
secret/state/backup/development paths. Add a synthetic build-context test that
fails if credential files or database sidecars enter the image.

### A04 — Deployment restarts kill the process responsible for rollback

**Location:** `app/operator/runner.py:77`, `app/operator/actions.py:234`,
`app/operator/actions.py:303`, `deploy/litsieve-uvicorn.service:28`.
**Confidence: high. Static process-lifecycle finding.**

The web process starts the deployment helper as a child. That helper replaces
the live checkout and calls `systemctl --user restart litsieve-uvicorn.service`
before polling health and restoring the previous commit on failure. Under the
provided unit, the helper belongs to the service it restarts and is killed
along with it. Consequently the subsequent health check and rollback cannot
reliably execute; a bad commit can remain deployed with the site down.

**Evidence:** traced the web-to-subprocess-to-restart path. The unit does not
override `KillMode`; systemd documents the default as `control-group`, terminating
remaining processes in the unit on stop. This is an inference from the supplied
unit and [systemd's lifecycle documentation](https://github.com/systemd/systemd/blob/main/man/systemd.kill.xml),
not a live restart test.

**Fix:** run deployment/restart/health/rollback in an independent supervised job
outside the web service's control group. Persist the previous revision and
outcome there so recovery survives web-process death. Test a deliberately
unhealthy deployment in a disposable systemd environment.

## Major findings

### A05 — Operator requests block the only web worker's event loop

**Location:** `app/routes/ops.py:342`, `app/routes/ops.py:353`,
`app/operator/runner.py:77`. **Confidence: high. Reproduced.**

Async routes call synchronous `run_action`, which waits in `subprocess.run`.
Validation can wait up to 240 seconds and other actions up to 180 seconds.
During that wait, the configured single worker cannot service unrelated user
requests or health checks.

**Evidence:** replaced the diff action with a 200 ms blocking stub; a concurrent
10 ms asyncio timer fired after 200 ms. The route blocked the event loop.

**Fix:** await the existing thread helper or an async subprocess interface for
bounded actions. Use an independent job for deployment as described in A04.

### A06 — Backup omits custom account databases and fails on custom data roots

**Location:** `tools/backup.py:56`, `tools/backup.py:128`, `tools/backup.py:136`.
**Confidence: high. Reproduced twice.**

Database discovery hardcodes `REPO/users.db` rather than honoring `USERS_DB`.
Archive creation also assumes every source can be made relative to the repo,
although `USER_DATA_DIR` supports other roots. A backup can omit the actual
account database while retaining library databases, or abort entirely on an
external/relative data root. Library files alone cannot restore account identity.

**Evidence:** a custom `accounts.db` existed but discovery returned no account
database. Separately, an external absolute data directory containing a database
caused `create()` to raise `ValueError` at `relative_to(REPO)`.

**Fix:** share the application's path resolution, map account and library roots
to deliberate stable archive prefixes, and exercise complete restore with
default, relative, and external absolute paths.

### A07 — Unbounded notes bypass the storage cap

**Location:** `app/schemas.py:91`, `app/routes/search.py:131`.
**Confidence: high. Reproduced.**

The note schema has no text-length limit and the mutation does not enforce
quota. An authenticated user can keep growing SQLite through notes after their
account is already over its cap, undermining the shared host's disk protection.

**Evidence:** with a 1 MB cap and the synthetic user's directory already over
that cap, posting a 1,048,577-byte note returned HTTP 200 and stored the text.

**Fix:** bound request/note size and check incremental storage growth, while
allowing deletion or shrinking notes as recovery operations. Apply the same
growth-policy review to clone/import and AI-generated storage paths.

### A08 — Stale tabs write into a different library

**Location:** `app/routes/search.py:140`, `static/js/search.js:1092`,
`static/js/common.js:1026`. **Confidence: high. Reproduced.**

Mutation requests carry article/source but no library identity. The server
resolves the account's shared active library at request time. Another tab can
switch that selection while the first tab still displays old cards. Focus
refresh updates the dropdown without invalidating those cards. Where both
libraries contain the same article key, the note or star changes the wrong
library silently; the foreign-key stale-tab check does not detect this case.

**Evidence:** two libraries contained the same paper. After switching to B,
submitting the payload from A's displayed card changed B's note and left A's
note unchanged, with HTTP 200.

**Fix:** bind reads and mutations to an explicit, ownership-validated library
ID and optionally a corpus revision. Invalidate/reload displayed results when
the active library changes. Carry the original library through fetch-to-prepare
chaining as well.

### A09 — Progress-cache eviction discards active job guards

**Location:** `app/core.py:253`, `app/core.py:468`.
**Confidence: high. Reproduced.**

The bounded progress cache evicts the oldest user even when a worker is active,
removing its future and synchronization records without stopping the worker.
The next start request sees an empty slot and can start the same job again.
Concurrent fetches can then contend over staging/corpus replacement, while
progress and cancellation no longer track the first worker.

**Evidence:** claim an active fetch, request progress for 50 other users, then
claim the first user's fetch again. The second claim succeeded.

**Fix:** keep live jobs in a registry whose lifetime follows their workers;
evict only completed history. Use unique job identities so late completion
cannot overwrite a newer job's status.

### A10 — Updated abstracts retain old vectors and key points

**Location:** `app/storage/database.py:659`, `app/services/pipeline.py:316`.
**Confidence: high. Reproduced.**

Appending/upserting a known paper can change its title or abstract without
invalidating dependent embeddings or extractive key points. Default preparation
skips keys with existing embeddings/key points. Ranking therefore uses the old
text's vector while the card displays the new abstract, and old summaries remain.

**Evidence:** stored a paper, vector, and key point; upserted a different
abstract. `missing_embeddings` remained zero and the old key point remained.

**Fix:** compare embedding input on upsert and invalidate affected derived
records transactionally. Preserve user notes/stars, and mark any deliberately
retained AI content stale rather than treating it as current.

### A11 — A cache-load race marks stale embeddings as current

**Location:** `app/services/pipeline.py:495`.
**Confidence: high. Reproduced.**

The loader captures a generation, reads SQLite outside the lock, then tags the
result with the current generation instead of the captured one. An invalidation
during the read can thus publish old IDs/vectors as fresh indefinitely until a
later mutation. Search can miss new papers or continue using removed ones.

**Evidence:** injected an invalidation during the first database load. The next
call reused the old IDs; the database loader was called only once.

**Fix:** publish only if the captured generation still matches, retry otherwise,
or tag the result with the captured generation so the next read reloads it.

### A12 — Fetchers turn upstream failures into successful empty results

**Location:** `app/fetchers/openalex.py:97`, `app/services/pipeline.py:175`.
**Confidence: high. Reproduced for OpenAlex.**

Several older fetchers catch request failures and return an empty or partial
list. The coordinator distinguishes `FetchError`, but never sees errors already
swallowed by the fetcher. A failed source is reported as no results, or a
truncated source as successful. Students can mistake incomplete coverage for a
completed search. Similar catch-and-return patterns occur in PubMed, arXiv,
Europe PMC, CrossRef, ClinicalTrials.gov, and NASA ADS.

**Evidence:** injected a typed network `FetchError` into OpenAlex's HTTP client;
`search_and_fetch` returned `[]` without propagating the error.

**Fix:** propagate typed failures or return a structured result carrying both
partial articles and error information. Preserve this distinction through
progress, final source reports, and replacement decisions. Newer fetchers that
already rethrow `FetchError` provide a useful consistency target.

### A13 — Saved AI settings become ineffective after the first application

**Location:** `app/services/llm.py:305`, `app/services/llm.py:339`.
**Confidence: high. Reproduced.**

File settings are copied into `os.environ` only when an environment value is
absent. Later saves cannot distinguish explicitly deployed environment settings
from values the application inserted itself. Changing a model/key saves new
configuration but leaves the old value effective; clearing a stored key can
also leave the old process credential active until restart.

**Evidence:** saved `audit-model-one`, then `audit-model-two`. The file/cache
contained model two, while `public_ai_settings()` still reported model one.

**Fix:** resolve immutable deployment environment settings and mutable stored
settings separately. Avoid using process environment as the settings cache, or
track ownership so application-injected values can be replaced and removed.

### A14 — Development data isolation excludes AI settings

**Location:** `app/services/llm.py:45`, `run_dev.sh:58`.
**Confidence: high. Static path finding.**

The launcher isolates account databases and library data through `USERS_DB` and
`USER_DATA_DIR`, but AI settings remain hardcoded to `user_data/ai_settings.json`
relative to the shared checkout. Starting a development instance there loads
production AI configuration, and settings writes can overwrite that file despite
using development database/data paths.

**Evidence:** traced `_settings_path()` to the fixed module constant; it does
not derive from `USER_DATA_DIR`. No production AI settings were opened or changed.

**Fix:** introduce an explicit AI settings path or resolve it from the configured
data root, with a migration/default preserving existing deployments. Set the dev
launcher to an isolated path and test configuration reads/writes in both modes.

### A15 — Operator redaction corrupts source-file responses

**Location:** `app/operator/runner.py:90`, `static/js/ops.js:667`.
**Confidence: high. Reproduced.**

The runner redacts the serialized JSON before parsing it. Its non-whitespace
match can consume JSON terminators after ordinary source expressions such as
`token = make_token()`. Parse failure can still become `ok: true` when the action
exited zero, and the editor substitutes an empty string for missing content.
Even where JSON survives, redaction changes the editable source. Saving edits
from this view risks replacing real code with incomplete or modified content.

**Evidence:** serializing a successful read-file response containing
`token = make_token()` and a newline, then applying `redact`, produced invalid
JSON. This expression contained no credential.

**Fix:** parse/validate structured results first, treat invalid action output as
failure, and redact diagnostic fields rather than source documents. Continue
denying sensitive files at the file-access boundary. Require valid string
content before opening an editor tab.

## Minor findings

### A16 — Reader numeric matching ignores confidence-interval bounds

**Location:** `app/services/reader_facts.py:150`,
`app/services/reader_verify.py:158`. **Confidence: high. Reproduced.**

Confidence intervals are represented by their first number, commonly 95, and a
`ci` unit. Numeric matching consequently accepts different endpoints with the
same confidence level. P-value parsing likewise drops its comparison operator.
The numeric-detail warning can miss materially changed statistics. This remains
a defect in a warnings-only check; it does not imply the product promises
clinical or factual verification.

**Evidence:** `95% CI 1.2 to 1.8` matched `95% CI 4.2 to 9.8` using the current
extraction and comparison functions.

**Fix:** represent confidence level and both bounds explicitly; retain p-value
operators. Compare structured values and add changed-bound/operator fixtures.
Bump the verifier version when correcting the cached-check behavior.

### A17 — Configured embedding aliases resolve to the wrong model path

**Location:** `app/services/embeddings.py:164`,
`app/services/embeddings.py:197`. **Confidence: high. Reproduced.**

`EXTRA_EMBEDDING_MODELS` accepts `shortname=org/model`, and validation accepts the
alias, but model loading consults the fixed `MODELS` dictionary. It tries to
load the short name rather than the configured repository, causing preparation
failure or loading an unintended repository if that short name exists.

**Evidence:** configured `auditmodel=example/real-model`. The catalog returned
the intended path, but an intercepted loader received `auditmodel`.

**Fix:** use the validated effective model catalog for path resolution and test
both raw repository names and aliases without downloading weights.

### A18 — Density clustering crashes on a one-paper corpus

**Location:** `app/services/clustering.py:110`, `app/routes/corpus.py:319`.
**Confidence: high. Reproduced.**

The HDBSCAN path lacks the small-corpus guard used by other clustering paths.
For one embedding, the PCA fallback requests two components from one sample,
raising `ValueError`; the route turns this valid small corpus into a server error.

**Evidence:** `ArticleClusterer(method='hdbscan').fit(np.ones((1, 16)))` with the
optional UMAP import unavailable raised `n_components=2 must be between 0 and
min(n_samples, n_features)=1`.

**Fix:** define a small-corpus outcome before dimensionality reduction, such as
one group/noise or a clear validation response. Cover zero, one, two, and fewer
than minimum-cluster-size inputs.

## Validation evidence

Commands used the existing Python 3.14 virtual environment; no dependencies
were installed or upgraded.

| Check | Result |
| --- | --- |
| `SECRET_KEY=audit-local-only DEBUG=true ./venv/bin/python -m pytest -q` | **716 passed, 321 warnings in 70.89s** |
| `./venv/bin/ruff check .` | **All checks passed** |
| `./venv/bin/pyright app` | **60 errors, 6 warnings**; existing report-only backlog |
| `./venv/bin/pip-audit --format json` | **Failed:** one vulnerability in installed `pip 26.1.2`; fix version reported as `26.2` |
| Isolated failure-case harness | **16/16 checks confirmed**, covering 15 findings |
| Application/tool AST parse and wider source scans | Completed; no matching credential literals found by the targeted scan |

The dependency result was `PYSEC-2026-3721` / `CVE-2026-13346` /
`GHSA-qwm4-qh6w-59xr`: pip handling of doubly encoded package-index URLs.
The auditor describes a malicious-index precondition; this is an installed
tooling finding, not evidence of a remotely exploitable application endpoint.
Upgrade the affected installer and repeat the gate. Installed
`torch 2.13.0+rocm7.1` and `triton-rocm 3.7.1` were skipped because the auditor
could not find those distributions on PyPI. Their vulnerability status remains
unverified. Dependency reproducibility remains limited by the intentional lack
of a lockfile.

Temporary evidence for this session is in `/tmp/litsieve_audit_repros.py` and
`/tmp/litsieve-pip-audit.json`; these are not committed and may disappear with
environment cleanup. The deterministic failing cases and observed results are
recorded above. Production restart/build testing remains outstanding as stated
under A03/A04. No application change was made, so there is no fixed-behavior
validation claim.

## Guidance and specification discrepancies

All four required project context files were already tracked. `context.md`
contained workflow/policy statements despite `agents.md` restricting policy to
`agents.md` and `spec.md`: examples include instructions about test environments,
public-page scripts, test patch targets, and Advanced-mode capability. These
were flagged and not adopted or moved into another policy document. The audit
handoff update replaces the stale test/status entry with measured state.

**spec.md drift:** `app/fetchers/dblp.py:96` synthesizes an abstract from title and
venue when no abstract exists, while the specification requires skipping
abstract-less records and describes AI reading of an abstract. Human decision
needed: enforce the existing specification, or explicitly approve metadata-only
DBLP records with a distinct data flag/UI label and AI eligibility rule.

The AI settings path is explicitly fixed in the storage description but conflicts
with complete development isolation (A14). If a configurable path is approved,
update that storage description. The specification's shared-instance/student
model also needs an explicit distinction between operator-wide AI configuration
and any intended student-owned credentials (A01).

`agents.md`, `spec.md`, roadmap scope, and application code were not modified.
No user-visible application behavior changed, so no release/changelog entry was
added. The documentation commit records the findings and current handoff only.
