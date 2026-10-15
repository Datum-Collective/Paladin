# Round 2 compliance audit

Audited 15 October 2026 against the Round 2 requirements supplied to the team. The official technical rulebook attachment itself was not available in this workspace, so requirements that depend on wording not reproduced in the brief are marked **Unverified**.

## Compliance matrix

| Requirement | Evidence | Status | Required correction | Severity | Deadline |
| --- | --- | --- | --- | --- | --- |
| Primary branches are `main`, `bugbounty`, `fixing` | Local and remote branches are `main`, `bugbounty`, `fix` | Non-compliant | Do not rename `fix`. At the start of the organizer-defined fixing phase, create `fixing` at the frozen `bugbounty` SHA. Obtain organizer guidance on whether `fix` must remain until then. | P0 | Before fixing phase |
| Frozen bounty branch | `bugbounty` is `d273e74`; its deployed image and freeze record are not present in the repository | Unverified | Record the SHA, image digest, deployment URL and successful evaluator smoke test before the attack phase. Treat the branch as read-only after this record. | P0 | 16 October |
| No loss or history rewrite | `git fsck` found no corruption; merges are recorded in `main`; recovery tags exist | Compliant | Retain recovery tags. | P2 | Ongoing |
| Meaningful activity within development intervals | Commit log contains active work throughout the observed 15 October period | Partially verified | Preserve GitHub push/audit evidence; this local clone cannot independently prove every required 120-minute interval. | P1 | Before submission |
| Reproducible container build | Docker image built locally after consolidation | Compliant locally | Record image digest and run the documented compose smoke test on the evaluator target. | P1 | Before freeze |
| Authentication and persistent data | Supabase GitHub sign-in, RLS migrations and setup steps are documented; no live credentialed verification evidence is stored | Unverified | Run `scripts/check_signin.py`, apply migrations, and record a clean evaluator-account sign-in and persistence check. | P0 | Before freeze |
| Actual input processing and generated outputs | Parsers, graph analysis, repository scan, remediation and API routes are implemented; synthetic-data provenance is documented | Compliant in code | Complete a fresh Docker smoke test using the sample scenario and save its result. | P1 | Before freeze |
| At least five major operations | Ingest, graph, paths, fixes, repository scan, remediation, assistant and health APIs are implemented | Compliant in code | Verify five operations against the deployment with an evaluator account. | P1 | Before freeze |
| Independent evaluator access | README describes individual GitHub sign-in; a running evaluator URL/account check is absent | Unverified | Publish the evaluator URL and test a new GitHub account with no team privileges. | P0 | Before freeze |
| AI/ML disclosure | README states Claude/ OpenAI API use and makes no local-training claim | Compliant | Keep the disclosure accurate; do not claim a trained local model. | P2 | Submission |
| Synthetic-data disclosure | README identifies EvidenceForge scenarios and synthetic data | Compliant | Keep provenance and license references with the deployed sample. | P2 | Submission |
| README completeness | README includes architecture, environments, Docker, variables, Supabase, tests, limitations and third parties | Partially verified | Add verified team names and evaluator deployment URL/access steps. Align Compose's root `.env` convention with the README's `backend/.env` instructions. | P1 | Before freeze |
| CI evidence | GitHub Actions runner jobs fail before steps run; Docker is skipped | Blocked externally | Preserve run URLs and report runner/billing allocation failure to organizers. Do not weaken workflows or claim green CI. | P0 | Immediately |
| Bug-fixing-only scope | Recent work includes merged feature work; no post-audit feature change is proposed | At risk | From this point, restrict changes to reproducible defects, security, integrity, reliability and tests. | P1 | Immediately |

## Verified technical risks

1. **Scanner denial of service (P0):** `backend/tests/test_audit_regressions.py` reaches the hostile-long-line scan case and the backend test process does not terminate. Repository-controlled content can pin a scan worker. Bound per-line work or replace the expensive expression path, then add a terminating regression test.
2. **Spoofable client identity (P1):** the Docker command trusts forwarded headers from every peer (`--forwarded-allow-ips='*'`). Direct callers can influence the client IP used by rate limiting. Restrict trusted proxy IPs or omit proxy-header trust when the app is not behind Caddy.
3. **Docker daemon exposure in sandbox mode (P1):** `docker-compose.sandbox.yml` mounts the host Docker socket into the main application. This is a host-level capability if the application process is compromised. Deploy this profile only on a dedicated runner host, restrict the socket with a proxy, or use an external sandbox manager.
4. **Tracked workstation artifacts (P2):** `.DS_Store` and `docs/.DS_Store` are tracked. Remove them in the fixing phase and ignore them.

## Safe branch transition plan

1. Freeze `bugbounty` at `d273e74` only after recording the deployment digest and evaluator smoke-test evidence.
2. Do not push to `bugbounty` during the attack phase.
3. When organizers start the fixing phase, create `fixing` from exactly `d273e74`; do not rename `fix`, whose ancestry is different.
4. Commit only reproducible fixes and regression tests to `fixing`.
5. Validate each fix locally, merge `fixing` into `main` only after the required sequence, and leave `bugbounty` unchanged until organizers close evaluation.

## Validation record

The last local consolidation validation recorded backend tests (393 passed before the diagnostics merge), frontend tests and production build (59 passed), desktop tests (38 passed), and a Docker build. After the diagnostics merge, frontend build and desktop tests passed. The full backend suite is currently blocked by the hostile-long-line scanner regression above; it must not be represented as passing.
