# Installation

## Via HACS (recommended)

1. HACS → Integrations → ⋮ → Custom repositories → add this repository URL
   with category *Integration*.
2. Find “Unired” in HACS and install it.
3. Restart Home Assistant.
4. Settings → Devices & Services → Add Integration → Unired, then complete
   the RUT + e-mail + OTP pairing (one 4-digit code per new device).

Once accepted into the HACS default store, step 1 becomes a plain search.

## Manual install

Copy `custom_components/unired/` into your Home Assistant
`config/custom_components/` directory and restart. Requires Home Assistant
2026.1+ (Python ≥ 3.13); the integration needs no extra packages beyond what
Home Assistant already ships.

## Via the NixOS flake

```nix
# flake.nix inputs
hass-unired.url = "github:frabarz/hass-unired";

# NixOS configuration
imports = [ hass-unired.nixosModules.default ];

services.home-assistant.enable = true;
services.hass-unired = {
  enable = true;
  package = hass-unired.packages.${pkgs.system}.unired-ha;
};
```

Notes:

- Requires `services.home-assistant.enable = true`; the module appends the
  component to `services.home-assistant.customComponents`.
- Use the **same nixpkgs input** for your system and this flake to avoid Home
  Assistant version skew. See `nixos-modules/unired.nix`.
