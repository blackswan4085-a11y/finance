# Finance

실적 리포트, 주간 주식 스크리너·시장 Recap, 산업 분류·차트, 수출입 통계를 하나의 로컬 대시보드에서 사용합니다.

## 실행

Python 3.10 이상과 Node.js가 필요합니다. 실적 PNG 생성은 Windows의 맑은 고딕과 Python Pillow를 사용합니다.

```powershell
python -m pip install -r requirements.txt
python run.py
```

브라우저에서 [localhost:8000](http://localhost:8000)을 엽니다. 서버 시작은 시세 수집이나 AI 생성을 자동 실행하지 않습니다.

- `/`: 실적 입력·리포트 생성
- `/weekly`: 주간 신고가·정배열 스크리너
- `/recap`: 시장 Recap
- `/industries`, `/chart`: 산업 분류와 종목·ETF 차트
- `/customs`: 수출입 통계

수출입 데이터를 수집하려면 `.env.example`을 `.env`로 복사하고 `CUSTOMS_API_KEY`를 입력합니다. 컨콜 요약과 Recap 코멘터리에는 설치·로그인된 Codex CLI를 사용합니다. 수치 입력·저장에는 AI가 필요하지 않습니다.

## 저장소 구성

```text
finance/
  run.py                  실행 진입점
  config.yaml             실행 설정
  requirements.txt        Python 의존성
  screener/               서버·데이터 처리·기능 모듈
  web/                    HTML·JavaScript·CSS·차트 자산
  data/                   공용 산업 분류·HS 명칭 기준 자료
  earnings/               고정 실적 렌더러와 작업 안내
  scripts/                가져오기·갱신·진단·검증 도구
  tests/                  개인 데이터 없이 실행하는 회귀 검증
  docs/                   사용법과 구조 설명
```

DB·시세 캐시·완성 보고서·개인 분류·API 키는 로컬 파일로 보존하며 Git에서 제외합니다. 원본 엑셀 없이도 `data/`의 기준 자료로 시작할 수 있습니다. 새로 받은 저장소에서는 저장된 실적·시세·수출입 데이터가 없는 상태로 시작합니다.

## 검증

```powershell
python scripts/check.py
python scripts/check_repository.py
```

첫 명령은 문법·실적·스크리너·산업·수출입·입력 표를 검사하며 외부 수집 API나 AI를 호출하지 않습니다. 두 번째 명령은 Git 업로드 후보에서 로컬 데이터·자격 증명·작업 기록이 제외됐는지 확인합니다. 두 명령 모두 Git에 파일을 추가하거나 커밋하지 않습니다.

[상세 사용법](docs/USAGE.md) · [프로그램 구조](docs/STRUCTURE.md) · [기준 자료](data/README.md)
