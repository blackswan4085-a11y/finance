# 실적 리포트 렌더러

실제 사용 안내와 복사용 프롬프트는 작업 폴더 루트의 `사용법.md`를 읽으세요.

## 폴더

- `../자료/<폴더명>/`: 사용자가 넣는 컨콜·재무표·메모
- `../결과/<폴더명>/`: 완성 PNG·HTML·입력 JSON·계산 근거
- 이 폴더: 확정 디자인 1.8의 렌더러, 스키마, AI 작업 지침

## 실행

AI가 원문을 읽고 `schema.json`에 맞는 `input.snapshot.json`을 작성한 뒤 실행합니다. 원문 파일을 넣는 것만으로 자동 분석되는 프로그램은 아닙니다.

작업 폴더 루트에서:

```powershell
node earnings-template/render.mjs "결과/V_FY2026Q3/input.snapshot.json" "결과/V_FY2026Q3"
```

두 번째 인수를 생략하면 `결과/<티커>_FY<연도>Q<분기>/`에 저장합니다. `render.cmd`에 완성 JSON 파일을 끌어놓아도 같은 방식으로 렌더링됩니다. 원문 Excel/TXT를 직접 넣는 용도는 아닙니다.

## 파일

| 파일 | 역할 |
|---|---|
| `AGENTS.md`, `EXTRACT.md` | 자료 정리와 표시 규칙 |
| `schema.json` | 입력 JSON 형식 |
| `report.mjs` | 실적 지표·PER 계산, 입력 형식 처리 |
| `draw_report.py` | 고정 PNG 디자인 |
| `render.mjs`, `render.cmd` | 렌더링 실행 |
| `.runtime/fonts/` | 재현 가능한 렌더링에 사용하는 고정 글꼴 |

## 확정 규칙

버전 1.8.0은 한 페이지에 이번 분기 실적, 과거 실적 추이, 주가·밸류에이션, 컨콜 주요 수치만 배치합니다. 가이던스·컨센서스 섹션과 비교는 사용하지 않습니다. 기존 JSON의 전망 항목은 호환 목적으로 읽을 수 있지만 출력에 반영하지 않습니다.

PER은 주가 ÷ (이번 분기 EPS × 4)로 고정 계산합니다. 시장 자료의 출처와 기준시점은 JSON·HTML에 기록합니다. RIG의 compact-review-v1은 컨콜 최대 6개와 간결한 시장 자료 표시를 사용합니다.

## 실행 환경

Node.js와 Python + Pillow가 필요합니다. 현재 PC의 Anaconda Python을 자동으로 찾습니다. 다른 Python은 `EARNINGS_PYTHON`으로 지정할 수 있습니다. 별도 npm 패키지나 API 키는 필요하지 않습니다.

`marketData`가 없으면 시장 자료는 미제공으로 표시합니다. 주가·EPS 통화 불일치, EPS가 0 이하, 주식분할로 EPS 비교 기준이 달라지면 PER을 산출하지 않습니다. JSON 형식의 가상 예시는 `../../tests/fixtures/earnings.json`에 있습니다.
