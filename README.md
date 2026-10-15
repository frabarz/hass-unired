# Unired — Home Assistant integration

Water, electricity, and internet bill status for Chilean
[Unired](https://www.unired.cl/) accounts, straight from the same backend the
official Android app uses into Home Assistant.

> **Unofficial integration, no affiliation with Unired S.A.** The backend is
> reverse-engineered and may change without notice. The app API authenticates
> with an e-mail OTP like a new device would.

## What it does

Set up your RUT once, get a device with one sensor per utility account
(water, electricity, internet, …):

- **Bill amount** — the current debt in CLP (`0` / `unknown` while no bill is
  prepared), with per-bill details (due date, contract number, company, …) as
  attributes.

Works in English and Spanish. Requires Home Assistant 2026.1 or newer.

## Install

Via HACS (recommended):

1. HACS → Integrations → ⋮ → Custom repositories → add this repo URL
   (category *Integration*).
2. Install “Unired”, restart Home Assistant.
3. Settings → Devices & Services → Add Integration → Unired, then follow the
   RUT + e-mail + OTP pairing.

Details and alternatives (manual install, NixOS flake):
[docs/installation.md](docs/installation.md).

## Documentation

- [Configuration](docs/configuration.md) — pairing, linking services, options.
- [Entities](docs/entities.md) — bill sensors and attributes.
- [Dashboards](docs/dashboards.md) — cards and "bill prepared" automations.
- [Troubleshooting](docs/troubleshooting.md) — server codes, OTP mail, reauth.

## Development

```bash
nix develop            # HA 2026.10 / Python 3.14 + pytest + ruff
pytest tests/
ruff check . && ruff format --check .
nix build .#unired-ha
nix flake check
```

Implementation notes live in
[AGENTS.md](AGENTS.md); the API research behind this integration is in
[findings.md](.design/findings.md) (base URL decryption, device-bound OTP login,
polling endpoints — all verified live against a real account).
