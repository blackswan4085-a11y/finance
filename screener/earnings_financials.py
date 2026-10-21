"""Validate the dashboard's financial table without inference or AI calls."""
from datetime import date
import math
import re


SOURCE_ID = "dashboard_financials"
CURRENCIES = ("USD", "EUR", "KRW", "JPY", "GBP", "CNY", "TWD")
NUMBER = re.compile(r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def number(value, label):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().replace("−", "-")
        if value.upper() in ("", "-", "—", "N/A", "NA"):
            return None
        if value.startswith("(") and value.endswith(")"):
            value = "-" + value[1:-1].strip()
        if not NUMBER.fullmatch(value):
            raise ValueError(f"{label}: 숫자를 확인해 주세요. 금액은 백만 단위로 입력합니다.")
        value = float(value.replace(",", ""))
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label}: 유효한 숫자를 입력해 주세요.")
    return value


def integer(value, low, high, label, prefix=""):
    text = str(value).strip().upper()
    if prefix and text.startswith(prefix):
        text = text[len(prefix):]
    if prefix == "Q" and text.endswith("분기"):
        text = text[:-2]
    if not re.fullmatch(r"\d+", text) or not low <= int(text) <= high:
        raise ValueError(f"{label}: {low}~{high} 범위의 정수를 입력해 주세요.")
    return int(text)


def manual_financials(raw, project):
    if not isinstance(raw, dict) or not isinstance(raw.get("company"), dict):
        raise ValueError("실적 표의 회사 정보를 확인해 주세요.")
    company = raw["company"]
    name = company.get("name", "")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 24:
        raise ValueError("표시할 회사명을 1~24자로 입력해 주세요.")
    currency, basis = company.get("currency"), company.get("basis")
    if currency not in CURRENCIES or basis not in ("GAAP", "Non-GAAP", "IFRS"):
        raise ValueError("통화와 실적 회계 기준을 확인해 주세요.")
    fiscal_month = integer(company.get("fiscalYearEndMonth"), 1, 12, "결산월")
    periods = raw.get("reportPeriod")
    if not isinstance(periods, dict):
        raise ValueError("실제 보고 기간을 확인해 주세요.")
    dates = {}
    for key, label in (("start", "시작일"), ("end", "종료일")):
        value = periods.get(key, "")
        if not isinstance(value, str):
            raise ValueError(f"보고 기간 {label}을 확인해 주세요.")
        value = value.strip()
        if value:
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) or date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError:
                raise ValueError(f"보고 기간 {label}을 YYYY-MM-DD로 입력해 주세요.") from None
        dates[key] = value
    if dates["start"] and dates["end"] and dates["start"] > dates["end"]:
        raise ValueError("보고 기간 시작일이 종료일보다 늦습니다.")
    result = {"schemaVersion": 1, "company": {"name": name.strip(), "ticker": project["ticker"],
              "currency": currency, "basis": basis, "fiscalYearEndMonth": fiscal_month, "isSample": False},
              "quarters": [], "annuals": [], "reportPeriod": dict(dates, sourceId=SOURCE_ID),
              "sources": [{"id": SOURCE_ID, "label": f"대시보드 실적 표 직접 입력 · {currency} 백만 / EPS 주당"}],
              "consensus": None, "conferenceCall": None, "callMetrics": [], "guidance": []}
    for kind, label in (("quarters", "분기 실적"), ("annuals", "연간 실적")):
        rows = raw.get(kind, [])
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError(f"{label}은 최대 100행까지 입력할 수 있습니다.")
        seen = set()
        metrics = ("revenue", "operatingIncome", "eps") if kind == "quarters" else ("revenue", "operatingIncome")
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise ValueError(f"{label} {index}행을 확인해 주세요.")
            values = {key: number(row.get(key), f"{label} {index}행 {key}") for key in metrics}
            if all(value is None for value in values.values()):
                continue  # Prefilled historical periods with blank metrics remain drafts.
            year = integer(row.get("year"), 1900, 2200, f"{label} {index}행 연도", "FY")
            entry = dict(values, year=year, sourceId=SOURCE_ID)
            if kind == "quarters":
                quarter = integer(row.get("quarter"), 1, 4, f"{label} {index}행 분기", "Q")
                if (year, quarter) > (project["year"], project["quarter"]):
                    raise ValueError("보고 대상 이후 분기의 예상치를 실적 표에 넣을 수 없습니다.")
                entry["quarter"] = quarter
                key = (year, quarter)
            else:
                if year > project["year"] or (year == project["year"] and project["quarter"] != 4):
                    raise ValueError("연간 실적에는 완료된 회계연도만 입력해 주세요. 누적·예상 실적은 제외합니다.")
                entry["complete"] = True
                key = year
            if key in seen:
                raise ValueError(f"{label}의 기간이 중복되었습니다.")
            seen.add(key)
            result[kind].append(entry)
        result[kind].sort(key=lambda row: (row["year"], row.get("quarter", 0)))
    return result


def financials_ready(data, project):
    period = data.get("reportPeriod") or {}
    return bool(period.get("start") and period.get("end") and any(
        row.get("year") == project["year"] and row.get("quarter") == project["quarter"]
        and any(row.get(key) is not None for key in ("revenue", "operatingIncome", "eps"))
        for row in data.get("quarters", [])))
