"""Regression checks for the Windows local-backend launcher without starting it."""
from pathlib import Path

launcher = (Path(__file__).resolve().parents[1] / "start_backend.bat").read_text(encoding="utf-8")
assert "C:\\Users\\you" not in launcher
assert ".venv\\Scripts\\python.exe" in launcher
assert "-m venv .venv" in launcher
assert "-m pip install -r deploy\\requirements.txt" in launcher
assert "server.py --host 127.0.0.1 --port 8787" in launcher
assert "--host 0.0.0.0" not in launcher
print("Windows launcher contract: PASS")
