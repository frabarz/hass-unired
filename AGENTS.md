# AGENTS.md

## Project Overview

Unofficial Home Assistant custom integration for Chilean Unired utility
payments (water/electricity/internet bill status from the app backend
`https://app1-prod-01.unired.cl/unired-api/v1/`). HACS-installable repo
**and** Nix flake (`packages`, `nixosModules`, `devShells`) for NixOS
deployment.

- Integration code: `custom_components/unired/` (domain `unired`,
  config-flow-only, `cloud_polling`, zero runtime `requirements`:
  stdlib + HA-bundled `aiohttp` only).
- Nix package: `pkgs/unired-ha/package.nix` (via
  `buildHomeAssistantComponent`).
- NixOS module: `nixos-modules/unired.nix`
  (`services.hass-unired.{enable, package}` → appends to
  `services.home-assistant.customComponents`).
- API research: `findings.md` (base-URL AES decryption, device-bound OTP
  login, account/instrument/debt endpoints — all verified live 2026-10-15).
  Research method: `jadx` + `hermes-decomp` on the APKs (git-ignored,
  `*.apk`/`unired_1.18/`), REA CLI for manifest/resources Evidence.
- Toolchain: Nix flake, HA 2026.10.x + Python 3.14 in dev shell; minimum
  supported runtime is HA 2026.1 (Python >= 3.13) per `hacs.json`. Keep code
  `py313`-compatible (`ruff target-version = py313`).
  `pytest` +
  `pytest-homeassistant-custom-component`.

## Setup Commands

- Enter dev env: `nix develop` (provides Python 3.14.x, HA 2026.9.x,
  `pytest`, `ruff`; all commands below assume this shell).
- Inspect outputs: `nix flake show`
- Check everything: `nix flake check`

## Development Workflow

- Integration implemented: `__init__.py` (lifecycle), `api.py`
  (`UniredClient`), `auth.py` (pairing tree), `coordinator.py` (poll fan-out),
  `sensor.py` (bill sensors), `config_flow.py` + `options_flow.py` (pairing,
  reauth, link/unlink, poll interval), `translations/en.json` + `es.json`,
  `diagnostics.py` (redacted).
- Auth model (from `findings.md` §7): first pairing is device-bound
  (`POST device` → e-mail OTP → `POST device/authorize` returns the token
  triple); poll with `access_token` header; refresh via
  `POST session/refreshToken` (tokens ROTATE — persist every refresh);
  `0509`/`0605` mean re-pair. Never guess OTPs (server attempt limits).
- Debt rule: per instrument, owed = Σ `billList[].amount` for `amount > 0`;
  empty/all-zero = nothing prepared. Debt endpoint returns **201**, accept any
  2xx.
- NixOS consumer wiring:
  ```nix
  imports = [ hass-unired.nixosModules.default ];
  services.hass-unired = {
    enable = true;
    package = hass-unired.packages.${pkgs.system}.unired-ha;
  };
  ```
  Requires `services.home-assistant.enable = true`. RUT/e-mail/OTP pairing
  stays in the HA UI (no declarative YAML for this integration).
- Keep `custom_components/unired/manifest.json` (`domain`, `version`,
  `requirements`) in sync with `pkgs/unired-ha/package.nix`
  (`domain`, `version`, `dependencies`) and `requirements.txt`.
- Bump `manifest.json → version` on every release (HACS compares it).

## Testing Instructions

- Run all tests: `pytest tests/ -q` (from repo root, inside `nix develop`).
- Suite: `test_manifest` (packaging sync) + `test_api`/`test_models`
  (client, fake aiohttp session) + `test_auth` (pairing tree) +
  `test_config_flow`/`test_options_flow` (phcc, mocked auth layer) +
  `test_coordinator`/`test_sensor` (mocked backend, full entry setup) +
  `test_translations`/`test_diagnostics`.
- Build Nix package: `nix build .#unired-ha` (runs manifest check
  hook; output `result/custom_components/unired/`).
- CI parity: `.github/workflows/validate.yml` (hassfest + HACS action),
  `.github/workflows/test.yml` (pytest + ruff).

## Code Style

- `ruff check .` and `ruff format --check .` must pass (line-length 88,
  `py313`, rules `E,F,I,UP,B,ASYNC` per `pyproject.toml`). Fix with
  `ruff check . --fix` / `ruff format .`.
- Fully typed, async-only code (`aiohttp` via HA session); never add sync
  `requests` calls to the integration.
- Translations: full literal text in `translations/en.json` (+ `es.json`);
  do NOT use core `strings.json` / `[%key:...%]` placeholders (unsupported
  in custom integrations).

## Build and Deployment

- `nix build .#unired-ha` → component derivation.
- HACS install: repo must keep `custom_components/unired/` at root,
  `hacs.json` (`country: CL`), `README.md`; ship via GitHub Release.
- Format Nix files: `nix fmt` (uses `nixfmt`).

## Additional Notes

- Gotchas (mirrored from the sibling `redregional` project):
  - `haPy.python.withPackages` resolves `ps` against the interpreter's
    default set, NOT the HA scope — reference HA packages absolutely
    (`haPy.pytest`, `haPy.homeassistant`, …) in `flake.nix`.
  - `pytest` binary needs explicit listing in `devShells`; transitive deps
    don't expose it.
  - Package `src` is fileset-filtered to `custom_components/` only, so the
    `*.apk` reverse-engineering artifacts (git-ignored) never enter the
    Nix store.
  - HA version skew: keep one nixpkgs input for system + flake.
  - HA 2026.10 types flow `data_schema` as `probatio.Schema`, but
    `voluptuous` still validates fine at runtime (proven by the flow tests)
    and keeps the 2026.1 floor where `probatio` may not exist — never import
    it. The zuban LSP flags vol schemas and some HA base-class properties;
    that noise is not part of the gate (`ruff` + `pytest`).
  - `async_set_unique_id` is a coroutine — awaiting it is what makes
    duplicate-entry aborts work; every `async_show_form(step_id=…)` needs a
    matching `async_step_<id>` handler or HA raises `UnknownStep`.
  - GitHub owner/repo (`frabarz/hass-unired` in `manifest.json`,
    `package.nix`, docs) is a placeholder until the release repo exists.
  - No `LICENSE` file yet — add MIT (or chosen license) before first release.
