"""Shared Korean HS labels for Korea, United States and Japan trade views."""
from functools import lru_cache
import json
from pathlib import Path


SPECIAL_NAMES = {
    "00": "재수출·재수입·항공기용품",
    "0000": "재수출·재수입·항공기용품",
    "000000": "재수출·재수입·항공기용품",
    "98": "특수분류 품목",
    "9801": "수리 후 수출품·재수입품",
    "980100": "가공 없이 재수입한 물품",
    "980110": "수입물품의 수리·변경 후 수출",
    "9802": "구호용 수출품·가공 후 재수입품",
    "980200": "가공 후 재수입한 물품",
    "980210": "구호·자선용 기증 식품",
    "980220": "기증 의약품",
    "980230": "구호용 기증 의류",
    "980240": "기타 구호용 기증 물품",
    "9803": "군용 의류·장비",
    "980310": "군용 의류",
    "980320": "기타 군용 장비",
    "9808": "미국 정부 수입품",
    "980800": "미국 정부 수입품",
    "9810": "종교·교육·과학기관 수입품",
    "981000": "종교·교육·과학기관 수입품",
    "9812": "영구 전시용 보세 면세 수입품",
    "981200": "영구 전시용 보세 면세 수입품",
    "9817": "기타 특수분류 면세 수입품",
    "981700": "기타 특수분류 면세 수입품",
    "9818": "해외 구입·수리 장비와 부분품",
    "981800": "해외 구입·수리 장비와 부분품",
    "9870": "캐나다 관련 특수분류 품목",
    "987000": "캐나다 관련 특수분류 품목",
    "9880": "소액 수출·캐나다 지연신고 추정액",
    "988000": "소액 수출·캐나다 지연신고 추정액",
    "99": "특별 수입분류 품목",
    "9999": "인양품·소액 수입 추정액",
    "999900": "침몰 선박에서 인양한 과세 물품",
    "999995": "소액 수입거래 추정액",
}


@lru_cache(maxsize=1)
def _catalogue():
    path = Path(__file__).resolve().parents[2] / "data" / "customs_hs_names.json"
    if not path.is_file():
        return {}
    names = json.loads(path.read_text(encoding="utf-8"))["names"]
    # Unsplit headings may exist only as HS6 (270900) or HSK10 (2705000000).
    # Explicit names take precedence, followed by the shortest equivalent code.
    for code in sorted(tuple(names), key=len):
        for length in (2, 4, 6):
            if len(code) > length and set(code[length:]) == {"0"}:
                names.setdefault(code[:length], names[code])
    return names


def code_name(code: str, fallback: str = "") -> str:
    """Use a common Korean label; identify parent labels for newer missing codes."""
    code = (code or "").strip()
    names = _catalogue()
    exact = SPECIAL_NAMES.get(code) or names.get(code)
    if exact:
        return exact
    for length in (6, 4, 2):
        if length >= len(code):
            continue
        parent = code[:length]
        name = SPECIAL_NAMES.get(parent) or names.get(parent)
        if name:
            return f"{name} (상위 품목)"
    return fallback if any("가" <= char <= "힣" for char in fallback or "") else "품목명 미등록"
