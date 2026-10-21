#!/usr/bin/env python3
"""KRX(한국거래소) 접속 진단 스크립트.

KOSPI/KOSDAQ 리스팅 실패("Expecting value: line 1 column 1") 원인을
집 PC에서 그대로 재현해 무엇이 오는지 보여줍니다.

사용법:
    python scripts/diagnose_krx.py
결과를 그대로 복사해서 공유하면 원인을 특정할 수 있습니다.
"""
from __future__ import annotations

import json
import sys

try:
    import requests
except ImportError:
    print("requests 가 없습니다. 먼저: pip install requests")
    sys.exit(1)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",
}

# FDR이 KOSPI/KOSDAQ 리스팅 때 가장 먼저 호출하는 바로 그 엔드포인트
HTTP_URL = ("http://data.krx.co.kr/comm/bldAttendant/executeForResourceBundle.cmd"
            "?baseName=krx.mdc.i18n.component&key=B128.bld")
HTTPS_URL = HTTP_URL.replace("http://", "https://")


def probe(label: str, url: str) -> None:
    print(f"\n===== {label} =====")
    print("URL:", url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
    except Exception as e:  # noqa: BLE001
        print("요청 자체 실패:", repr(e))
        return
    ct = r.headers.get("content-type", "")
    print("status      :", r.status_code)
    print("content-type:", ct)
    print("length      :", len(r.text))
    head = r.text[:300].replace("\n", " ")
    print("응답 앞부분  :", repr(head))
    # JSON 파싱 시도
    try:
        j = json.loads(r.text)
        dt = j.get("result", {}).get("output", [{}])[0].get("max_work_dt")
        print("JSON 파싱    : 성공 ✅  최근영업일 =", dt)
    except Exception as e:  # noqa: BLE001
        print("JSON 파싱    : 실패 ❌ ->", repr(e))
        if "<html" in r.text.lower() or "<!doctype" in r.text.lower():
            print("  → HTML이 왔습니다. ISP/방화벽/백신이 http 요청을 가로채 "
                  "차단 페이지를 돌려줬을 가능성이 큽니다.")
        elif len(r.text.strip()) == 0:
            print("  → 빈 응답입니다. 네트워크 차단 또는 KRX의 IP 차단일 수 있습니다.")


def main() -> int:
    print("KRX 접속 진단을 시작합니다. (집 네트워크에서 실행하세요)")
    probe("1) HTTP (FDR 기본 경로)", HTTP_URL)
    probe("2) HTTPS (암호화 경로)", HTTPS_URL)
    print("\n--- 해석 가이드 ---")
    print("• HTTP는 실패하는데 HTTPS는 성공 → ISP/보안장비가 평문(http)을 가로챈 것.")
    print("  해결: FDR을 https로 쓰도록 패치하거나, pykrx로 한국 데이터를 받으면 됩니다.")
    print("• 둘 다 HTML/빈응답 → KRX가 현재 IP를 차단했거나 방화벽/백신/VPN 간섭.")
    print("  해결: VPN/백신 끄고 재시도, 또는 다른 네트워크에서 시도.")
    print("• 둘 다 JSON 성공 → KRX는 정상. 일시적 문제였을 수 있으니 run.py 재실행.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
