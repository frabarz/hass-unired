# NixOS module wiring the Unired custom component into
# services.home-assistant. Config-flow-only: the module only installs the
# component (customComponents); RUT/e-mail/OTP pairing happens in the HA UI,
# and declarative `services.home-assistant.config.unired` is NOT used.
{
  config,
  lib,
  ...
}:

let
  cfg = config.services.hass-unired;
in
{
  options.services.hass-unired = {
    enable = lib.mkEnableOption "Unired Home Assistant custom integration";

    package = lib.mkOption {
      type = lib.types.package;
      description = ''
        The unired custom component derivation.
        Defaults to this flake's package built against the flake's nixpkgs
        (same input as your system should use to avoid HA version skew).
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.services.home-assistant.enable;
        message = "services.hass-unired.enable requires services.home-assistant.enable = true.";
      }
    ];

    services.home-assistant.customComponents = [ cfg.package ];
  };
}
