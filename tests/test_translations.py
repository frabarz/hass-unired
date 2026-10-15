"""Translation parity: en/es share the exact key tree, no empty strings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TRANS = Path("custom_components/unired/translations")


def _load(lang: str) -> dict[str, Any]:
    return json.loads((TRANS / f"{lang}.json").read_text())


def _leaves(node: Any, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            out.update(_leaves(value, f"{prefix}.{key}" if prefix else key))
    else:
        out[prefix] = node
    return out


def test_translation_key_parity_and_content() -> None:
    """Both locales expose identical keys with non-empty literal text."""
    en = _leaves(_load("en"))
    es = _leaves(_load("es"))
    assert set(en) == set(es)
    texts = (*en.values(), *es.values())
    assert all(isinstance(text, str) and text.strip() for text in texts)


def test_required_flow_keys_present() -> None:
    """Every step/error/abort the flow can reach is translated."""
    en = _load("en")["config"]
    assert set(en["step"]) == {"user", "otp", "reauth_confirm"}
    for step in en["step"].values():
        assert step["title"].strip()
        assert step["description"].strip()
    assert set(en["error"]) >= {
        "cannot_connect",
        "invalid_otp",
        "terms_not_accepted",
        "unknown",
    }
    assert set(en["abort"]) >= {
        "already_configured",
        "reauth_successful",
        "unknown",
    }
    assert set(en["step"]["user"]["data"]) == {"rut", "email", "name", "accept_terms"}
    assert set(en["step"]["otp"]["data"]) == {"code"}


def test_options_and_entity_keys_present() -> None:
    """Options menu steps, errors, and the sensor name are translated."""
    en = _load("en")
    assert set(en["options"]["step"]) == {
        "init",
        "add_service",
        "add_service_manual",
        "add_details",
        "remove_service",
        "settings",
    }
    assert set(en["options"]["error"]) >= {"invalid_input", "unknown"}
    assert en["entity"]["sensor"]["bill_amount"]["name"].strip()
