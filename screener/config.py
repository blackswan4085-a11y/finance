"""설정 파일(config.yaml) 로드 및 기본값 처리."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

import yaml

# 시장 코드 -> 국가/통화 메타데이터
MARKET_META = {
    "KOSPI": {"country": "KR", "currency": "KRW"},
    "KOSDAQ": {"country": "KR", "currency": "KRW"},
    "KONEX": {"country": "KR", "currency": "KRW"},
    "SP500": {"country": "US", "currency": "USD"},
    "S&P500": {"country": "US", "currency": "USD"},
    "NASDAQ": {"country": "US", "currency": "USD"},
    "NYSE": {"country": "US", "currency": "USD"},
    "AMEX": {"country": "US", "currency": "USD"},
}


@dataclass
class Config:
    markets: List[str] = field(default_factory=lambda: ["KOSPI", "KOSDAQ", "SP500"])
    high_periods_weeks: List[int] = field(default_factory=lambda: [4, 13, 26, 52])
    ma_periods_weeks: List[int] = field(default_factory=lambda: [4, 13, 26, 52])
    include_mode: str = "any_high"
    lookback_days: int = 760
    min_avg_dollar_volume: float = 0.0
    max_workers: int = 8
    request_sleep: float = 0.0
    cache_dir: str = "cache"
    output_dir: str = "output"
    use_cache: bool = True
    port: int = 8000
    auto_open: bool = True
    usd_krw: float = 1400.0
    exclude_special: bool = True  # 우선주/유닛/권리 등 특수증권(보통주 아님) 제외

    base_dir: str = "."

    @property
    def cache_path(self) -> str:
        return os.path.join(self.base_dir, self.cache_dir)

    @property
    def output_path(self) -> str:
        return os.path.join(self.base_dir, self.output_dir)


def load_config(path: str = "config.yaml") -> Config:
    base_dir = os.path.dirname(os.path.abspath(path)) or "."
    data = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    cfg = Config(**{k: v for k, v in data.items() if k in Config.__annotations__})
    cfg.base_dir = base_dir
    os.makedirs(cfg.cache_path, exist_ok=True)
    os.makedirs(cfg.output_path, exist_ok=True)
    return cfg
