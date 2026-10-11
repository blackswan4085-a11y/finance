# 📈 신고가 · 정배열 스크리너

한국(KOSPI/KOSDAQ) + 미국(S&P500/NASDAQ/NYSE) 전체 시장을 매일 장 전에 스캔하여
**신고가**와 **주봉 이동평균 정배열** 종목을 찾아 **필터 가능한 HTML 리포트**로 보여줍니다.

## 체크 조건

- **신고가 (고가 기준)**: 최근 주봉의 고가가 과거 N주 중 최고가인지
  - 4주 / 13주 / 26주 / 52주 각각 판정
- **정배열 (주봉 이동평균, 종가 기준)**: `MA4주 > MA13주 > MA26주 > MA52주` 로 내림차순이면 정배열

> 포함 기준(기본값 `any_high`): 4/13/26/52주 신고가 중 **하나라도** 충족하면 리포트에 포함.
> 리포트 안에서 신고가 조건·시장·정배열 여부를 **직접 필터링**할 수 있습니다.

## 설치

```bash
pip install -r requirements.txt
```

## 사용법

```bash
# config.yaml 기준으로 전체 스캔 → HTML 리포트 생성
python3 run.py

# 특정 시장만
python3 run.py --markets KOSPI KOSDAQ

# 캐시 무시하고 새로 받기
python3 run.py --no-cache

# 포함 기준 바꾸기 (신고가 AND 정배열 둘 다 만족한 것만)
python3 run.py --include-mode require_both
```

생성된 리포트는 `output/report_YYYY-MM-DD.html` 에 저장됩니다.
브라우저로 그 파일을 열면 됩니다.

## HTML 리포트에서 할 수 있는 필터링

- **검색**: 종목명 / 코드로 즉시 필터
- **시장 선택**: KOSPI / KOSDAQ / SP500 등
- **신고가 조건 칩**: 4주 / 13주 / 26주 / 52주 중 원하는 것 선택
  - **OR(하나라도)** / **AND(모두)** 전환 가능
- **정배열만 보기** 토글
- **최소 시가총액 필터**: 전체 / 소형↑ / 중형↑ / 대형↑ (한국·미국 각각 임계값 자동 적용 → 소형주 걸러내기)
- 모든 컬럼 **클릭 정렬** (시가총액, 충족수, 종가, MA 등)

## 시가총액

- **한국(KOSPI/KOSDAQ)**: KRX 캐시 CSV의 시가총액(원)을 그대로 사용
- **미국(SP500/NASDAQ/NYSE)**: Nasdaq 공개 스크리너 API로 전종목 시총을 1회 호출로 수집 (API 키 불필요)
- 표시: 한국은 `조/억`, 미국은 `$T/$B/$M` 로 축약

## 설정 (config.yaml)

| 항목 | 설명 |
|---|---|
| `markets` | 스캔할 시장 목록 |
| `high_periods_weeks` | 신고가 판정 주기 (기본 4/13/26/52주) |
| `ma_periods_weeks` | 정배열 이동평균 주기 (기본 4/13/26/52주) |
| `include_mode` | `any_high` / `any_signal` / `require_both` |
| `lookback_days` | 다운로드 기간 (52주 MA용으로 2년 권장) |
| `use_cache` | 캐시 사용(증분 업데이트)으로 매일 빠르게 실행 |
| `max_workers` | 동시 다운로드 스레드 수 |
| `request_sleep` | 레이트 리밋 발생 시 0.1~0.3으로 설정 |

## 매일 자동 실행 (선택)

macOS/Linux cron 예시 — 평일 아침 8시 실행:

```cron
0 8 * * 1-5 cd /path/to/stock-screener && python3 run.py >> run.log 2>&1
```

## 다른 국가 확장

`screener/config.py`의 `MARKET_META`와 `screener/universe.py`의 `_LISTING_CODE`에
FinanceDataReader가 지원하는 시장 코드를 추가하면 됩니다.

## 데이터 소스

[FinanceDataReader](https://github.com/FinanceData/FinanceDataReader) (무료, 증권사 API 불필요).
일봉을 받아 주봉(금요일 마감)으로 리샘플링하여 지표를 계산합니다.

## 성능 참고

- 미국 NASDAQ(약 4000종목) + NYSE(약 2800종목) 전체는 종목이 매우 많아 첫 실행이 오래 걸립니다.
  캐시가 있으면 다음날부터는 증분 업데이트라 빠릅니다.
- 처음에는 `KOSPI`, `KOSDAQ`, `SP500` 정도로 시작하는 것을 권장합니다.

---
*투자 판단과 그 결과의 책임은 전적으로 본인에게 있습니다. 이 도구는 참고용 스크리너입니다.*
