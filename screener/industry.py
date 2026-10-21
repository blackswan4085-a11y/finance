"""KUIM three-level industries, independent of the legacy ETF associations."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from .security_policy import exclusion_reason, load_exclusions
from zipfile import ZipFile
import xml.etree.ElementTree as ET

_LOCK = threading.RLock()
_CACHE = {}
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
LEVELS = {'major': 1, 'middle': 2, 'minor': 3}
REVIEW_LABELS = {'approved': '사업 검토 완료', 'draft': '자동 분류 초안', 'review': '사업 검토 필요',
                 'unclassified': '미분류', 'excluded': '분류 제외', 'manual': '직접 지정'}
REASON_LABELS = {
    'BROAD_NODE_NEEDS_SUBINDUSTRY_REVIEW': '하위 산업 검토 필요',
    'APP_SECTOR_MANUAL_OR_AUTO_ORIGIN_UNCONFIRMED': '기존 섹터의 입력·자동 분류 근거 미확인',
    'NO_PRECISE_CROSSWALK': '정확한 산업 대응표 없음',
    'SPAC_BUSINESS_UNCONFIRMED': '스팩 사업 미확인',
    'SHELL_COMPANY_BUSINESS_UNCONFIRMED': '실제 영업 사업 미확인',
    'ISSUER_IDENTITY_NEEDS_REVIEW': '발행 기업 확인 필요',
    'ADR_UNDERLYING_IDENTITY_AND_RATIO_UNVERIFIED': 'ADR 원주·전환 비율 미확인',
    'PUBLISHER_SECTOR_CONFLICT': '자료 간 섹터 불일치',
    'ASSET_FORM_NEEDS_REVIEW': '증권 유형 검토 필요',
    'UNCLASSIFIED_OR_ALTERNATIVES_ONLY': '산업 미분류 또는 검토 대안만 있음',
    'UNCLASSIFIED_OR_ALTERNATIVE_SECTORS_ONLY': '산업 미분류 또는 검토 대안만 있음',
    'OFFICIAL_BUSINESS_REVIEW_DETAILS_IN_SEPARATE_LEDGER': '별도 원장의 사업 근거 검토 필요',
    'FINANCIAL_OR_NONFINANCIAL_HOLDING_UNRESOLVED': '금융·비금융 지주 구분 필요',
    'OFFICIAL_CLOSED_END_FUND': '폐쇄형 펀드',
    'MULTIPLE_PRODUCT_HINTS_NOT_MULTIPLE_APPROVED_BUSINESSES': '복수 제품 단서는 복수 사업 승인 근거가 아님',
    'PRODUCT_HINTS_ACROSS_SECTORS_REVIEW': '제품 단서의 산업 간 교차 검토 필요',
    'PRODUCT_METADATA_MISSING': '제품 정보 누락',
    'CROSS_MARKET_DRAFT_DISAGREEMENT': '시장별 분류 초안 불일치',
    'FOREIGN_REGION_METADATA_REVIEW': '해외 지역 정보 검토 필요',
    'SECTOR_ONLY_NO_BUSINESS_PROOF': '섹터 정보만 있고 사업 근거 없음',
}

def _read_json(path, default=None):
    if not path.exists():
        if default is not None:
            return copy.deepcopy(default)
        raise ValueError('산업 분류 자료가 없습니다. KUIM 참고 파일을 확인해 주세요.')
    stamp = (path.stat().st_mtime_ns, path.stat().st_size)
    with _LOCK:
        cached = _CACHE.get(str(path))
        if cached and cached[0] == stamp:
            return cached[1]
        value = json.loads(path.read_text(encoding='utf-8'))
        _CACHE[str(path)] = (stamp, value)
        return value


def _write_json(path, value):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)
    _CACHE.pop(str(path), None)


def workbook_rows(path):
    with ZipFile(path) as archive:
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(t.text or '' for t in node.iter('{'+NS['m']+'}t'))
                       for node in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        relations = {node.attrib['Id']: node.attrib['Target'] for node in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        sheets = ET.fromstring(archive.read('xl/workbook.xml')).find('m:sheets', NS)
        output = {}
        for sheet in sheets:
            target = relations[sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            target = target.lstrip('/') if target.startswith('/') else 'xl/' + target
            rows = []
            for row in ET.fromstring(archive.read(target)).findall('m:sheetData/m:row', NS):
                cells = {'source_row': int(row.attrib['r'])}
                for cell in row.findall('m:c', NS):
                    value = cell.find('m:v', NS)
                    text = value.text if value is not None else ''
                    if cell.attrib.get('t') == 's':
                        text = strings[int(text)] if text else ''
                    elif cell.attrib.get('t') == 'inlineStr':
                        text = ''.join(t.text or '' for t in cell.iter('{'+NS['m']+'}t'))
                    if text:
                        cells[re.sub(r'\d+$', '', cell.attrib['r'])] = text
                if len(cells) > 1:
                    rows.append(cells)
            output[sheet.attrib['name']] = rows
        return output


def _ids(value):
    return list(dict.fromkeys(part.strip() for part in str(value or '').split(';') if part.strip()))


def _terminal_ids(ids, nodes):
    chosen = set(ids)
    covered = set()
    for node_id in ids:
        parent = nodes[node_id]['parent_id']
        while parent:
            if parent in chosen:
                covered.add(parent)
            parent = nodes[parent]['parent_id']
    return [node_id for node_id in ids if node_id not in covered]


def import_workbook(base_dir, source=None):
    base = Path(base_dir)
    source = Path(source) if source else base / 'KUIM_전체결과표.xlsx'
    data_dir = base / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    sheets = workbook_rows(source)
    if not {'기업전체', '산업분류'}.issubset(sheets):
        raise ValueError('KUIM 엑셀의 기업전체·산업분류 시트를 확인해 주세요.')
    nodes = {}
    for row in sheets['산업분류']:
        if row['source_row'] < 7:
            continue
        for node_id, name, level, parent in [(row.get('B'), row.get('C'), 'major', ''),
                                            (row.get('D'), row.get('E'), 'middle', row.get('B')),
                                            (row.get('F'), row.get('G'), 'minor', row.get('D'))]:
            if not node_id or not name:
                raise ValueError('산업 분류 마스터에 ID 또는 이름이 없습니다.')
            item = {'id': node_id, 'name': name, 'level': level, 'parent_id': parent}
            if level == 'minor':
                item.update(definition=row.get('H', ''), include=row.get('I', ''), exclude=row.get('J', ''))
            if node_id in nodes and nodes[node_id] != item:
                raise ValueError('중복·불일치 산업 ID: ' + node_id)
            nodes[node_id] = item
    for node in nodes.values():
        parent = node['parent_id']
        if parent and (parent not in nodes or LEVELS[nodes[parent]['level']] != LEVELS[node['level']] - 1):
            raise ValueError('올바르지 않은 산업 부모 분류: ' + node['id'])
    assignments = {}
    for row in sheets['기업전체']:
        if row['source_row'] < 7:
            continue
        country, symbol = row.get('B', '').upper(), row.get('D', '').strip().upper()
        if country not in {'KR', 'US'} or not symbol:
            raise ValueError('기업의 국가 또는 코드가 없습니다.')
        key = country + ':' + symbol
        if key in assignments:
            raise ValueError('국가·종목코드 중복: ' + key)
        major, middle, minor = _ids(row.get('T')), _ids(row.get('U')), _ids(row.get('V'))
        for level, values in [('major', major), ('middle', middle), ('minor', minor)]:
            for node_id in values:
                if node_id not in nodes or nodes[node_id]['level'] != level:
                    raise ValueError('기업의 산업 ID를 확인해 주세요: ' + key + ' / ' + node_id)
        if any(nodes[i]['parent_id'] not in middle for i in minor) or any(nodes[i]['parent_id'] not in major for i in middle):
            raise ValueError('기업의 산업 경로가 마스터와 다릅니다: ' + key)
        assignments[key] = {
            'country': country, 'symbol': symbol, 'name': row.get('C', symbol), 'market': row.get('E', ''),
            'node_ids': _terminal_ids(major + middle + minor, nodes),
            'source_status': row.get('O', ''), 'source_method': row.get('P', ''),
            'source_url': row.get('AD', ''), 'review_reasons': _ids(row.get('AB')),
            'source_row': row['source_row'], 'source_path': row.get('J', ''), 'source_depth': row.get('I', ''),
            'company_id': row.get('R', ''), 'original_company_id': row.get('S', ''),
            'approved_business_ids': _ids(row.get('Z')), 'business_review': row.get('AA', ''),
        }
    date_text = next((r.get('B', '') for r in sheets['기업전체'] if r['source_row'] == 3), '')
    date_match = re.search(r'\d{4}-\d{2}-\d{2}', date_text)
    metadata = {'file': source.name, 'source_date': date_match.group(0) if date_match else '',
                'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'imported_at': datetime.now().isoformat(timespec='seconds'),
                'company_rows': len(assignments), 'counts': dict(Counter(n['level'] for n in nodes.values()))}
    with _LOCK:
        for filename, data in [('industry_taxonomy.json', {'version': 1, 'source': metadata, 'nodes': list(nodes.values())}),
                               ('industry_assignments.json', {'version': 1, 'source': metadata, 'companies': assignments})]:
            path = data_dir / filename
            if path.exists():
                backup = base / 'classification_reports' / ('kuim-backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
                backup.mkdir(parents=True, exist_ok=True)
                (backup / filename).write_bytes(path.read_bytes())
            _write_json(path, data)
    return metadata


def ensure_dataset(base_dir):
    base = Path(base_dir)
    source = base / 'KUIM_전체결과표.xlsx'
    taxonomy, assignments = base / 'data' / 'industry_taxonomy.json', base / 'data' / 'industry_assignments.json'
    if source.exists():
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if not taxonomy.exists() or not assignments.exists() or any(_read_json(path)['source']['sha256'] != digest for path in (taxonomy, assignments)):
            return import_workbook(base_dir, source)
    return _read_json(taxonomy)['source']


class IndustryStore:
    def __init__(self, base_dir):
        self.base = Path(base_dir)
        self.data = self.base / 'data'
        if not (self.data / 'industry_taxonomy.json').exists() or not (self.data / 'industry_assignments.json').exists():
            ensure_dataset(base_dir)
        self.taxonomy = copy.deepcopy(_read_json(self.data / 'industry_taxonomy.json'))
        extensions = _read_json(self.data / 'industry_taxonomy_extensions.json', {'nodes': []})
        existing_nodes = {n['id']: n for n in self.taxonomy['nodes']}
        for node in extensions['nodes']:
            if node['id'] in existing_nodes or node.get('level') not in LEVELS:
                raise ValueError('추가 산업 ID·단계를 확인해 주세요: ' + node['id'])
            parent = existing_nodes.get(node.get('parent_id'))
            if not parent or LEVELS[parent['level']] != LEVELS[node['level']] - 1:
                raise ValueError('추가 산업의 부모 분류를 확인해 주세요: ' + node['id'])
            self.taxonomy['nodes'].append(node)
            existing_nodes[node['id']] = node
        self.taxonomy['source']['original_counts'] = self.taxonomy['source']['counts'].copy()
        self.taxonomy['source']['extension_count'] = len(extensions['nodes'])
        self.taxonomy['source']['counts'] = dict(Counter(n['level'] for n in self.taxonomy['nodes']))
        self.assignments = _read_json(self.data / 'industry_assignments.json')['companies']
        self.nodes = {n['id']: n for n in self.taxonomy['nodes']}
        self.overrides = _read_json(self.base / 'industry_overrides.json', {'version': 1, 'companies': {}})['companies']

    def paths(self, node_ids):
        paths = []
        for node_id in _terminal_ids(node_ids, self.nodes):
            path = {'node_id': node_id, 'major': None, 'middle': None, 'minor': None}
            current = node_id
            while current:
                node = self.nodes[current]
                path[node['level']] = {'id': node['id'], 'name': node['name']}
                current = node['parent_id']
            path['label'] = ' › '.join(path[level]['name'] for level in LEVELS if path[level])
            path['depth'] = self.nodes[node_id]['level']
            paths.append(path)
        return paths

    def classify(self, country, symbol):
        key = str(country).upper() + ':' + str(symbol).strip().upper()
        original = self.assignments.get(key)
        override = self.overrides.get(key)
        item = copy.deepcopy(original) if original else {'country': str(country).upper(), 'symbol': str(symbol).upper(),
            'name': str(symbol).upper(), 'market': '', 'node_ids': [], 'source_status': '', 'source_method': '',
            'source_url': '', 'review_reasons': [], 'source_row': None, 'source_path': '', 'company_id': ''}
        if override is not None:
            item['node_ids'] = override['node_ids']
            item['manual_note'] = override.get('note', '')
            item['updated_at'] = override.get('updated_at', '')
            item['review_required'] = override.get('review_required', False)
        if item['source_status'] == 'EXCLUDED_CLOSED_END_FUND':
            status = 'excluded'
        elif override is not None:
            status = 'review' if override.get('review_required', False) else 'manual'
        elif not item['node_ids']:
            status = 'unclassified'
        elif item['source_status'] == 'BUSINESS_APPROVED_INDEX_UNREVIEWED':
            status = 'approved'
        elif item['source_status'] == 'BUSINESS_EVIDENCE_REVIEW_INDEX_UNREVIEWED':
            status = 'review'
        else:
            status = 'draft'
        item.update(paths=self.paths(item['node_ids']), status=status, status_label=REVIEW_LABELS[status],
                    manual_override=override is not None, in_source=original is not None,
                    source_date=self.taxonomy['source']['source_date'],
                    review_reason_labels=[REASON_LABELS.get(r, r) for r in item['review_reasons']])
        item['path_label'] = ' / '.join(p['label'] for p in item['paths'])
        for level in LEVELS:
            values = list({p[level]['id']: p[level] for p in item['paths'] if p[level]}.values())
            item[level + '_ids'] = [n['id'] for n in values]
            item[level + '_label'] = ' · '.join(n['name'] for n in values)
        item['depth'] = max((LEVELS[p['depth']] for p in item['paths']), default=0)
        item['has_partial_path'] = any(p['depth'] != 'minor' for p in item['paths'])
        return item

    def catalogue(self):
        return {'version': self.taxonomy['version'], 'source': self.taxonomy['source'], 'nodes': self.taxonomy['nodes'],
                'statuses': REVIEW_LABELS}

    def list_rows(self, store, query='', country='', status='', major='', middle='', minor='', offset=0, limit=100):
        if country and country not in {'KR', 'US'}:
            raise ValueError('지원하지 않는 국가입니다.')
        if status and status not in REVIEW_LABELS and status != 'partial':
            raise ValueError('지원하지 않는 검토 상태입니다.')
        filters = {'major': major, 'middle': middle, 'minor': minor}
        for level, value in filters.items():
            if value and (value not in self.nodes or self.nodes[value]['level'] != level):
                raise ValueError('올바르지 않은 산업 필터입니다.')
        with store.connect() as db:
            stocks = {(row['country'] + ':' + row['symbol']): dict(row) for row in db.execute("SELECT symbol,country,name,market FROM instruments WHERE asset_type='STOCK'")}
        exclusions = load_exclusions(self.base)['instruments']
        keys = sorted(set(stocks) | set(self.assignments) | set(self.overrides))
        items = []
        totals = Counter()
        country_counts = Counter()
        needle = str(query).strip().casefold()[:160]
        for key in keys:
            row_country, symbol = key.split(':', 1)
            if country and row_country != country:
                continue
            item = self.classify(row_country, symbol)
            if exclusion_reason(self.base, row_country, symbol, item['name'], records=exclusions):
                continue
            if key in stocks:
                item['catalogue_name'] = stocks[key]['name']
                catalogue_market = stocks[key]['market']
                if catalogue_market not in {'KRX', 'US'} or not item.get('market'):
                    item['market'] = catalogue_market
                if not item['in_source']:
                    item['name'] = stocks[key]['name']
            item['in_catalogue'] = key in stocks
            totals[item['status']] += 1
            country_counts[row_country] += 1
            if status == 'partial' and not item['has_partial_path']:
                continue
            if status in REVIEW_LABELS and item['status'] != status:
                continue
            if any(filters.values()) and not any(all(not value or (path[level] and path[level]['id'] == value) for level, value in filters.items()) for path in item['paths']):
                continue
            if needle and needle not in ' '.join([item['symbol'], item['name'], item.get('catalogue_name', ''), item['path_label']]).casefold():
                continue
            items.append(item)
        offset, limit = max(0, int(offset)), min(200, max(1, int(limit)))
        if offset >= len(items):
            offset = max(0, ((len(items) - 1) // limit) * limit) if items else 0
        return {'items': items[offset:offset + limit], 'total': sum(totals.values()), 'filtered': len(items),
                'offset': offset, 'limit': limit, 'counts': dict(totals), 'countries': dict(country_counts),
                'source': self.taxonomy['source']}

    def save(self, country, symbol, node_ids, note='', reset=False, store=None, review_required=False):
        country, symbol = str(country).upper(), str(symbol).strip().upper()
        if country not in {'KR', 'US'} or not re.fullmatch(r'[A-Z0-9][A-Z0-9./_-]{0,24}', symbol):
            raise ValueError('국가·종목코드를 확인해 주세요.')
        key = country + ':' + symbol
        if exclusion_reason(self.base, country, symbol, self.assignments.get(key, {}).get('name', '')):
            raise ValueError('우선주·스팩은 기업 검토 및 시세 수집 대상에서 제외됩니다.')
        if key not in self.assignments and key not in self.overrides:
            with store.connect() as db:
                if not db.execute("SELECT 1 FROM instruments WHERE symbol=? AND country=? AND asset_type='STOCK'", (symbol, country)).fetchone():
                    raise ValueError('등록된 기업을 선택해 주세요.')
        if self.classify(country, symbol)['status'] == 'excluded':
            raise ValueError('원본에서 분류 제외한 증권입니다.')
        if not isinstance(node_ids, list) or len(node_ids) > 30 or any(not isinstance(i, str) or i not in self.nodes for i in node_ids):
            raise ValueError('분류 마스터에서 산업을 선택해 주세요.')
        if not isinstance(review_required, bool):
            raise ValueError('추가 검토 상태를 확인해 주세요.')
        if not isinstance(note, str) or len(note) > 2000:
            raise ValueError('검토 메모는 2,000자 이내로 입력해 주세요.')
        path = self.base / 'industry_overrides.json'
        with _LOCK:
            data = copy.deepcopy(_read_json(path, {'version': 1, 'companies': {}}))
            if reset:
                data['companies'].pop(key, None)
            else:
                data['companies'][key] = {'node_ids': _terminal_ids(list(dict.fromkeys(node_ids)), self.nodes),
                    'note': note.strip(), 'review_required': review_required,
                    'updated_at': datetime.now().isoformat(timespec='seconds')}
            _write_json(path, data)
        return IndustryStore(self.base).classify(country, symbol)
