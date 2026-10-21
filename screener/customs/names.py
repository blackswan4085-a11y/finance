"""HS descriptions supplied in the user's workbook take precedence over API labels."""
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def _catalogue():
    path = Path(__file__).resolve().parents[2] / "data" / "customs_hs_names.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["names"]


def code_name(code: str, fallback: str = "") -> str:
    return _catalogue().get(code) or fallback
