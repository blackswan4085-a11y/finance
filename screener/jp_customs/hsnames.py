"""Japanese trade views use the same Korean HS catalogue as Korea and the US."""
from ..customs.names import code_name


def hs_name(code: str) -> str:
    return code_name(code)
