# Security report

**Prototype. Not an official service. All identity, payment and data services are simulated.**

What the platform enforces, where, and the test that proves it. Every test named here exists and passed in the
run below. Paths are relative to `backend/`. Generated from a real run on branch `track/a3-keys-limits-security`;
re-run with:

```
cd backend && uv run ruff check . && uv run mypy && uv run pytest -q
uv run pytest -q tests/security          # the security suite alone (about 40 s)
```

**Run (Sat 21 Nov 2026):** ruff clean, mypy clean, **662 passed, 2 skipped (Tesseract not installed), 2 xfailed** (both
pin finding 2 in section 2; they turn into failures once it is fixed, as a reminder to drop the markers). Live check on a local server (port 8105, seeded demo data): every API-key, rate-limit
and probe behaviour in sections 1.6 and 1.7 was repeated over HTTP with the demo accounts; the server log held no key
material.

The security suite (`tests/security/`) is driven by the policy registry (`app.core.policy.describe_routes`). A route
added by any track is covered by the authorisation matrix, the IDOR checks and the cross-department list checks
without editing a test. A route with a new kind of id fails the IDOR test until a real object for it is added to
`tests/security/support.py`.

## 1. Controls

Result is the outcome of the run above. Numbers in brackets are parametrised cases.

### 1.1 Who may call what

| Control | Enforced in | Proven by | Result |
|---|---|---|---|
| Every route declares exactly one `Policy` or `Public` marker; the build fails otherwise | `app/core/policy.py` | `tests/unit/test_contracts_unit.py::test_every_route_declares_who_may_call_it`, `::test_a_route_without_a_policy_is_caught` | pass |
| Public routes are a reviewed allowlist (sign-in, refresh, logout, registration, verify code, info, demo accounts, health, metrics) | `app/core/policy.py` | `tests/security/test_authorization_matrix.py::test_every_route_declares_a_policy_and_public_routes_are_an_explicit_list` | pass |
| A caller the policy does not admit (anonymous, each role outside the policy, an API key without the scope) gets 401/403 with a stable code, on every protected route | `Policy.__call__`, `core/deps.get_credential` | `tests/security/test_authorization_matrix.py::test_callers_the_policy_does_not_admit_are_refused_and_change_nothing` [62 routes] | pass |
| A refused request writes nothing: every row of both test departments hashes the same afterwards | same | same test (a count and content hash of the departments' rows in every table but `plans`, before and after; new `audit_log` rows checked one by one) | pass |
| Every refusal of a known caller is audited once, in its own committed transaction | `core/audit.write_independent`, `Policy._deny`, `people/context.deny` | same test (one `access.denied` row per refusal); `tests/integration/test_audit_and_api.py::test_auditor_can_verify_and_browse_but_officer_cannot` | pass |
| IDOR: a random id and another department's real id both answer 403/404, show nothing of it and change nothing | RLS + service lookups | `tests/security/test_idor.py::test_a_random_id_and_another_departments_real_id_reveal_nothing` [29 routes] | pass |
| Lists read by another department's staff and API keys contain nothing of ours | RLS + tenant filters | `tests/security/test_idor.py::test_lists_never_show_another_departments_records` [24 routes], `::test_an_api_key_reads_only_its_own_department` | pass |
| Inside a department a citizen reaches only their own records | `people/context.resolve_person`, `applications/service.load_owned`, RLS | `tests/security/test_person_boundaries.py::test_a_citizen_cannot_reach_another_persons_records` [7 routes], `app/modules/applications/tests/test_applications_api.py::test_one_citizen_cannot_read_or_change_another_application` | pass |
| A helper reaches only families with a live delegation; each refusal is audited | `people/context.resolve_person`, RLS | `tests/security/test_person_boundaries.py::test_a_helper_reaches_only_the_families_that_delegated_to_them`, `tests/integration/test_rls.py::test_a_helper_needs_a_live_delegation_for_each_person` | pass |

### 1.2 Row Level Security (raw SQL as the runtime role)

| Control | Enforced in | Proven by | Result |
|---|---|---|---|
| The API connects as `rahat_app`: not superuser, no BYPASSRLS, owns no table | `migrations/rls.py` | `tests/integration/test_rls.py::test_runtime_role_is_not_privileged` | pass |
| Every table has RLS enabled | initial migration | `tests/integration/test_rls.py::test_every_table_has_row_level_security` | pass |
| No context means no rows, in every table | `core/db._apply_rls_context` (`after_begin`), policies | `tests/security/test_rls_bypass.py::test_without_a_context_every_table_is_empty`, `tests/integration/test_rls.py::test_without_a_context_nothing_is_visible` | pass |
| One department cannot read, change, delete or insert into another | `tenant_isolation` policies | `tests/integration/test_rls.py::test_one_tenant_cannot_read_or_write_another` | pass |
| A malformed context fails closed | `app_tenant_id()` cast | `tests/integration/test_rls.py::test_a_malformed_context_fails_closed` | pass |
| The runtime role cannot disable, rewrite or drop policies, replace the consent function, create tables, change roles, read server files or run programs | grants, ownership | `tests/security/test_rls_bypass.py::test_the_runtime_role_cannot_switch_off_or_rewrite_row_level_security` [12 statements], `::test_the_runtime_role_cannot_hand_out_privileges` | pass |
| `SET row_security = off` makes queries fail instead of showing rows | Postgres RLS | `tests/security/test_rls_bypass.py::test_row_security_cannot_be_turned_off_for_a_session` | pass |
| The same refusals can be watched live: `POST /v1/admin/security/probes` (admin, auditor) runs fixed read-only SQL as `rahat_app` and shows the database's answer; each run is audited | `app/modules/security/probes.py` | `app/modules/security/tests/test_security_api.py::test_the_database_refuses_every_bypass_and_the_run_is_audited` | pass |

### 1.3 Consent

| Control | Enforced in | Proven by | Result |
|---|---|---|---|
| Person tables need `app_can_read_person()` (SECURITY DEFINER, owner role); withdrawal stops officers, workers and API clients on the next query | `migrations/rls.py` | `tests/integration/test_rls.py::test_consent_gates_staff_access_and_withdrawal_stops_it_at_once` | pass |
| Withdrawal through the API stops an officer, a helper and an API key on the very next request, and each blocked read is audited | consent service + RLS | `tests/security/test_person_boundaries.py::test_withdrawal_stops_officers_helpers_and_api_keys_on_the_next_request`, `app/modules/consent/tests/test_consent_api.py::test_withdrawal_holds_applications_and_blocks_access_on_the_next_request` | pass |
| An expired consent counts as none | `app_can_read_person()` | `tests/integration/test_rls.py::test_an_expired_consent_counts_as_no_consent` | pass |
| Admins and auditors never read personal records | `app_can_read_person()` | `tests/integration/test_rls.py::test_admins_and_auditors_do_not_read_personal_records` | pass |

### 1.4 Audit trail

| Control | Enforced in | Proven by | Result |
|---|---|---|---|
| The app role may only INSERT and SELECT `audit_log`, `audit_anchors`, `consent_events` | grants | `tests/integration/test_rls.py::test_the_audit_log_cannot_be_rewritten_by_the_app` | pass |
| Hash chain per department detects an edited row, edited details, a deleted row and a forged hash, even by the database owner | `core/audit.py` | `tests/integration/test_audit_and_api.py::test_editing_a_row_as_database_owner_is_detected`, `::test_editing_the_details_is_detected`, `::test_deleting_a_row_is_detected`, `::test_replacing_a_row_with_a_self_consistent_forgery_breaks_the_next_link` | pass |
| Appends are serialised per department with `pg_advisory_xact_lock` | `core/audit.write` | `tests/integration/test_audit_and_api.py::test_concurrent_writers_keep_one_unbroken_chain` | pass |
| An API key is recorded as `api_key`, never as a person | `core/audit.write` | `app/modules/apikeys/tests/test_api_keys_api.py::test_a_key_that_reads_personal_data_needs_a_second_admin` | pass |

### 1.5 Sign-in and tokens

| Control | Enforced in | Proven by | Result |
|---|---|---|---|
| Access tokens: pinned HS256, known `kid`, issuer, audience, required claims, expiry; `none`, other algorithms, wrong keys and edited claims are refused | `core/security.decode_access_token` | `tests/unit/test_security_unit.py::test_bad_tokens_are_rejected` [11 forgeries], `::test_changing_the_role_in_a_token_breaks_the_signature`, `tests/integration/test_auth.py::test_requests_without_or_with_forged_tokens_are_refused` | pass |
| Short-lived tokens bound to a session row checked on every request: sign-out, revoke-all and department switch take effect at once | `core/deps.get_principal` | `tests/integration/test_auth.py::test_sign_out_takes_effect_immediately`, `::test_sessions_can_be_listed_and_revoked_all`, `::test_switching_department_invalidates_the_old_token` | pass |
| Refresh tokens rotate on use; replaying an old one revokes the whole session family | `auth/service.refresh` | `tests/integration/test_auth.py::test_refresh_rotates_and_needs_the_app_header`, `::test_reusing_an_old_refresh_token_ends_every_session_in_the_family` | pass |
| Refresh cookie is HttpOnly, SameSite=Lax, scoped to `/v1/auth`; cookie routes need the `X-Requested-With` header | `auth/router.py` | `tests/integration/test_auth.py::test_refresh_cookie_is_http_only_and_scoped`, `tests/security/test_http_probes.py::test_the_refresh_cookie_cannot_be_read_by_scripts_or_sent_cross_site` | pass |
| No enumeration: one answer for a wrong password and an unknown account, one hash check either way, unknown identifiers lock out too; registration answers the same for new and known numbers | `auth/service.login`, `core/security.verify_secret`, `people/registration.py` | `tests/integration/test_auth.py::test_wrong_password_and_unknown_account_look_identical`, `::test_unknown_identifiers_lock_too_so_lockout_reveals_nothing`, `tests/unit/test_security_unit.py::test_secret_hashing`, `app/modules/people/tests/test_registration_api.py::test_start_gives_the_same_answer_for_registered_and_new_numbers` | pass |
| Lockout after five failures; argon2id hashes | `auth/service.login`, `core/security.py` | `tests/integration/test_auth.py::test_account_locks_after_repeated_failures`, `tests/unit/test_security_unit.py::test_secret_hashing` | pass |
| Deployed instances refuse the development secrets; contract stubs never load there | `core/config.check_secrets`, `stubs_effective` | `tests/unit/test_security_unit.py::test_prod_refuses_default_secrets` | pass |

### 1.6 API keys

| Control | Enforced in | Proven by | Result |
|---|---|---|---|
| A key (`rk_<prefix>_<secret>`) is shown once; only the prefix and a SHA-256 hash are stored; no table and no log record ever holds the secret | `core/apikeys.py`, `modules/apikeys/service.py`, `core/logging.redact` | `tests/security/test_api_key_security.py::test_a_key_is_never_stored_or_logged_in_clear` (scans every table and every log record), `app/modules/apikeys/tests/test_api_keys_api.py::test_keys_are_never_stored_or_logged_in_clear`, `app/modules/apikeys/tests/test_rules_unit.py::test_keys_never_reach_the_logs_in_clear` | pass |
| Keys are admitted only by scope (`Policy(api_scopes=...)`), never by a role list, and only on reads: `GET /v1/cases`, `GET /v1/cases/{id}` (`cases:read`), `GET /v1/payments` (`payments:read`) | `core/policy.Policy` | `tests/security/test_authorization_matrix.py::test_api_keys_are_admitted_only_by_scope_on_a_small_read_surface`, the matrix above (a key without the scope on every route), `app/modules/apikeys/tests/test_api_keys_api.py::test_a_key_cannot_reach_a_route_outside_its_scopes` | pass |
| A key is looked up on every request: revocation, expiry and a suspended department stop it on the next call | `core/apikeys.authenticate` | `tests/security/test_api_key_security.py::test_the_right_scope_opens_a_route_and_revocation_or_expiry_close_it_at_once` [3 routes], `app/modules/apikeys/tests/test_api_keys_api.py::test_revoking_a_key_stops_it_on_the_very_next_request`, `::test_an_expired_key_stops_at_once`, `::test_a_key_of_a_suspended_department_stops` | pass |
| A key that reads personal data (`cases:read`) has no scopes until a second admin approves it; a refusal revokes it; consent still applies to it | `modules/apikeys/service.create_key`, `decide_key`, RLS | `app/modules/apikeys/tests/test_api_keys_api.py::test_a_key_that_reads_personal_data_needs_a_second_admin`, `::test_a_refused_approval_revokes_the_key` | pass |
| Rotation issues a new secret; the old key stops at once (or after a named grace); a revoked key cannot be revived by rotating it | `modules/apikeys/service.rotate_key` | `app/modules/apikeys/tests/test_api_keys_api.py::test_rotation_replaces_the_secret_and_the_old_key_stops` | pass |
| A wrong secret on a real prefix gets the same answer as an unknown key, is audited in that department and raises a security event | `core/apikeys.authenticate` | `app/modules/apikeys/tests/test_api_keys_api.py::test_wrong_secrets_and_malformed_keys_are_refused_and_misuse_is_recorded`, `app/modules/security/tests/test_security_api.py::test_security_events_show_refused_key_use_in_this_department_only` | pass |
| Every admitted keyed call is metered (`usage_counters`, `api_calls`, month); last use is recorded; refused calls are not metered | `core/apikeys.record_use` | `app/modules/apikeys/tests/test_api_keys_api.py::test_a_key_is_shown_once_works_for_its_scope_and_is_metered`, `::test_a_key_cannot_reach_a_route_outside_its_scopes` | pass |
| Key management is admin-only, per department, validated (known scopes only, an expiry of at most a year, at most 1,200 requests a minute, no extra fields); every change is audited | `modules/apikeys` | `app/modules/apikeys/tests/test_api_keys_api.py::test_key_management_is_validated_and_tenant_scoped`, the matrix and IDOR tests | pass |

### 1.7 Rate limits

| Control | Enforced in | Proven by | Result |
|---|---|---|---|
| Anonymous calls are limited per client network (IPv6 per /64), 300 a minute by default; 429 with `Retry-After` and a plain message; health, metrics, docs and static files are exempt | `core/ratelimit.py`, `Public.__call__` | `tests/security/test_rate_limits.py::test_anonymous_calls_are_limited_per_network_and_health_is_exempt` | pass |
| Failed credentials and probing for endpoints (404/405) count against the network | `core/deps.get_credential`, `core/errors` | `tests/security/test_rate_limits.py::test_failed_credentials_count_against_the_network`, `::test_probing_for_endpoints_counts_against_the_network` | pass |
| Each signed-in user has a bucket (600 a minute); a department's people share one lane (6,000) | `Policy.__call__` | `tests/security/test_rate_limits.py::test_each_user_has_a_bucket`, `::test_a_departments_people_share_one_lane` | pass |
| Each API key has its own limit, and keys use a separate department lane so an integration cannot lock officers out | `Policy.__call__` | `tests/security/test_rate_limits.py::test_an_api_key_has_its_own_limit_and_cannot_starve_the_officers` | pass |
| Routes declare a cost (an upload counts as ten); limits are checked before the role check, so refusals cannot flood the audit log | `core/policy.Cost`, `route_cost` | `tests/security/test_rate_limits.py::test_costly_routes_count_as_several_requests` | pass |
| Bucket arithmetic: burst then steady refill, all-or-nothing across buckets, limit changes, bounded memory | `core/ratelimit.Limiter` | `app/modules/ratelimit/tests/test_buckets_unit.py` (all 8 tests) | pass |
| Sign-in keeps its own stricter throttle (30 a minute per address) | `auth/service._throttle_ip` | `tests/security/test_rate_limits.py::test_sign_in_keeps_its_own_stricter_throttle` | pass |
| Admins see their department's current use: lanes, people, keys, API calls this month, costly routes | `app/modules/ratelimit/router.py` | `tests/security/test_rate_limits.py::test_admins_see_their_departments_current_use` | pass |

### 1.8 HTTP surface

| Control | Enforced in | Proven by | Result |
|---|---|---|---|
| Security headers (nosniff, DENY framing, no referrer, COOP, permissions policy, strict CSP, `no-store` for the API) on every kind of response, including 401, 404, 405, 413, 422 and 500 | `core/middleware.py` | `tests/security/test_http_probes.py::test_every_kind_of_response_carries_the_security_headers`, `::test_an_unexpected_failure_is_a_plain_500_with_headers_and_a_request_id`, `tests/integration/test_audit_and_api.py::test_security_headers_and_request_ids` | pass |
| HSTS behind an HTTPS proxy; only `/docs` gets the relaxed CSP Swagger needs | `core/middleware.py` | `tests/security/test_http_probes.py::test_hsts_is_sent_behind_an_https_proxy`, `::test_only_the_api_docs_get_the_relaxed_content_policy` | pass |
| No cross-origin reads: no CORS headers for any origin, preflights refused | no CORS middleware | `tests/security/test_http_probes.py::test_no_origin_is_allowed_to_read_responses_cross_origin` [4 origins] | pass |
| Errors are RFC 7807 documents with a real request id, never a stack trace, file path or library name; validation errors do not echo input | `core/errors.py`, `core/middleware.py` | `tests/security/test_http_probes.py::test_errors_are_problem_documents_without_internals`, `::test_validation_errors_do_not_echo_what_was_sent`, `tests/integration/test_audit_and_api.py::test_errors_are_problem_documents_and_never_leak_internals` | pass |
| Input models forbid extra fields | `contracts.common.Strict` | `tests/integration/test_audit_and_api.py::test_errors_are_problem_documents_and_never_leak_internals` (`is_admin`), `app/modules/apikeys/tests/test_api_keys_api.py::test_key_management_is_validated_and_tenant_scoped` (`never_expires`) | pass |
| Request bodies are capped (6 MB) | `core/middleware.py` | `tests/integration/test_audit_and_api.py::test_oversized_bodies_are_refused` | pass |

### 1.9 Data, uploads, money and rules

| Control | Enforced in | Proven by | Result |
|---|---|---|---|
| Only mock identifier shapes are accepted anywhere | `core/mockdata.py` | `tests/unit/test_security_unit.py::test_only_mock_shapes_are_accepted`, `tests/integration/test_auth.py::test_real_looking_phone_numbers_are_never_accepted`, `app/modules/people/tests/test_registration_api.py::test_only_mock_phones_and_bounded_requests` | pass |
| Identifiers encrypted with a per-department key (AES-GCM, wrapped by the master key); blind index per department | `core/crypto.py` | `tests/unit/test_security_unit.py::test_field_encryption_round_trip_and_tenant_separation`, `::test_blind_index_is_deterministic_and_scoped`, `::test_key_rotation_rewraps_the_tenant_key` | pass |
| Logs redact ids, phones, emails, tokens and API keys, and cannot be forged with newlines | `core/logging.redact` | `tests/unit/test_security_unit.py::test_logs_are_redacted`, `app/modules/apikeys/tests/test_rules_unit.py::test_keys_never_reach_the_logs_in_clear` | pass |
| Uploads: type by magic bytes, 5 MB cap, pixel cap (decompression bombs), re-encoded without EXIF, random storage name, uploaded filename ignored | `documents/imaging.py`, `documents/service.py` | `app/modules/documents/tests/test_imaging_unit.py::test_magic_bytes_decide_the_type`, `::test_non_images_are_refused_with_415`, `::test_size_cap`, `::test_decompression_bombs_are_refused_from_the_header`, `::test_reencode_strips_exif_and_keeps_pixels`, `app/modules/documents/tests/test_documents_api.py::test_upload_abuse_is_refused`, `::test_traversal_filename_is_ignored_and_the_stored_copy_is_clean` | pass |
| A payment exists only for an approved decision, once per application under concurrency, with a state machine and a different second officer above the limit | `payments/service.py`, `payments/rules.py` | `app/modules/payments/tests/test_payments.py::test_no_payment_without_an_approved_decision`, `::test_two_concurrent_requests_create_one_payment`, `::test_above_the_limit_a_different_officer_must_release_it`, `app/modules/payments/tests/test_rules.py::test_state_machine_allows_only_the_listed_moves`, `::test_the_second_approver_must_be_someone_else` | pass |
| Clients cannot mark a field verified; only the server sets `qr_signed` or `registry` | `applications` | `app/modules/applications/tests/test_applications_api.py::test_client_sent_verified_or_server_provenance_is_rejected` | pass |
| Published rule versions and stored decisions cannot be rewritten, even by a buggy service; a second admin publishes | migration 0002, `rules/service.py` | `tests/integration/test_immutability.py::test_a_published_rule_version_cannot_be_rewritten`, `::test_a_stored_decision_cannot_be_rewritten_but_can_be_linked_to_its_case`, `app/modules/rules/tests/test_rules_api.py::test_rollback_is_a_new_version_that_needs_a_second_admin` | pass |

## 2. Holes found during this work

| # | Finding | Status | Reproduction |
|---|---|---|---|
| 1 | Unexpected errors (500) were rendered by Starlette outside every middleware: no security headers, no `X-Request-ID`, and `request_id: "-"` in the body, so the advice "quote the request id" was useless and the error log lost its correlation id. | **Fixed** in `core/middleware.py`: unexpected errors are answered inside the request middleware, logged once with the request id, then re-raised so servers and tests still see them. Regression: `tests/security/test_http_probes.py::test_an_unexpected_failure_is_a_plain_500_with_headers_and_a_request_id`, `::test_unexpected_errors_still_reach_the_test_client`. | On a commit before the fix: monkeypatch `app.modules.system.router.describe_routes` to raise, call `GET /v1/system/policies` as an admin with `TestClient(app, raise_server_exceptions=False)`: the response has only `content-length` and `content-type` headers and `"request_id":"-"`. |
| 2 | The consent function `app_can_read_person` is `SECURITY DEFINER` with `SET search_path = public`. Postgres searches `pg_temp` first for table names unless it is listed last, and `rahat_app` may create temporary tables. A session running SQL as `rahat_app` can create a temporary `consents` table and read a person whose consent was withdrawn. | **Reported** (migrations belong to the lead). Pinned by strict xfails that start passing when fixed: `tests/security/test_rls_bypass.py::test_a_temporary_table_cannot_stand_in_for_the_consent_table`, `app/modules/security/tests/test_security_api.py::test_the_consent_function_cannot_be_hijacked_by_a_temporary_table`. The live probe `consent_function_is_safe` reports it as failed until then. | As `rahat_app`: `SELECT set_config('app.role','officer',false), set_config('app.tenant_id','<t>',false), set_config('app.user_id','<officer>',false);` withdraw the consent, `SELECT count(*) FROM persons` gives 0; then `CREATE TEMP TABLE consents (person_id uuid, tenant_id uuid, status text, grantee_type text, grantee_id uuid, expires_at timestamptz); INSERT INTO consents VALUES ('<person>','<t>','active','tenant','<t>',NULL); SELECT count(*) FROM persons` gives 1. **Fix:** a migration with `ALTER FUNCTION app_can_read_person(uuid) SET search_path = public, pg_temp;` and the same in `migrations/rls.py`. Severity is low today: SQL running as `rahat_app` can already set `app.role` itself (DECISIONS 5), but the fix is one line and removes the gap if that ever changes. |
| 3 | Some lookups by id have no tenant filter in the application, so Row Level Security is their only tenant barrier: `cases/service._load` (every `/v1/cases/{case_id}` route) and `jobs/router.retry_job`. With RLS on, as deployed, the IDOR suite passes. | **Reported** (defence in depth; CONTRACTS asks for both layers). | Temporarily replace `credential.rls()` with `SYSTEM` in `app/core/deps.get_db` and run `pytest tests/security/test_idor.py`: the cases routes and `POST /v1/admin/jobs/{job_id}/retry` fail; routes with an application-level filter still pass. **Fix:** add `Model.tenant_id == principal.tenant_id` to those two queries. |
| 4 | `deploy/start.sh` defaults `FORWARDED_ALLOW_IPS` to `*`. With that, uvicorn 0.54 takes the **leftmost** `X-Forwarded-For` entry, which the client controls. Behind a proxy that appends to the header (many platform routers), a client can pick its own rate-limit bucket and the address in the logs. | **Reported** (deploy files belong to the lead). The live tunnel on this PC trusts only `127.0.0.1` and takes the rightmost untrusted entry, so it is not affected. | Run the image with the default, send `X-Forwarded-For: 198.51.100.1` through an appending proxy: the request is limited and logged as `198.51.100.1`. **Fix:** set `FORWARDED_ALLOW_IPS` to the proxy's address in each deploy recipe. |
| 5 | Unmatched `/v1/` paths (404, 405) ran no policy, so they were never rate limited (in production the SPA catch-all already covered unknown GET paths). | **Fixed** in `core/errors.py`. Regression: `tests/security/test_rate_limits.py::test_probing_for_endpoints_counts_against_the_network`. | Before the fix, with a limit of 3, a fourth `GET /v1/no-such-endpoint` still answered 404. |

## 3. Known gaps and residual risk

- **Rate limits live in one process.** They reset on restart and assume one API worker (DECISIONS 3). A flood from many networks is not stopped; a real deployment puts a CDN or WAF in front. People behind one NAT share one anonymous bucket (300 a minute); shared demo accounts share one user bucket (600 a minute).
- **The database context is chosen by the API process.** Row Level Security stops application bugs and IDOR, not an attacker who can run arbitrary SQL as `rahat_app`: such SQL can set `app.role` to `system` (DECISIONS 5). Finding 2 is a narrower form of the same limit.
- **Consent function search path** (finding 2) stays open until the lead's migration lands; two strict xfails track it.
- **Webhooks and their SSRF guard are not built** (A15, Phase 3). No code makes an outbound request to a user-supplied URL today.
- **API keys belong to the department, not the admin who made them.** A key keeps working after its creator leaves, until it is revoked or expires (at most a year). A key without personal-data scopes (`payments:read`: amounts, status and payment references, no names) is created by one admin alone.
- **Rotation grace.** During a named grace period (at most 24 hours) both the old and the new key work.
- **Metering is best effort.** If writing the usage counter fails, the call proceeds and the failure is logged: a missed count, never a blocked call.
- **Limits come before the role check.** A caller over its limit gets 429 even on a route it could not call anyway; this caps how fast refusals can fill the audit log.
- **`notifications` has a `person_id` but no consent policy in the database**; the API filters it (CONTRACTS, known gap).
- **`/metrics` is public.** It carries aggregate counters only, with route templates and status classes as labels.
- **What the matrix proves.** It proves that refused callers are refused and write nothing. It does not prove that an admitted caller gets exactly the right data; the module tests and the IDOR checks cover that for each route.
- **Sign-in** is a mock phone and a 4 to 6 digit PIN with lockout (DECISIONS 11); a real service would add a one-time code or device binding.
