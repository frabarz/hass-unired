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
hass-unired = {
  url = "github:frabarz/hass-unired";
  inputs.nixpkgs.follows = "nixpkgs";
};

# NixOS configuration (`inputs` is available via specialArgs)
services.home-assistant = {
  enable = true;
  customComponents = [
    inputs.hass-unired.packages.${pkgs.stdenv.hostPlatform.system}.default
  ];
};
```

Notes:

- The stock Home Assistant module installs the component through
  `services.home-assistant.customComponents`; no custom NixOS module is needed.
- Keep `inputs.nixpkgs.follows = "nixpkgs"` so the component is built against
  the same Home Assistant version you run.
- RUT/e-mail/OTP pairing stays in the Home Assistant UI (there is no
  declarative YAML for this integration).
