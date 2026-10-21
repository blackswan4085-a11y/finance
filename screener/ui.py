"""Shared chart-inspired theme, also embedded in offline reports."""
from pathlib import Path

def shared_ui() -> str:
    base = Path(__file__).resolve().parent.parent / "web"
    css = (base / "ui.css").read_text(encoding="utf-8")
    js = (base / "ui.js").read_text(encoding="utf-8")
    return "<style>" + css + "</style><script>" + js + "</script>"
