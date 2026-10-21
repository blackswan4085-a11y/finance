# 실적 리포트 작업
사용자가 실적 리포트를 요청하면 earnings-template/AGENTS.md, EXTRACT.md, schema.json을 읽고 확정된 고정 렌더러를 사용하세요.
사용자 자료는 자료/<티커_FY연도Q분기>/에서 읽고, 같은 이름의 결과/<폴더명>/에 input.snapshot.json, PNG와 확인용 HTML을 저장하세요. JSON을 먼저 완성한 뒤 node earnings-template/render.mjs "결과/<폴더명>/input.snapshot.json" "결과/<폴더명>"으로 렌더링하세요.
폴더명은 예를 들어 V_FY2026Q3입니다. 사용자가 다른 이름을 지정하면 해당 이름을 따르세요. 사용자가 대화로 제공한 원문도 해당 자료 폴더에 보관하세요.
사용법.md에 자료 종류와 실행 방법이 있습니다. JSON 형식은 schema.json과 ../tests/fixtures/earnings.json의 가상 예시를 참고하되 다른 회사·기간의 수치나 발언 또는 가상 수치를 실제 보고서에 재사용하지 마세요.
디자인 변경 요청이 없으면 입력 JSON만 작성하고, ImageGen으로 보고서를 다시 그리지 마세요. 의견·핵심 요약·다음 분기 질문 없이 수치와 발언 내용을 정리하세요.
