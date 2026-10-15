# Unired APK Reverse-Engineering Findings

## Approach

1. Inspected the APK (`cl.unired.app_v240.apk`) with `jadx` to identify app type and entry points.
2. Detected a React Native app with a Hermes (`index.android.bundle`) bytecode bundle.
3. Decompiled the Hermes bundle to JavaScript with `hbc-decompiler`.
4. Recovered API constants from decompiled code and from APK string resources/`BuildConfig`.
5. Traced call sites for login, account listing, instrument listing, and debt queries.

## Identity

- Package: `cl.unired.app`
- App: React Native, Hermes bytecode
- Base URL (`BuildConfig.API_URL` / `res/values/strings.xml`):
  `https://app1-prod-01.unired.cl/unired-api/v1/`

## Authentication and Account Lifecycle

- A Unired account is required by the app API: `GET account`, `GET account/{uuid}/instruments`, and `GET debt/account/{uuid}/instrument/{uuid}` return `401 No esta autorizado para acceder a este servicio` without `access_token`. Only lookup-like unauthenticated endpoints (e.g. `GET inscription/items`, `GET publicInfo/tyc`) appear to work without login.
- Registration:
  - `POST registration` with `{ "rut": "<RUT>", "email": "<email>" }`.
  - `PATCH registration/{userIdentifier}` with `{ "codeVerification": "<code>" }` to verify.
  - `PATCH registration/{userIdentifier}` with `{ "name": "<name>", "uuidTyc": "<tyc>" }` to complete.
  - `POST registration/{identifier}/code` to resend the verification code.
- Login endpoint: `POST session/login`
  - Request body: `{ "rut": "<RUT>", "email": "<email>", "name": null }`.
- Protected requests use header `access_token: <accessToken>` (the app's interceptor adds this when available), plus `Content-Type: application/json` and `Accept: application/json`.
- Token refresh:
  - `POST session/refreshToken` with empty body; request headers include `access_token` and `refresh_token`.
- Logout:
  - `POST session/logout`.

## Key Endpoints

- Accounts:
  - `GET account` returns `{ accounts: [{ uuid, ... }] }`.
- Instruments for an account:
  - `GET account/{accountUuid}/instruments`
- Debts (bill amounts/status) for an instrument:
  - `GET debt/account/{accountUuid}/instrument/{instrumentUuid}`

## Suggested Polling Flow for a Sensor

1. `POST session/login` with user credentials (RUT + email) to obtain `accessToken`/`refreshToken`.
2. `GET account` to enumerate account UUIDs.
3. For each account, `GET account/{uuid}/instruments`.
4. For each instrument, `GET debt/account/{accountUuid}/instrument/{instrumentUuid}` to retrieve the current debt/bill amount and preparation status.

## Notes / Limits

- The APK is not executed; findings are static observations of decompiled code.
- Endpoint field names and response shapes are inferred from call sites; live verification is needed once valid credentials are available.
- No secrets or credentials were embedded in the decompiled artifacts beyond the public API base URL.

---

# Unired 1.18.2 (versionCode 410) Findings — `unired_1.18/base.apk`

Package identity confirmed via REA `decode-android-resources`
(Evidence `ev_f5132ec25cc51517431fccb3d2a5e63d4e01df7dcbc0206d6139cb470035d814`,
provider apktool 3.0.3, target sha256
`6d54214d…fc4a2af`): package `cl.unired.app`, version `1.18.2` (410),
`com.unired.MainApplication` / `com.unired.MainActivity`, minSdk 29, targetSdk 36.
Old APK for comparison: `cl.unired.app_v240.apk` = 1.7.3 (240).
Both ship a React Native Hermes bundle (`assets/index.android.bundle`):
old = HBC v94, new = HBC v96. Decompiled with `hermes-decomp`
(`cargo install --git https://github.com/SymbioticSec/hermes-decomp hbc-decomp-cli`;
supports HBC 40–99; `dump --kind strings`, `xref`, `decompile`, `extract`).
REA's JADX provider was unavailable (no `REA_JADX_MCP_JAR` on this NixOS host),
so Java-side facts below are ordinary-tool observations via `jadx`, not REA Evidence.

## 1. Base URL: same host, now encrypted at rest

- `BuildConfig` (`jadx --single-class com.unired.BuildConfig`) and
  `res/values/strings.xml` no longer contain the URL in plaintext:
  `API_URL = "U2FsdGVkX19Z62fbE+cFJ4CvB4xw2ndJVO6BVHNKUZabhdiW6oIVHQBRYH4QXm4WX4qYZQ7ae2NLRTEKgBktjQ=="`
  (same for `SENTRY_DNS`, `CLARITY_PROJECT_ID`; plaintext survivors:
  `NAME=Unired`, `APP_ENV=production`).
  The `U2FsdGVkX1…` prefix is base64 for `Salted__`: CryptoJS/OpenSSL-format AES.
- Decryption lives in bundle module 1496 (`F16856`, `getEnvVar` at `F16857`,
  consumed by `CONSTANTS` module 1495/`F16855` for `API_URL`, `SENTRY_DNS`,
  `CLARITY_PROJECT_ID`; `REF_CODE`/`NAME`/`APP_ENV` pass through in plaintext):
  - `closure_1` = react-native-config (`RNCConfigModule`, i.e. `BuildConfig` values),
  - `closure_0` = CryptoJS (`./aes`, `aes-256-cbc`, `enc-utf8` pulled in by module 1497),
  - key = `Q3 + reverse(Q1) + Q4 + Q2` where `Q1..Q4` are the quarters of
    `BuildConfig.REF_CODE` (`n = floor(len/4)`), i.e.
    `REF_CODE[2n:3n] + reverse(REF_CODE[0:n]) + REF_CODE[3n:] + REF_CODE[n:2n]`,
  - `CryptoJS.AES.decrypt(value, key).toString(CryptoJS.enc.Utf8)`
    (standard MD5-based `EVP_BytesToKey`, no PBKDF2).
- `REF_CODE` (64 hex chars, `BuildConfig`):
  `b1e2f3a4c5d6e7f8091a2b3c4d5e6f70a1b2c3d4e5f60718293a4b5c6d7e8f90`
  → key `a1b2c3d4e5f607188f7e6d5c4a3f2e1b293a4b5c6d7e8f90091a2b3c4d5e6f70`.
- Decrypted and verified locally (Python `hashlib` + `pycryptodome`, replicating
  `EVP_BytesToKey`):
  - `API_URL` = `https://app1-prod-01.unired.cl/unired-api/v1/` (UNCHANGED from 1.7.3)
  - `SENTRY_DNS` = `https://bafa18eec7255569cb0bf87e6e8c059f@o4506463368118272.ingest.us.sentry.io/4506463385616384`
  - `CLARITY_PROJECT_ID` = `no8o9clw8s`
- (Separate, unrelated crypto: bundle function `F5728 decrypt` does
  Node-style `aes-256-cbc` with SHA-256 of the hardcoded phrase
  `?D!1B&A0947R{@Z8_DeKPl^WY}Lji8o#` on `iv:ciphertext` payloads — looks like
  secure-storage payload decryption, not transport config.)

## 2. Authentication: old simple login replaced by device-bound OTP flow

Old: `POST session/login` with `{ rut, email, name: null }`.
New (module 1564 `postLogout`, module 2201 `ERRORS_VALIDATE_SECURE_CODE`,
module 1567 federated): no `session/login` string remains in the bundle.

1. `POST session/secure/loginWithDevice` with
   `{ user: { email, rut }, device: getDeviceInfo() }`
   (`secureLogin`, module 1564). `getDeviceInfo()` (module 675) sends the
   `react-native-device-info` inventory: `deviceId`, `deviceType`, `deviceName`,
   `installerPackageName`, `macAddress`, `manufacturer`, `readableVersion`,
   `systemName`, `systemVersion`, `uniqueId`, `version`, `emulator`,
   `supportedAbis`, `buildNumber`, `carrier`, `buildId`.
   Response yields a `userIdentifier` (kept in the redux user slice) and triggers
   an email OTP.
2. `POST session/secure/login/{userIdentifier}/authorize` with `{ otp }`
   (`mutationFnValidateCode`, module 2201).
   Resend: `POST security/{userIdentifier}/otp` with
   `{ reasonType: "LOGIN_VALIDATION" }` (device-flow variant uses
   `reasonType: "DEVICE_VALIDATION"`; relative `device/authorize` also exists,
   module 2202).
3. Success response `data` = `{ accessToken, refreshToken, expirationDate }`
   (module 1752), persisted via `saveSecureTokens` (keychain) and redux `setSession`.
- Federated alternative: `POST session/secure/loginWithFederatedUser` with
  `{ jwt, device }` (module 1567, Google/Apple); registration-side
  `POST registration/federated`, `POST device` (`registerDevice`, same user+device body).
- Registration (unchanged shape): `POST registration`, `PATCH registration/{userIdentifier}`
  (`{ name, uuidTyc }`), `DELETE /registration` (module 2543/1564).

Implication for the sensor: first pairing on a new "device" requires solving the
email OTP once (out-of-band read of the inbox). Afterwards the refresh flow below
keeps the session alive without captchas or OTPs — until the server forces
re-login (see error codes).

## 3. Transport: axios instance, headers, refresh, error codes (module 1444 `URL_BASE`)

- `axios.create({ baseURL: API_URL, headers: { Content-Type: application/json, Accept: application/json } })`.
- Request interceptor: loads `{ accessToken, expirationDate }` from secure store;
  if expired (`isTokenExpired`, UTC compare), refreshes first; then sets header
  `access_token: <accessToken>`.
- `POST session/refreshToken` with `{}` body and headers
  `{ access_token, refresh_token }` → new `{ accessToken, refreshToken, expirationDate }`
  (`renewToken`; on failure the app shows "inicia sesión nuevamente" and logs out).
- Response interceptor unwraps `data.data`; error `code` routing:
  `0700`/`0701` → silent token refresh + retry; `0801` → external-error screen;
  `0509` → "sesión desde un nuevo dispositivo" logout; `0605` → logout.
  (`0604`/`0407`/`0408`/`0500` = OTP errors; `0427`/`0428` = debt-load errors.)

## 4. Sensor polling endpoints (unchanged paths, confirmed in 1.18.2)

- `GET account` → `response.data.data.accounts[]`, each with `uuid`
  (+ `instrumentList`, `company`; module 1566 `accountsKeys`).
- `GET account/{accountUuid}/instruments` (`getAccountInstrumentInfo`, module 1443).
- `GET debt/account/{accountUuid}/instrument/{instrumentUuid}` (`getInstrumentDebt`,
  module 1443) → `response.data.data` =
  `{ billList: [{ amount, groupDescription, queryAttribute: [{ code, value }], … }],
     presentationRule: [{ code }], acceptZeroDebt ("S"/"N"), allowsCredit ("S"/"N") }`.
  App logic (`useFindInstrument`): `billListDebit` = bills with `amount > 0`
  (what is owed / "prepared"), `billListPaid` = `amount === 0`; known
  `presentationRule` codes: `MTKPO PAGORD AUTODE MTKPU PAGDES MTKPT` and combos.
- Other live endpoints seen (not needed for the sensor but confirming the same
  base URL + auth): `GET inscription/items`, `POST inscription/account`,
  `GET instrument?code=`, `GET transaction?month=&year=`, payment gateways
  (`bancoestado|fintoc|webpay|alps /transaction[/authorize|/status]`),
  `POST support/ticket*`, `POST account/{uuid}/instrument/{iUuid}/payment/validation`.

## 5. Suggested polling flow for the Home Assistant sensor (1.18.2)

1. One-time pairing: `POST session/secure/loginWithDevice` with RUT + email +
   a stable spoofed `device` object (copy the field list from §2; keep
   `uniqueId`/`deviceId` constant so the server sees one device), read the email
   OTP, `POST session/secure/login/{userIdentifier}/authorize` with `{ otp }`,
   store `{ accessToken, refreshToken, expirationDate }` (e.g. HA `.storage`).
2. Each poll: if `expirationDate` passed (or on `0700`/`0701`),
   `POST session/refreshToken` (empty JSON body, `access_token` + `refresh_token`
   headers) and persist the new triple.
3. `GET account` → for each `uuid`: `GET account/{uuid}/instruments` →
   for each instrument: `GET debt/account/{aUuid}/instrument/{iUuid}`.
4. Sensor value = sum of `billList` entries with `amount > 0`; "prepared" state =
   `billListDebit` non-empty. Extra attributes: per-bill `groupDescription`,
   `presentationRule` codes, `acceptZeroDebt`, `allowsCredit`.
5. On `0509`/`0605`: session dead → re-pair from step 1 (new OTP).

## 6. Notes / Limits (1.18.2 pass)

- REA CLI (`npx -y rea-agents@latest`) works on NixOS via `nix-shell -p nodejs apktool`
  with `REA_APKTOOL_COMMAND` set (see `shell.nix`); `decode-android-resources`
  Evidence is cited above. The REA Android/JADX provider family needs a
  caller-supplied `jadx-headless-mcp` JAR + supported distro, so Java findings
  here come from plain `jadx` 1.5.6 instead.
- Hermes decompile is lossy (register names gone, some closures unresolved), but
  every endpoint/method/body above was read from decompiled call sites, and the
  AES key schedule + all three ciphertexts were re-verified by independent
  decryption — API base URL byte-matches the 1.7.3 value.
- Live verification (OTP pairing → tokens → `debt` payload for a real account)
  still pending; response shapes in §4 are inferred from `useFindInstrument`
  and `accountsKeys` call sites.

## 7. Live verification (2026-10-15, real account, all steps executed)

- `GET publicInfo/tyc` → 200, no captcha. ✅
- `POST session/secure/loginWithDevice {user:{email,rut}, device}` for an
  unregistered RUT+email → `404/0603` (`UNREGISTERED_USER`; tried RUT with and
  without dash — app strips `./-`, confirmed in `1809_STEPS.js`/`module_1357`).
- `POST registration {rut:"172143520", email}` → `201 + {userIdentifier}` (×2).
  No OTP ever arrived at mask `6blmszu1r@mozmail.com` (likely dead/disabled
  relay mask — server still 201s); `POST registration/{uid}/code` resend → always
  `404/0603`, even seconds fresh (endpoint dead server-side; app usually skips it
  via its resume guard); `POST security/{uid}/otp` → `401/0700` (needs auth).
  Never guess OTPs — attempt limits/blocking (`0408`).
- In-app registration with a live mask works (OTP instant) — request bytes equal
  to ours, so the dead mask, not the format, was the blocker.
- `loginWithDevice` for the registered user from an unknown device →
  `400/0630` (`UNREGISTERED_DEVICE`, "Dispositivo no registrado").
- `POST device {user, device}` → `201 + {deviceUuid, userIdentifier, cooldown:"60"}`
  and OTP email arrives immediately.
- `POST device/authorize {device, user:{email,rut}, otp}` → `200 + {accessToken,
  refreshToken, expirationDate, name}` (tokens ~base64, expiry ~24h).
- `GET account` (header `access_token`) → 200, `data.accounts[]`:
  `{nickname, identifier, uuid, company:{name, imageIcon, industryCode, industryName,
  dynamicCreditInfo}}`. Real account: 3 accounts (Mundo Pacífico/CABLE,
  Essbio/AGUA, CGE S.A./LUZ).
- `GET account/{uuid}/instruments` → 200, `data.instrumentList[]`:
  `{instrumentUuid, name, company, account:{identifier, nickname}}` (1 each).
- `GET debt/account/{aUuid}/instrument/{iUuid}` → **201** (not 200 — accept any 2xx),
  `data = {instrumentUid, allowsCredit, acceptZeroDebt, billList, presentationRule}`.
  Real payloads: Internet `billList: []` (no debt); Agua one bill `amount: 0`
  (paid); Luz one bill `amount: 10600` (`debtType: "Deuda Total"`, plus
  `queryAttribute` detail: name, address, NUMCON, MONTO, FECVEN…).
  Sensor rule confirmed: owed = Σ `billList[].amount` where `amount > 0`;
  empty/`0` = nothing prepared/owed.
- `POST session/refreshToken` (`{}`, headers `access_token`+`refresh_token`) →
  200 + fresh `{accessToken, refreshToken, expirationDate, name}`; tokens ROTATE
  (old access token invalid afterwards — persist the new triple every refresh).
- `GET inscription/items` needs **no auth** (200): `data.itemsTypeList[]` →
  `itemList[]` → `companyList[]` (`uuid`, `name`, `imageIcon`,
  `imageIdentifier`, `favorite`, `descriptionItem`, `multipleIdentifier`,
  `allowsBillScan`); live catalog = 2 types / 22 items / **126 companies**.
  Powers the add-service company picker.
- `GET instrument?code=` (and bare `instrument`) → `401/0700` without
  `access_token` (auth required; response shape still unverified live).
- Inscription mutation bodies (static bundle evidence, `module_2293/2330/2523`;
  no live mutation performed): link is `POST inscription/account`
  `{nickname, identifier: <RUT digits, ./- stripped>, companyUuid}` — the
  identifier is a RUT (validated with `validateRut` at the call site), so
  services link by holder RUT + nickname; unlink is `POST account/delete`
  `{accounts: [{accountUuid}]}` (list of objects, not bare strings).
