"""Persistent exclusions shared by catalogue, industry review and price collection."""
from __future__ import annotations
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

_LOCK = threading.RLock()
_KR_PREFERRED = re.compile(r'^[0-9]{4}[0-9A-HJ-NP-TV-Z][579KLMN]$')

def load_exclusions(base_dir):
    path = Path(base_dir) / 'instrument_exclusions.json'
    if not path.exists():
        return {'version': 1, 'instruments': {}}
    return json.loads(path.read_text(encoding='utf-8'))

def detected_reason(country, symbol, name='', asset_type='STOCK'):
    if str(asset_type).upper() == 'ETF':
        return ''
    if str(country).upper() == 'KR':
        if '스팩' in str(name) or '기업인수목적' in str(name):
            return 'SPAC'
        if _KR_PREFERRED.fullmatch(str(symbol).strip().upper()) or re.search(r'우(?:[BC])?$', str(name)):
            return 'PREFERRED'
    # US common-share classes such as BRK.B are deliberately not preferred shares.
    if re.search(r'\bspecial purpose acquisition\b|\bblank[ -]check\b|\bSPAC\b', str(name), re.I):
        return 'SPAC'
    if re.search(r'\bpreferred (?:stock|shares)\b|\bdepositary shares\b.*\bpreferred\b', str(name), re.I):
        return 'PREFERRED'
    return ''

def exclusion_reason(base_dir, country, symbol, name='', asset_type='STOCK', records=None):
    if str(asset_type).upper() == 'ETF':
        return ''
    records = load_exclusions(base_dir)['instruments'] if records is None else records
    item = records.get(str(country).upper() + ':' + str(symbol).strip().upper())
    return item.get('reason', 'EXCLUDED') if item else detected_reason(country, symbol, name, asset_type)

def remember_exclusions(base_dir, rows):
    with _LOCK:
        data = load_exclusions(base_dir)
        changed = False
        for row in rows:
            country = str(row.get('country', '')).upper()
            symbol = str(row.get('symbol', '')).strip().upper()
            reason = detected_reason(country, symbol, row.get('name', ''), row.get('asset_type', 'STOCK'))
            key = country + ':' + symbol
            if reason and country in {'KR', 'US', 'JP'} and re.fullmatch(r'[A-Z0-9][A-Z0-9./_-]{0,24}', symbol) and key not in data['instruments']:
                data['instruments'][key] = {'country': country, 'symbol': symbol,
                    'name': row.get('name', symbol), 'reason': reason,
                    'reviewed_at': datetime.now().isoformat(timespec='seconds'), 'basis': '상장 목록의 증권 유형·명칭'}
                changed = True
        if changed:
            path = Path(base_dir) / 'instrument_exclusions.json'
            temp = path.with_name(path.name + '.tmp')
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temp, path)
        return data['instruments']
