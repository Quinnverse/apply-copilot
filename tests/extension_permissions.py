"""Manifest regression: pages receive no content script until a user grants site access."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))

assert manifest["manifest_version"] == 3
assert "scripting" in manifest["permissions"]
assert "<all_urls>" not in manifest.get("host_permissions", [])
assert manifest.get("content_scripts") == []
assert set(manifest.get("optional_host_permissions", [])) == {"http://*/*", "https://*/*"}
popup = (ROOT / "extension" / "popup.js").read_text(encoding="utf-8")
background = (ROOT / "extension" / "background.js").read_text(encoding="utf-8")
assert "chrome.permissions.request" in popup
assert "chrome.scripting.executeScript" in popup
assert "chrome.tabs.onUpdated" in background
assert "chrome.permissions.contains" in background
print("extension permission gate: PASS")
