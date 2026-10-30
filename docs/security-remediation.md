# Audit remediation — 30 October 2026

All S1–S7 and P1–P5 findings from the local audit have implementation changes.
The original audit is a point-in-time record; this document describes the fixes.

| Finding | Change | Regression coverage |
| --- | --- | --- |
| S1 privilege escalation / cross-user Djoser edits | Public privilege flags read-only; owner-only auth-user objects; deletion disabled on alternate API | `user_management.tests_security`, existing account contracts |
| S2 profile scope escalation | Profile writes use the central management serializer and safe self-edit fields; direct-permission source-name bug fixed | Self scope/role escalation blocked, allowed preference/name/admin assignment preserved |
| S3 unrestricted SQL assistant | Removed SQL/database tools; authenticated user passed to an allowlisted, read-only inventory resource adapter; existing API permissions, scoping and pagination reused | Disabled assistant rejected; scoped reads exclude hidden stock; unsupported resources and denied modules rejected; existing response/stream contracts |
| S4 missing CSRF | Unsafe cookie requests, login and refresh enforce CSRF and Origin; frontend sends tokens including multipart/streaming/voice; login rotates CSRF | Trusted writes succeed; missing/untrusted tokens fail; bearer clients remain supported |
| S5 anonymous provider spending | Voice verifies backend session and chatbot preference, transactional per-user quotas in Postgres, bounded body/text/prompt, server-selected model and provider timeout | Anonymous/forged/disabled/over-quota rejected; valid translation/transcription preserved; oversized streaming uploads rejected before parsing; provider errors sanitized |
| S6 logout replay | Presented refresh token blacklisted; access lifetime 15 minutes; frontend retries after refresh | Refresh replay rejected after logout; valid refresh works; cookie domain/CSRF rotation and frontend renewal covered |
| S7 dependency advisories | Supported Django security patch, Next.js and affected Python/JS dependencies updated; backend full lock supplied | Full behavior suites, TypeScript and production build; npm and pip audits |
| P1 distribution N+1 | Bulk ancestor tags/source contracts and parent category loading; stable row order | Query growth bounded from 1 to 25 rows, plus existing distribution/tag/contract tests |
| P2 duplicate notification work | Summary and alerts share one server snapshot and one polling request | Summary equals alerts API; existing notifications tests; mounted provider polling test checks contents/counts |
| P3 whole-dataset stock loading | Server movement pagination/filtering; store inventory and selected-item reference loading; correction source fetched by ID when off-page | Pair/effective-status pagination, domain/scope checks, existing movement/stock business tests, scoped frontend data-loading tests |
| P4 synchronous provider work | Embeddings moved to scheduled idempotent command; short serial submission/status requests replace waiting loop | Save stays searchable without provider call; worker skips unchanged/stale results; signed user-bound serial ticket and unchanged matching/non-mutating preview |
| P5 avatar object URLs | Preview lifecycle hook revokes replaced/unmounted URLs | Mounted hook checks current preview and both cleanup paths |

Deployment details and the binary serial-preview 202 contract are documented
in `deployment.md`. Semantic indexing now needs the scheduled command when
enabled. No paid provider calls or production deployment were performed.

## Final verification

- Backend: **394 tests passed** on native PostgreSQL, including the main
  inventory suite, user management, inspection PDF/scope, auth, provider jobs,
  hybrid search, notifications and settings.
- Frontend: **360 tests passed**, **1 optional integration test skipped** because
  `langchain-agent-chat-openrouter` is absent. The skipped test checks source
  in that external repository; local Copilot behavior tests remain enabled.
- Actual upgraded OpenUI packages render a real response in a separate test;
  this compatibility test does not mock the rendering dependencies.
- TypeScript, Next.js production build, Django checks, migration consistency,
  Python dependency compatibility and Git whitespace checks pass.
- `npm audit`: **0 known vulnerabilities**. `pip-audit` against all **95 pinned
  backend packages**: **0 known vulnerabilities**, including the final SDK fix.
- Live localhost HTTP checks: CSRF bootstrap/login/current user and movement,
  distribution and notification reads succeed; missing-CSRF write returns 403;
  logout succeeds and refresh replay returns 401; frontend login page returns 200.
- The extra embedding SDK construction test reproduced and fixed a pre-existing
  HTTP-client compatibility error; no provider network request was needed.

No live paid-provider request, production load test or deployed reverse-proxy
review was performed. Chrome DevTools could not connect locally, so browser
visual inspection was unavailable; React integration tests, production build
and live HTTP checks supplied frontend validation. Zero scanner findings do
not establish absence of all possible security defects.

Both servers were restarted for localhost verification. The voice-usage
migration is applied locally. Real application records were retained. All
changes remain local; no remote push or deployment was performed.
