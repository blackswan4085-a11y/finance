"""Evidence-based US sector assignments. Personal overrides live in sectors.json."""
from __future__ import annotations
import csv
import hashlib
import json
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime

SECTOR_LABELS = {
    'Technology': '정보기술', 'Information Technology': '정보기술',
    'Telecommunications': '커뮤니케이션', 'Communication Services': '커뮤니케이션', 'Communication':'커뮤니케이션',
    'Health Care': '헬스케어', 'Healthcare': '헬스케어',
    'Finance': '금융', 'Financials': '금융', 'Real Estate': '부동산',
    'Consumer Discretionary': '경기소비재', 'Consumer Staples': '필수소비재',
    'Industrials': '산업재', 'Basic Materials': '소재', 'Materials': '소재',
    'Energy': '에너지', 'Utilities': '유틸리티',
}
# Nasdaq's legacy industries do not use the same boundaries as sector ETFs.
# These explicit translations are application rules, not claims of official GICS.
INDUSTRIES = {}
GROUPS = {
    '반도체': ['Semiconductors'],
    '소재': ['Aluminum','Agricultural Chemicals','Building Materials','Containers/Packaging',
        'Forest Products','Major Chemicals','Metal Mining','Mining & Quarrying of Nonmetallic Minerals (No Fuels)',
        'Other Metals and Minerals','Paints/Coatings','Paper','Plastic Products','Precious Metals',
        'Specialty Chemicals','Steel/Iron Ore'],
    '에너지': ['Coal Mining','Integrated oil Companies','Oil & Gas Production','Oil Refining/Marketing',
        'Oil and Gas Field Machinery','Oil/Gas Transmission','Oilfield Services/Equipment'],
    '유틸리티': ['Electric Utilities: Central','Power Generation','Water Supply'],
    '헬스케어': ['Biotechnology: Biological Products (No Diagnostic Substances)',
        'Biotechnology: Commercial Physical & Biological Resarch',
        'Biotechnology: Electromedical & Electrotherapeutic Apparatus',
        'Biotechnology: In Vitro & In Vivo Diagnostic Substances',
        'Biotechnology: Laboratory Analytical Instruments','Biotechnology: Pharmaceutical Preparations',
        'Hospital/Nursing Management','Managed Health Care','Medical Electronics','Medical Specialities',
        'Medical/Dental Instruments','Medical/Nursing Services','Medicinal Chemicals and Botanical Products',
        'Misc Health and Biotechnology Services','Ophthalmic Goods','Other Pharmaceuticals','Pharmaceuticals and Biotechnology'],
    '커뮤니케이션': ['Advertising','Books','Broadcasting','Cable & Other Pay Television Services',
        'Movies/Entertainment','Newspapers/Magazines','Publishing'],
    '필수소비재': ['Beverages (Production/Distribution)','Farming/Seeds/Milling','Food Chains','Food Distributors',
        'Meat/Poultry/Fish','Package Goods/Cosmetics','Packaged Foods','Specialty Foods','Tobacco'],
    '경기소비재': ['Apparel','Auto & Home Supply Stores','Auto Manufacturing','Auto Parts:O.E.M.',
        'Automotive Aftermarket','Catalog/Specialty Distribution','Clothing/Shoe/Accessory Stores',
        'Consumer Electronics/Video Chains','Department/Specialty Retail Stores','Garments and Clothing',
        'Home Furnishings','Homebuilding','Hotels/Resorts','Motor Vehicles','Other Specialty Stores',
        'RETAIL: Building Materials','Recreational Games/Products/Toys','Restaurants',
        'Retail-Auto Dealers and Gas Stations','Retail: Computer Software & Peripheral Equipment',
        'Services-Misc. Amusement & Recreation','Shoe Manufacturing','Textiles','Tools/Hardware'],
    '산업재': ['Aerospace','Air Freight/Delivery Services','Building Products','Construction/Ag Equipment/Trucks',
        'Diversified Commercial Services','Engineering & Construction','Environmental Services','Fluid Controls',
        'General Bldg Contractors - Nonresidential Bldgs','Integrated Freight & Logistics','Marine Transportation',
        'Metal Fabrications','Military/Government/Technical','Misc Corporate Leasing Services',
        'Ordnance And Accessories','Other Transportation','Pollution Control Equipment','Railroads',
        'Transportation Services','Trucking Freight/Courier Services','Water Sewer Pipeline Comm & Power Line Construction'],
    '정보기술': ['Computer Communications Equipment','Computer Manufacturing','Computer peripheral equipment',
        'Electronic Components','Electronics Distribution'],
    '부동산': ['Building operators','Real Estate'],
}
for label, names in GROUPS.items():
    INDUSTRIES.update({name: label for name in names})
AMBIGUOUS = {'Business Services','Other Consumer Services','Professional Services','Industrial Specialties',
    'Telecommunications Equipment','Consumer Electronics/Appliances','Multi-Sector Companies','Miscellaneous',
    'EDP Services','Computer Software: Programming Data Processing','Consumer Specialties','Durable Goods','Precision Instruments','Professional and commerical equipment',
    'Wholesale Distributors','Radio And Television Broadcasting And Communications Equipment'}
SPECIAL = re.compile(r'\b(warrants?|rights?|preferred|preference|debentures?|notes|bonds)\b|\bpref\s+shs\b', re.I)
SPAC = re.compile(r'\bacquisition\s+(?:corp|corporation)|\bblank\s+check|\bSPAC\b', re.I)
FUND = re.compile(r'\bfund\b|\bETF\b|\bexchange[ -]traded\b', re.I)


def init_table(store):
    with store.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS sector_classifications (
            symbol TEXT NOT NULL, country TEXT NOT NULL CHECK(country='US'),
            sector TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('mapped','review')),
            raw_sector TEXT NOT NULL, industry TEXT NOT NULL, source TEXT NOT NULL,
            source_url TEXT NOT NULL, source_symbol TEXT NOT NULL, source_name TEXT NOT NULL,
            method TEXT NOT NULL, reason TEXT NOT NULL, classified_at TEXT NOT NULL,
            source_hash TEXT NOT NULL, PRIMARY KEY(symbol,country))''')


def _read_csv(path, required):
    with open(path, encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('분류 원본의 필수 컬럼이 없습니다: ' + path)
        return list(reader)


def _key(value):
    # Only equivalent class-share separators; no suffix stripping or fuzzy match.
    value = str(value).strip().upper()
    if re.fullmatch(r'[A-Z]+ [AB]',value):
        value = value.replace(' ','.')
    return value.replace('/', '.').replace('-', '.')


def classify_us(base_dir, store, manifest_path):
    from .sectors import load_manual_sectors
    from .sector_etfs import load_sector_etfs
    manifest_path = os.path.abspath(manifest_path)
    with open(manifest_path, encoding='utf-8') as stream:
        manifest = json.load(stream)
    root = os.path.dirname(manifest_path)
    source_files = {k: os.path.join(root, manifest[k]['file']) for k in ('nasdaq','sp500','ipay','iwv','smh') if k in manifest}
    if 'nasdaq' not in source_files:
        raise ValueError('Nasdaq 원본이 필요합니다.')
    raw_rows = _read_csv(source_files['nasdaq'], {'Symbol','Name','Sector','Industry'})
    if len(raw_rows) < 1000:
        raise ValueError('전체 미국 종목 원본이 아닙니다. 필터 없는 Nasdaq CSV를 사용해 주세요.')
    listings = {}
    for raw in raw_rows:
        symbol = _key(raw['Symbol'])
        if symbol in listings:
            raise ValueError('중복 원본 종목 코드: ' + symbol)
        listings[symbol] = {k: str(v or '').strip() for k,v in raw.items()}
    gics = {}
    if 'sp500' in source_files:
        with open(source_files['sp500'], encoding='utf-8') as stream:
            for row in json.load(stream):
                if not all(k in row for k in ('symbol','sector','industry')):
                    raise ValueError('S&P500 보조 분류 형식을 확인해 주세요.')
                gics[_key(row['symbol'])] = row
    payments = set()
    if 'ipay' in source_files:
        for row in _read_csv(source_files['ipay'], {'Holding Ticker','Fund Ticker'}):
            if not row.get('Holding Ticker'):
                continue
            if row['Fund Ticker'] != 'IPAY':
                raise ValueError('IPAY 보유목록이 아닙니다.')
            if not str(row.get('CUSIP','')).lower().startswith('cash') and row['Holding Ticker'] != 'AGPXX':
                payments.add(_key(row['Holding Ticker']))
    iwv = {}
    if 'iwv' in source_files:
        with open(source_files['iwv'],encoding='utf-8-sig',newline='') as stream:
            lines = stream.readlines()
        start = next((n for n,line in enumerate(lines) if line.startswith('Ticker,Name,Sector,Asset Class,')),None)
        if start is None:
            raise ValueError('iShares 종목별 섹터 헤더를 찾지 못했습니다.')
        for evidence in csv.DictReader(lines[start:]):
            if evidence.get('Asset Class') != 'Equity' or evidence.get('Exchange') not in ('NASDAQ','NYSE','NYSE Arca','NYSE MKT','Cboe BZX'):
                continue
            if evidence['Sector'] in SECTOR_LABELS:
                iwv[_key(evidence['Ticker'])] = evidence
        if len(iwv) < 1000:
            raise ValueError('iShares 전체 보유목록이 아닙니다.')
    semiconductors = set()
    if 'smh' in source_files:
        with open(source_files['smh'],encoding='utf-8') as stream:
            semiconductors = {_key(r['symbol']) for r in json.load(stream)}
    digest = hashlib.sha256()
    for key, path in sorted(source_files.items()):
        digest.update(key.encode())
        with open(path,'rb') as stream:
            digest.update(stream.read())
    digest.update(json.dumps(manifest,sort_keys=True).encode())
    source_hash = digest.hexdigest()
    manual = load_manual_sectors(base_dir)
    settings = load_sector_etfs(base_dir)
    now = datetime.now().isoformat(timespec='seconds')
    with store.connect() as db:
        stocks = [dict(row) for row in db.execute("SELECT * FROM instruments WHERE country='US' AND asset_type='STOCK' ORDER BY symbol")]
    results = []
    for stock in stocks:
        symbol = stock['symbol']
        key = _key(symbol)
        raw = listings.get(key)
        row = {'symbol':symbol, 'country':'US', 'sector':'', 'status':'review',
               'raw_sector': raw['Sector'] if raw else '', 'industry':raw['Industry'] if raw else '',
               'source':'Nasdaq screener', 'source_url':manifest['nasdaq']['url'],
               'source_symbol':raw['Symbol'] if raw else '', 'source_name':raw['Name'] if raw else stock['name'], 'method':'', 'reason':'',
               'classified_at':now, 'source_hash':source_hash}
        name = raw['Name'] if raw else iwv.get(key,{}).get('Name',stock['name'])
        row['source_name'] = name
        industry = row['industry']
        label, method, reason = '', '', ''
        if SPECIAL.search(name):
            reason = '워런트·권리·우선주·채권 등 특수 증권. 보통주 업종 비교에서 보류'
        elif SPAC.search(name) or industry == 'Blank Checks':
            reason = 'SPAC/인수목적회사. 사업 업종 미확정 또는 티커 재사용 가능성'
        elif FUND.search(name) or industry == 'Trusts Except Educational Religious and Charitable':
            reason = '펀드·투자신탁 성격의 항목. 일반 기업 섹터 연결에서 보류'
        elif not raw and key not in iwv:
            reason = '현재 Nasdaq 전체 목록에서 코드를 확인하지 못함. 상장 상태·코드 검토 필요'
        elif key in payments:
            label, method = '결제', 'ETF 보유종목'
            row.update(source='Amplify IPAY holdings',source_url=manifest['ipay']['url'])
            reason = 'IPAY의 미국 상장 보유종목과 코드 일치. 결제 테마 비교용 연결'
        elif key in semiconductors:
            label, method = '반도체', 'ETF 보유종목'
            row.update(source='VanEck SMH holdings',source_url=manifest['smh']['url'])
            reason = 'SMH 공식 미국 상장 보유종목과 코드 일치. 반도체·장비·설계 테마 연결'
        elif key in iwv:
            evidence = iwv[key]
            label, method = SECTOR_LABELS[evidence['Sector']], '운용사 섹터 분류'
            if label == '정보기술' and (industry == 'Semiconductors' or gics.get(key,{}).get('industry') in ('Semiconductors','Semiconductor Materials & Equipment')):
                label = '반도체'
            row.update(source='BlackRock/iShares IWV holdings',source_url=manifest['iwv']['url'],
                       raw_sector=evidence['Sector'],source_symbol=evidence['Ticker'])
            reason = 'iShares 공식 보유종목의 섹터와 코드 일치. 반도체 업종 근거가 있으면 SMH 그룹으로 분리'
        elif key in gics:
            evidence = gics[key]
            label = '반도체' if evidence['industry'] in ('Semiconductors','Semiconductor Materials & Equipment') else SECTOR_LABELS.get(evidence['sector'],'')
            method = 'GICS 보조 분류'
            row.update(source='Wikipedia S&P500 GICS (secondary)', source_url=manifest['sp500']['url'],
                       raw_sector=evidence['sector'], industry=evidence['industry'])
            reason = 'S&P500 종목별 GICS 보조 표와 코드 일치; 반도체 업종은 SMH 그룹으로 분리'
        elif industry in AMBIGUOUS:
            reason = '하나의 Nasdaq 업종에 여러 ETF 섹터가 섞임. 기업별 확인 필요'
        elif industry == 'Real Estate Investment Trusts':
            if re.search(r'\bmortgage\b|\bcredit\b',name,re.I):
                reason = '모기지·신용 REIT는 일반 부동산 ETF와 성격이 달라 검토 필요'
            else:
                label,method,reason = '부동산','업종 변환','Nasdaq REIT 업종을 부동산 그룹으로 연결; 모기지 REIT 여부 추가 검토 가능'
        elif industry in INDUSTRIES:
            label,method,reason = INDUSTRIES[industry],'업종 변환','Nasdaq 업종을 앱의 ETF 섹터 기준으로 변환: '+industry
        elif industry in ('Industrial Machinery/Components','Electrical Products'):
            if row['raw_sector'] == 'Industrials':
                label,method,reason = '산업재','업종 변환','Nasdaq 업종과 산업재 섹터가 일치'
            else:
                reason = '기계·전기제품 업종이 원본 섹터와 불일치. 기업별 확인 필요'
        elif industry == 'Natural Gas Distribution':
            if row['raw_sector'] == 'Utilities':
                label,method,reason = '유틸리티','업종 변환','가스 공급 유틸리티 업종과 섹터 일치'
            else:
                reason = '가스 생산·운송·공급의 섹터 구분 확인 필요'
        elif row['raw_sector'] in SECTOR_LABELS and industry:
            label,method,reason = SECTOR_LABELS[row['raw_sector']],'Nasdaq 섹터','Nasdaq 공개 섹터를 대응. ETF 편입 여부나 공식 GICS와 일치한다는 의미는 아님'
        else:
            reason = '섹터·업종 분류가 없거나 지원하지 않는 분류'
        row.update(sector=label,status='mapped' if label else 'review',method=method,reason=reason)
        effective = manual.get(symbol,label)
        row.update(name=name,effective_sector=effective,manual_override=symbol in manual,
                   etf=settings['mapping'].get(effective,''))
        results.append(row)
    init_table(store)
    columns = ['symbol','country','sector','status','raw_sector','industry','source','source_url',
               'source_symbol','source_name','method','reason','classified_at','source_hash']
    with store.connect() as db:
        db.executemany('INSERT OR REPLACE INTO sector_classifications ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',
                       [tuple(row[k] for k in columns) for row in results])
    summary = {'classified_at':now,'scope':'US STOCK only','total':len(results),
               'mapped':sum(r['status']=='mapped' for r in results),
               'review':sum(r['status']=='review' for r in results),
               'manual_overrides':sum(r['manual_override'] for r in results),
               'effective_mapped':sum(bool(r['etf']) for r in results),
               'by_sector':dict(Counter(r['effective_sector'] for r in results if r['etf'])),
               'by_method':dict(Counter(r['method'] for r in results if r['sector'])),
               'sources':manifest,'source_hash':source_hash}
    directory = os.path.join(base_dir,'classification_reports')
    os.makedirs(directory,exist_ok=True)
    for filename, data in [('us-sector-summary.json',summary),('us-sector-results.json',results)]:
        path=os.path.join(directory,filename)
        with open(path+'.tmp','w',encoding='utf-8') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2)
        os.replace(path+'.tmp',path)
    return summary


def automatic_sectors(base_dir):
    path=os.path.join(base_dir,'instruments.sqlite3')
    if not os.path.exists(path):
        return {}
    with sqlite3.connect(path,timeout=15) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='sector_classifications'").fetchone():
            return {}
        return dict(db.execute("SELECT c.symbol,c.sector FROM sector_classifications c JOIN instruments i ON i.symbol=c.symbol AND i.country=c.country WHERE c.country='US' AND c.status='mapped' AND i.asset_type='STOCK'"))


def classification_rows(base_dir, store, query='', status='', offset=0, limit=100):
    from .sectors import load_manual_sectors
    from .sector_etfs import load_sector_etfs
    init_table(store)
    manual=load_manual_sectors(base_dir)
    settings=load_sector_etfs(base_dir)
    with store.connect() as db:
        rows=[dict(r) for r in db.execute("SELECT c.*,i.name FROM sector_classifications c JOIN instruments i ON i.symbol=c.symbol AND i.country=c.country WHERE c.country='US' AND i.asset_type='STOCK' ORDER BY c.symbol")]
    totals=Counter()
    selected=[]
    needle=str(query).strip().casefold()[:120]
    for row in rows:
        row['manual_override']=row['symbol'] in manual
        row['effective_sector']=manual.get(row['symbol'],row['sector'])
        row['etf']=settings['mapping'].get(row['effective_sector'],'')
        row['effective_status']='manual' if row['manual_override'] else row['status']
        totals[row['effective_status']]+=1
        if status and row['effective_status'] != status:
            continue
        if needle and needle not in ' '.join(str(row.get(k,'')) for k in ('symbol','name','effective_sector','industry','etf')).casefold():
            continue
        selected.append(row)
    return {'counts':dict(totals),'total':len(rows),'filtered':len(selected),'offset':offset,
            'items':selected[offset:offset+limit], 'classified_at':max((r['classified_at'] for r in rows),default='')}


def classification_context(base_dir,store,symbol):
    init_table(store)
    with store.connect() as db:
        row=db.execute("SELECT * FROM sector_classifications WHERE symbol=? AND country='US'",(symbol,)).fetchone()
    return dict(row) if row else None
