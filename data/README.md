# 공유 기준 자료

| 파일 | 내용 |
|---|---|
| `industry_taxonomy.json` | KUIM 대분류·중분류·세부산업과 가져오기 출처 |
| `industry_assignments.json` | 국가·종목코드별 원본 산업 배정, 검토 상태와 출처 |
| `industry_taxonomy_extensions.json` | 원본에 없는 추가 산업 정의·근거 |
| `customs_hs_names.json` | 한·미·일 공통 HS 2·4·6·10자리 한국어 명칭 (`통합 문서1.xlsx` 기준) |

서버의 기본 조회에 필요한 자료이므로 Git에 포함한다. 개인 산업 수정·증권 제외 이력은 프로젝트 루트의 별도 로컬 JSON에 저장되며 Git에서 제외한다.

산업 갱신: `python scripts/import_kuim.py --import --source <원본.xlsx>`.
HS 명칭 갱신: `python scripts/import_customs_names.py <원본.xlsx>`.
원본 엑셀은 갱신할 때만 필요하며 저장소에 포함하지 않는다.

세 나라 모두 `screener/customs/names.py`에서 명칭을 조회한다. 하위 구분 없이
끝이 0인 6자리·10자리 코드만 있는 경우 상위 자리수에서도 같은 명칭을 사용한다
(예: `2709` = `270900`, 원유). 표에 없는 최신 코드는 `(상위 품목)`을 붙인다.
일본 `00`, 미국 `98`·`99`의 한국어 명칭은 같은 모듈에 별도로 정의한다.
금액·단가의 K/M/B 표시는 `screener/trade_display.py`를 세 화면에서 함께 사용한다.
