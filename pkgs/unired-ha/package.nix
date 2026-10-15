# Arguments are resolved from home-assistant.python3Packages scope.
# IMPORTANT: call via pkgs.home-assistant.python3Packages.callPackage, NOT
# pkgs.callPackage, so buildHomeAssistantComponent and any future Python
# deps come from HA's pinned interpreter set.
{
  lib,
  buildHomeAssistantComponent,
  src,
}:

buildHomeAssistantComponent rec {
  owner = "frabarz";
  domain = "unired";
  version = "0.1.0";

  inherit src;

  # No runtime `dependencies`: the integration uses only stdlib + aiohttp
  # (already bundled with Home Assistant). The Unired API base URL is
  # hardcoded (decrypted once during research, see findings.md §1) instead
  # of reimplementing the app's CryptoJS AES config decryption at runtime.
  # If a third-party lib is added later, declare it here (from
  # home-assistant.python3Packages) AND pin it in
  # custom_components/unired/manifest.json -> requirements.

  meta = {
    description = "Unired utility-bill sensors (water/electricity/internet debt polling)";
    homepage = "https://github.com/frabarz/hass-unired";
    license = lib.licenses.mit;
    maintainers = [ ];
  };
}
