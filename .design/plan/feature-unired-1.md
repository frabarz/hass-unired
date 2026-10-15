---
goal: Incremental implementation of Unired HA integration (device-bound auth, bill sensors, add/remove services)
version: 1.0
date_created: 2026-10-15
last_updated: 2026-10-15
owner: Unired HA Contributors
status: 'Planned'
tags: [feature, home-assistant, chile, unired, utility-bills, plan]
---

# Introduction

![Status: Planned](https://img.shields.io/badge/status-Planned-blue)

Incremental, executable plan to take `custom_components/unired/` from the current scaffold (manifest only) to a working V1: device-bound RUT+e-mail+OTP pairing (new and existing users), per-utility bill sensors, and in-HA add/remove of linked services. Each phase is independently buildable, testable, and committable. No code is written by this plan; each TASK names exact files, symbols, and done-criteria.

> API source of truth: `findings.md` §§1–7 (endpoints, error codes, payload shapes — all verified live 2026-10-15 unless marked ASSUMPTION). Sibling reference implementation: `../redregional` (flake layout, coordinator patterns, CI, docs structure).

## 1. Requirements & Constraints

- **REQ-001**: UI-only setup via `ConfigFlow`; single form collects RUT + e-mail + full name (name is only sent on the registration branch, mirroring the app's guest form).
- **REQ-002**: One config entry per Unired user (RUT+e-mail). Entry data holds auth (tokens, stable device fingerprint); never YAML. RUT is normalized (strip `.`/`-`, app behavior verified in `1809_STEPS.js`) before sending, displayed masked.
- **REQ-003**: Flow branches on live server codes: `loginWithDevice` success-with-tokens → create; `0603` → registration branch; `0630` → device-pairing branch; anything else → form error, no entry.
- **REQ-004**: Registration branch: `POST registration {rut,email}` → OTP form → `PATCH registration/{uid}/activation {codeVerification, device}` → `PATCH registration/{uid} {name, uuidTyc}` (`uuidTyc` from live `GET publicInfo/tyc → data.uuid`) → continue into device-pairing branch (fresh account has no known device).
- **REQ-005**: Device-pairing branch: `POST device {user, device}` → OTP form → `POST device/authorize {device, user, otp}` → tokens → create entry.
- **REQ-006**: OTP is 4 digits, e-mail delivered. There is NO resend button (server resend endpoints are dead: `registration/{uid}/code` → `0603`, `security/{uid}/otp` → `401` pre-login — verified live). Restarting the step's POST re-issues a code; the UI text must say so.
- **REQ-007**: Reauth flow (`0509`/`0605` at runtime, or user-initiated): `POST device` (same stored fingerprint) → OTP → `device/authorize` → replace token triple in entry data.
- **REQ-008**: One bill `sensor` per (account, instrument): state = total owed CLP (`Σ billList[].amount` for `amount > 0`; `0` when empty/all-zero = nothing prepared), `device_class=monetary`, `native_unit_of_measurement="CLP"`, `state_class=measurement`? NO — bills are point-in-time totals, not measurements; omit `state_class`. `unknown` while coordinator lacks data. `amount > 0` ⟺ "bill prepared" (no separate binary sensor in V1).
- **REQ-009**: Sensor attributes: `bills[]` (`amount`, `debt_type`, `due_date` from `FECVEN`, `contract` from `NUMCON`, `selected`), `bill_count`, `company`, `account_identifier`, `account_nickname`, `allows_credit`, `accept_zero_debt`, `presentation_rule[]`.
- **REQ-010**: Stable `unique_id`s (`{account_uuid}_{instrument_uuid}`); `DeviceInfo.identifiers={(DOMAIN, account_uuid)}`, manufacturer = company name, model = industry name, name = account nickname.
- **REQ-011**: Add-service (options flow): company picker from live `GET inscription/items` (manual `companyUuid` text fallback) → identifier (client number) + nickname form → `POST inscription/account` → reload entry. Remove-service: multi-select of known accounts → `POST account/delete {accounts:[...]}` → reload. Sensors follow server state (no local tracking set).
- **REQ-012**: All polling via one `DataUpdateCoordinator` per entry: `GET account` → per account `GET account/{uuid}/instruments` → per instrument `GET debt/…` (accept any 2xx; debt returns **201**). Default interval 6h, options range 1h–24h. Auth failures → `ConfigEntryAuthFailed`; rest → `UpdateFailed`, keep-last-known.
- **REQ-013**: Token refresh: when `expirationDate` passed or server answers `0700`/`0701`, `POST session/refreshToken {}` with `access_token`+`refresh_token` headers, then **persist the rotated triple** via `async_update_entry` (old tokens die — verified live).
- **REQ-014**: `POST session/logout` on entry removal (`async_remove_entry`).
- **REQ-015**: Logout/debt/account payloads as frozen dataclasses in `models.py`; parsers tolerate missing keys (`None`, never crash); sparse logging (no per-poll info, no tokens/PII at info).
- **REQ-016**: Async-only; `aiohttp` via `async_get_clientsession`; zero `requests` in runtime code; `asyncio.timeout(10)` per call.
- **REQ-017**: Fully typed, `ruff`-clean (line-length 88, `E,F,I,UP,B,ASYNC`, target `py313`), docstrings at module/class/public-function level only.
- **REQ-018**: Full literal text in `translations/en.json` + `translations/es.json`; no `strings.json` / `[%key%]` placeholders. Every server code mapped in REQ-026 gets a translated form error.
- **REQ-019**: `diagnostics.py` redacting tokens, e-mail, RUT, device ids, contract numbers, names/addresses; `quality_scale.yaml` targeting Silver (Bronze minimum).
- **REQ-020**: Tests mirror `../redregional` stack (`pytest` + `pytest-homeassistant-custom-component` + `respx`); fixtures are the §7 live payloads with PII replaced by valid-shaped fakes.
- **REQ-021**: Docs: `configuration.md` (pairing, add/remove services, options), `entities.md`, `dashboards.md` (amount card + "bill prepared" automation on `> 0`), `troubleshooting.md` (code table, no-resend, relay masks, rotation, re-pair); README doc links updated as pages land.
- **REQ-022**: Keep `manifest.json` (`domain`, `version`, `requirements`) in sync with `pkgs/unired-ha/package.nix` and `requirements.txt`; bump version per release.
- **SEC-001**: Tokens live only in config-entry data (HA `.storage`), never logs/diagnostics/attributes. OTPs are transient form values, never stored.
- **SEC-002**: Never guess OTPs (server locks codes after attempts — `0408`); single-shot verify per user submit.
- **SEC-003**: Device `uniqueId`/`deviceId` generated once per entry (`uuid4`), persisted, reused forever — the server binds the device identity; rotating it forces re-pairing.
- **CON-001**: Zero runtime `requirements` (hardcoded `API_BASE`; no CryptoJS reimplementation — see ALT-001).
- **CON-002**: Base URL, endpoint paths, fingerprint field list, error-code table centralized in `const.py`.
- **CON-003**: HA floor 2026.1 / Python ≥ 3.13 (`py313`-compatible; `ConfigEntry.runtime_data` pattern).
- **CON-004**: `594`-style constraints don't exist here; instead: max 3 sequential fan-out levels per poll, no per-bill requests, coordinator serializes refresh vs poll with a lock.
- **GUD-001**: Mirror `../redregional` file layout, CI, commit granularity (one phase = one commit), and AGENTS.md update discipline.
- **PAT-001**: `UniredClient` on injected session; `UniredCoordinator(DataUpdateCoordinator[UniredData])`; `CoordinatorEntity` sensors; `async_forward_entry_setups(["sensor"])`.
- **PAT-002**: Config-flow branching by server code (not by user choice): try login → `0603` register → `0630` pair → tokens. Registration converges into pairing.
- **PAT-003**: Options-flow mutations (link/unlink) end with entry reload; never patch sensor state locally.
- **OOS-001**: `session/secure/login/{uid}/authorize` path (contingency only — see TASK-010).
- **OOS-002**: Federated login (`loginWithFederatedUser`, Google/Apple JWT) — no JWT source in HA.
- **OOS-003**: OTP resend button (dead server-side).
- **OOS-004**: Payments/transactions endpoints (`bancoestado/fintoc/webpay/alps`, vouchers, tickets, ratings).
- **OOS-005**: Account rename (`PATCH account/{uuid}`) — trivial later, excluded from V1 scope.
- **OOS-006**: Biometrics, push, multi-user entry sharing.

## 2. Implementation Steps

### Implementation Phase 1

- GOAL-001: Lock the API contract in a typed async client with redacted live fixtures; debt rule green, zero entities.

| Task | Description | Completed | Date |
| ---- | ----------- | --------- | ---- |
| TASK-001 | Copy redacted live payloads to `tests/fixtures/`: `tyc.json` (`{tyc:"…",version,uuid}`), `accounts.json` (3 accounts, fake uuids/identifiers), `instruments_{internet,agua,luz}.json` (`{instrumentList:[…]}`), `debt_{empty,zero,owed}.json` (201 shapes: `billList:[]`, `amount:0`, `amount:10600` + `queryAttribute`/`presentationRule`), `tokens.json`, `device_register.json` (`{deviceUuid,userIdentifier,cooldown}`), `error_{0603,0630,0700,0509}.json` (+ `inscription_items.json` trimmed catalog from TASK-007) | ✅ | 2026-10-16 |
| TASK-002 | Create `custom_components/unired/const.py`: `API_BASE`, endpoint path constants, `DEVICE_FIELDS` (16 names from findings §2), static fingerprint values (`APP_VERSION="1.18.2"`, `BUILD_NUMBER="410"`, `BUNDLE_ID="cl.unired.app"`), error-code map (`CODE_*`), `CONF_RUT/CONF_EMAIL/CONF_NAME/CONF_DEVICE/CONF_TOKENS/CONF_USER_ID/CONF_DEVICE_UUID`, `CONF_SCAN_INTERVAL_S` + `DEFAULT_SCAN_INTERVAL_S=21600/MIN=3600/MAX=86400`, `RUT_STRIP_RE` + `normalize_rut()` (strip `./-`, uppercase) | ✅ | 2026-10-16 |
| TASK-003 | Create `custom_components/unired/exceptions.py`: `UniredError`, `UniredAuthError(code)`, `UniredNotFoundError` (0603), `UniredDeviceError` (0630/0907), `UniredConnectionError`, `UniredRateLimitError` | ✅ | 2026-10-16 |
| TASK-004 | Create `custom_components/unired/models.py`: frozen `Tokens(access, refresh, expires_at)`, `DeviceFingerprint` (+ `generate()` classmethod: uuid4 uniqueId/deviceId, static rest), `Account(uuid, nickname, identifier, company_name, industry)`, `Instrument(uuid, name, account_uuid)`, `Bill(amount, debt_type, due_date, contract, selected, raw_attrs)`, `DebtSummary(owed_total, has_debt, bills, allows_credit, accept_zero_debt, presentation_rule)` + `LinkableCompany`/`linkable_companies_from_dict` (catalog flatten) | ✅ | 2026-10-16 |
| TASK-005 | Create `custom_components/unired/api.py` class `UniredClient(session)`: `async_get_tyc`, `async_preregister(rut, email) -> str userIdentifier`, `async_activate_registration(uid, code, device)`, `async_complete_registration(uid, name, uuid_tyc)`, `async_login(rut, email, device) -> Tokens | str userIdentifier-or-device-code`, `async_register_device(email, rut, device) -> (deviceUuid, userIdentifier, cooldown)`, `async_authorize_device(device, email, rut, otp) -> Tokens`, `async_refresh(tokens) -> Tokens`, `async_logout(tokens)`, `async_get_accounts/instruments/debt` (debt accepts any 2xx), `async_inscription_items`, `async_lookup_instrument(code)`, `async_link_account(body)`, `async_delete_accounts(uuids)`; `asyncio.timeout(10)` each; map HTTP/code → exceptions from TASK-003; never log bodies/tokens (login raises 0603/0630 via exceptions; `login_authorize` contingency included) | ✅ | 2026-10-16 |
| TASK-006 | Add `tests/test_api.py` (respx): preregister 201, activation 200, login 0630/0603 branches, device register 201, authorize 200 triple, refresh rotation (old token then rejected), debt **201** accepted, debt rule (empty→0, zero→0, 10600→10600), error-code mapping incl. 0700/0509 (fake aiohttp session — respx is httpx-only; + `test_models.py`: RUT/tokens/fingerprint/debt rule; 30 passed) | ✅ | 2026-10-16 |
| TASK-007 | Live-probe (read-only, no creds): `GET inscription/items` and `GET instrument?code=` with/without `access_token` (tokens in local probe only, never committed) `GET inscription/items` → **200 unauthenticated**, `data.itemsTypeList[{uuid,name,itemList[{uuid,name,companyList[{uuid,name,flags}]}]}]` (2 types/22 items/126 companies) → typed `LinkableCompany`; `GET instrument?code=` → **401 without token** (auth locked, shape deferred to TASK-020). Findings §7 updated | ✅ | 2026-10-16 |

### Implementation Phase 2

- GOAL-002: Auth-state orchestration in the client (pairing decision tree) with rotation-safe refresh; still no HA glue.

| Task | Description | Completed | Date |
| ---- | ----------- | --------- | ---- |
| TASK-008 | Add `custom_components/unired/auth.py`: `AuthResult` union (`Authenticated(tokens)`, `NeedRegistration`, `NeedDevicePairing(userIdentifier?)`, `Failed(code,message)`); `async def ensure_tokens(client, rut, email, device, otp_provider) -> AuthResult` implementing PAT-002 (login → 0603 register+activate+complete → device → authorize), single OTP attempt per code, refresh-on-0700 with one retry (pairing tree in `ensure_tokens` + step helpers `start_login`/`submit_registration_otp`/`submit_device_otp` reused by Phase 3; `refresh_if_needed` covers expiry/forced rotation with persistence sink; 0700-retry lands in the Phase 4 coordinator) | ✅ | 2026-10-16 |
| TASK-009 | Add `tests/test_auth.py`: full new-user path, existing-user-new-device path, known-device direct tokens, 0603-mid-flow abort, refresh rotation persistence callback asserted (scripted client stub; 11 tests: known-device, 0603→register, 0630→pair, bad-OTP single attempt, transport abort, refresh skip/rotate) | ✅ | 2026-10-16 |
| TASK-010 | Contingency probe (only if live login ever returns `userIdentifier` instead of tokens/0630): document `session/secure/login/{uid}/authorize {otp}` usage and wire as fallback branch; default stays OOS-001 (condition never observed live 2026-10-15/16; `api.login_authorize` exists + `auth` documents the wiring point) | ✅ | 2026-10-16 |
| TASK-011 | Resolve ASSUMPTION-001/002 (activation + complete response shapes) against the next live pairing; update fixtures + client, never guess | (open 2026-10-16: no new live pairing performed in Phase 2; pass-through dicts hold) | |

### Implementation Phase 3

- GOAL-003: Config flow (user/OTP/reauth), options skeleton, translations; entry creatable by hand-run test, no entities yet.

| Task | Description | Completed | Date |
| ---- | ----------- | --------- | ---- |
| TASK-012 | Create `custom_components/unired/config_flow.py`: `UniredConfigFlow` steps `user` (RUT+email+name) → `otp` (4-digit + context which POST to re-issue on restart, REQ-006 text) branching per REQ-003/004/005 via `auth.py`; `async_step_reauth` (REQ-007); unique_id = normalized RUT+email, abort-if-exists; create entry with `data={CONF_*}` per REQ-002/SEC-003 (12 flow tests: direct/pairing/registration paths, bad+short OTP, duplicate abort, reauth replace+retry). Fixes found while testing: `async_set_unique_id` must be awaited (else unique_id=None, no abort); `reauth_confirm` needs its own step handler | ✅ | 2026-10-16 |
| TASK-013 | Create `translations/en.json` + `es.json` with full literal text for all steps, OTP explanations (no-resend notice), and every `errors.*` key for REQ-026 codes | ✅ | 2026-10-16 |
| TASK-014 | Add `tests/test_config_flow.py` (phcc): existing-user device-pairing happy path, new-user registration path, 0603→register convergence, wrong-OTP error (single attempt, no retry loop), reauth replaces triple, abort on duplicate (mocked auth layer, phcc flow driver) | ✅ | 2026-10-16 |
| TASK-015 | Add `tests/test_translations.py`: en/es key parity incl. all error keys; mirror redregional pattern | ✅ | 2026-10-16 |

### Implementation Phase 4

- GOAL-004: Coordinator, entry lifecycle, bill sensors, add/remove-service options, diagnostics; first end-to-end green run. Plus: mandatory T&C checkbox on the user step (requested mid-phase; `terms_not_accepted` error, en+es).

| Task | Description | Completed | Date |
| ---- | ----------- | --------- | ---- |
| TASK-016 | Create `custom_components/unired/coordinator.py`: `UniredCoordinator(DataUpdateCoordinator[dict[tuple[str,str], DebtSummary]])`; `_async_update_data` does accounts→instruments→debts, pre-checks `expires_at` (refresh first), maps `UniredAuthError`→`ConfigEntryAuthFailed`, rest→`UpdateFailed`, keeps last data; exposes `accounts` meta + `async_add_account(company_uuid, identifier, nickname)` / `async_remove_accounts(uuids)` (link/unlink + `async_reload`)  (per-instrument fault isolation added: missing debt skips, auth/ratelimit still abort; `test_coordinator.py` 7 tests) | ✅ | 2026-10-16 |
| TASK-017 | Create `custom_components/unired/__init__.py`: `async_setup_entry` (build client+fingerprint from entry data, coordinator `async_config_entry_first_refresh`, `runtime_data`, forward `sensor`), `async_unload_entry`, `async_remove_entry` (best-effort `logout`), `async_migrate_entry` stub (version 1)  (entry update-listener refreshes scan interval; `logout` on remove; no YAML `async_setup`) | ✅ | 2026-10-16 |
| TASK-018 | Create `custom_components/unired/sensor.py`: `UniredBillSensor(CoordinatorEntity)` per REQ-008/009/010 (`unique_id=f"{auuid}_{iuuid}"`, monetary CLP, `unknown` without data) + per-instrument owed computation shared with coordinator (`debt_summary`)  (`entity.py` base mirroring redregional; `test_sensor.py` full-stack: 10600/0/0 + unknown) | ✅ | 2026-10-16 |
| TASK-019 | Extend `config_flow.py` with `UniredOptionsFlow`: `add_service` (company select from `inscription_items` w/ manual uuid fallback → identifier+nickname → link → reload), `remove_service` (multi-select → delete → reload), `scan_interval` (3600–86400); add `tests/test_options_flow.py` covering link, unlink, reload-called, server-error surfacing  (implemented as separate `options_flow.py` mirroring redregional, not inside config_flow; menu + manual fallback + settings; `test_options_flow.py` 6 tests) | ✅ | 2026-10-16 |
| TASK-020 | Lock inscription mutation shapes first: inspect bundle call sites (`module_2293` link body, `module_2523` delete body `{accounts:[…]}`) and confirm with one live link/unlink round on a disposable identifier only with explicit user approval; record exact bodies in findings §7  (STATIC ONLY: link `{nickname, identifier: RUT-digits, companyUuid}`, unlink `{accounts: [{accountUuid}]}` — findings §7; live round-trip still needs user approval) | ✅ | 2026-10-16 |
| TASK-021 | Create `custom_components/unired/diagnostics.py` redacting per REQ-019 (assert redaction in `tests/test_diagnostics.py` with a fixture containing tokens/e-mail/RUT/contract/address)  (`TO_REDACT` covers tokens/device ids/NOMCON/DGLOSA/contract/identifiers/rut/email; entry data never dumped) | ✅ | 2026-10-16 |
| TASK-022 | Add `tests/test_coordinator.py` (accounts→debts fan-out incl. 201, partial failure keeps rest, `ConfigEntryAuthFailed` on 0509) and `tests/test_sensor.py` (10600 state + attrs, zero→0, empty→0, unknown without data, unique_ids)  (plus `test_diagnostics.py`; 71 passed total) | ✅ | 2026-10-16 |
| TASK-023 | Add `quality_scale.yaml` (Silver target), `icons.json` + `brand/` mirroring `../redregional` hassfest set; run local hassfest equivalent via CI later  (placeholder brand icons generated stdlib-only; real artwork still wanted) | ✅ | 2026-10-16 |

### Implementation Phase 5

- GOAL-005: Docs, release hygiene, Nix/CI parity; repo shippable.

| Task | Description | Completed | Date |
| ---- | ----------- | --------- | ---- |
| TASK-024 | Write `docs/configuration.md` (pairing walkthrough incl. no-resend + relay-mask warning, options reference), `docs/entities.md` (sensor + attribute table), `docs/dashboards.md` (amount card, `>0` "prepared" automation example), `docs/troubleshooting.md` (code table 0603/0630/0907/040x/042x/0509/0605/0700/0801, rotation, re-pair) | ✅ | 2026-10-16 |
| TASK-025 | Update `README.md` doc index + pairing summary; update `AGENTS.md` (scaffold→implementation status, fixture/test commands); bump `manifest.json` version if behavior changed since 0.1.0 and sync `package.nix` (test_manifest guards) (0.1.0 kept: first release; README doc index + AGENTS implementation status updated; `quality_scale.yaml` documentation → done; MIT `LICENSE` added) | ✅ | 2026-10-16 |
| TASK-026 | Full gate inside `nix develop`: `ruff check . && ruff format --check .`, `pytest tests/ -q` (71 passed), `nix build .#unired-ha`, `nix flake check` (all green 2026-10-16); push branch, confirm GH Actions (test matrix + hassfest + HACS) green (CI runs on push; local parity done) | ✅ | 2026-10-16 |

## 3. Alternatives

- **ALT-001**: Reimplement CryptoJS config decryption at runtime (needs AES dep → manifest `requirements` + nix packaging, new failure modes). Rejected: base URL is stable across app versions (verified identical 1.7.3→1.18.2); hardcode + document.
- **ALT-002**: Separate config entries per utility account. Rejected: auth is per-user device-bound; one entry + N sensors matches server model and avoids N OTP pairings.
- **ALT-003**: Local "tracked set" in options instead of server-side link/unlink. Rejected: app links server-side (`inscription/account`); local-only hiding would desync from the app and confuse.
- **ALT-004**: Binary sensor "bill prepared" + monetary sensor. Rejected for V1: `amount > 0` on the monetary sensor already encodes it; automations trigger on numeric threshold. Revisit if UX demands.
- **ALT-005**: Username/password login. Does not exist in 1.18.2 (device+OTP only); old `session/login` is gone.

## 4. Dependencies

- **DEP-001**: `../redregional` patterns (devShell, CI, coordinator/error idioms) — read-only reference, no code copy of domain logic.
- **DEP-002**: HA ≥ 2026.1 runtime (nixpkgs unstable in flake; CI matrix pins 2026.1.1/py3.13 + 2026.9.0/py3.14 + local 2026.10.x).
- **DEP-003**: Live Unired backend for TASK-007/011/020 + final acceptance (user-operated OTPs; never automated guessing).
- **DEP-004**: `pytest-homeassistant-custom-component` version lockstep with HA under test (see `requirements_test.txt` header).

## 5. Files

- **FILE-001**: `custom_components/unired/const.py` — URLs, paths, codes, fingerprint, config keys, intervals (new)
- **FILE-002**: `custom_components/unired/exceptions.py` — error taxonomy (new)
- **FILE-003**: `custom_components/unired/models.py` — frozen dataclasses (new)
- **FILE-004**: `custom_components/unired/api.py` — `UniredClient` (new)
- **FILE-005**: `custom_components/unired/auth.py` — pairing decision tree (new)
- **FILE-006**: `custom_components/unired/coordinator.py` — poll fan-out + link/unlink (new)
- **FILE-007**: `custom_components/unired/__init__.py` — lifecycle (new)
- **FILE-008**: `custom_components/unired/sensor.py` — bill sensors (new)
- **FILE-009**: `custom_components/unired/config_flow.py` — user/OTP/reauth/options (new)
- **FILE-010**: `custom_components/unired/translations/en.json`, `es.json` (new)
- **FILE-011**: `custom_components/unired/diagnostics.py`, `quality_scale.yaml`, `icons.json`, `brand/` (new)
- **FILE-012**: `tests/fixtures/*.json`, `tests/test_{api,auth,config_flow,options_flow,coordinator,sensor,translations,diagnostics}.py` (new)
- **FILE-013**: `docs/{configuration,entities,dashboards,troubleshooting}.md`, `README.md`, `AGENTS.md`, `findings.md` §7 (docs/live updates)
- **FILE-014**: `custom_components/unired/manifest.json`, `pkgs/unired-ha/package.nix` (version sync only)

## 6. Testing

- **TEST-001**: `test_manifest.py` (exists) stays green — packaging sync guard.
- **TEST-002**: `test_api.py` — fake-session mocks of every endpoint incl. debt-201, rotation, code mapping (TASK-006).
- **TEST-003**: `test_auth.py` — three pairing paths + refresh persistence (TASK-009).
- **TEST-004**: `test_config_flow.py` — branching, OTP single-shot, reauth, duplicates (TASK-014).
- **TEST-005**: `test_options_flow.py` — link/unlink/reload, error surfacing (TASK-019).
- **TEST-006**: `test_coordinator.py` + `test_sensor.py` — fan-out, 201, partial failure, states/attrs/unique_ids (TASK-022).
- **TEST-007**: `test_translations.py` + `test_diagnostics.py` — parity + redaction (TASK-015/021).
- **TEST-008**: Live acceptance (manual, user-driven OTPs): pair → sensors show real bills → unlink/link round-trip on a disposable identifier → refresh survival past expiry → `0509`-path documented. Record results in findings §7.

## 7. Risks & Assumptions

- **RISK-001**: Backend drift (endpoint/code/shape changes without notice) — mitigated by CON-002 centralization + fixtures exposing drift as test failures.
- **RISK-002**: `0603`-on-resend class surprises: any new dead endpoint discovered live → document, route around (repo precedent exists).
- **RISK-003**: HA `customComponents` API drift in nixpkgs unstable — pinned by flake.lock; CI builds the package.
- **RISK-004**: OTP e-mail deliverability (relay masks) — troubleshooting doc + in-flow warning text (observed live).
- **ASSUMPTION-001**: `PATCH registration/{uid}/activation` success shape (unverified — no live activation performed); TASK-011 resolves before client freeze.
- **ASSUMPTION-002**: `PATCH registration/{uid} {name,uuidTyc}` success shape + whether login is still required after (same resolution path).
- **ASSUMPTION-003**: `loginWithDevice` response for a *known* device (tokens directly — inferred, unverified); client branches on payload, TASK-010 covers the alternate shape.
- **ASSUMPTION-004**: `0907 DEVICE_ALREADY_REGISTERED` semantics on `POST device` (plan: surface as "already paired, use login" error; confirm live if ever hit).
- **ASSUMPTION-005**: Inscription shapes (`inscription/items` entries, `instrument?code=` result, link body — `module_2292` suggests `{nickname, rut(digits), companyUuid}`; delete body `{accounts:[…]}`); TASK-007/020 resolve, mutations only with approval.
- **ASSUMPTION-006**: Re-POST (`device`/`registration`) re-issues the code with latest-wins (observed: new uid per registration; device re-POST behavior unverified — flow text tells users to use the newest code).

## 8. Related Specifications / Further Reading

- `findings.md` §§1–7 — Unired API research (decryption, auth, endpoints, live verification 2026-10-15)
- `../redregional/.design/plan/feature-red-regional-1.md` — sibling plan conventions followed here
- `../redregional/.design/spec/spec-design-red-regional-ha.md` — coordinator/translation/diag patterns reference
- [Home Assistant Integration Quality Scale](https://www.home-assistant.io/docs/quality_scale/)
- [Config flow + reauth + options](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/)
- [DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data/)
