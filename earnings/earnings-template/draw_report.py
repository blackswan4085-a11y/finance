"""Deterministic PNG earnings report. Layout is fixed in logical pixels; 2x export."""
import json, sys, math, hashlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, __version__ as PIL_VERSION
W,H,S=1440,1940,2
C={'bg':'#F7F6F2','ink':'#1A1A18','muted':'#73736C','border':'#D8D6CE','blue':'#1764AC','green':'#16754F','amber':'#A56813'}
ROOT=Path(__file__).resolve().parent
FONTS=ROOT/'.runtime'/'fonts'
fonts={}
def font(size,bold=False):
    key=(size,bold)
    if key not in fonts: fonts[key]=ImageFont.truetype(str(FONTS/('bold.ttf' if bold else 'regular.ttf')),int(size*S))
    return fonts[key]
def measure(text,size=18,bold=False): return draw.textlength(str(text).replace('−','-'),font=font(size,bold))/S
def wrapped_text(value,size=18,bold=False,width=None):
    value=str(value).replace('−','-')
    if width is None: chunks=[value]
    else:
        chunks=[]
        for paragraph in value.split('\n'):
            current=''
            for token in paragraph.split():
                candidate=(current+' '+token).strip()
                if measure(candidate,size,bold)<=width:
                    current=candidate
                    continue
                if current:chunks.append(current);current=''
                if measure(token,size,bold)<=width:current=token
                else:
                    for c in token:
                        if measure(current+c,size,bold)>width:
                            if not current:raise ValueError('문자 폭 초과: '+value)
                            chunks.append(current);current=c
                        else:current+=c
            chunks.append(current)
    return chunks

def text(x,y,value,size=18,fill='ink',bold=False,width=None,lines=1):
    chunks=wrapped_text(value,size,bold,width)
    if len(chunks)>lines: raise ValueError('문장 영역 초과: '+str(value)+' / 허용 '+str(lines)+'줄')
    for i,line in enumerate(chunks): draw.text((int(x*S),int((y+i*size*1.5)*S)),line,font=font(size,bold),fill=C.get(fill,fill),stroke_width=0)
def box(x,y,w,h,fill='white',outline=True,r=10):
    draw.rounded_rectangle((int(x*S),int(y*S),int((x+w)*S),int((y+h)*S)),radius=r*S,fill=C.get(fill,fill),outline=C['border'] if outline else None,width=S)
def line(x,y,x2,y2,fill='border',width=1):
    draw.line((int(x*S),int(y*S),int(x2*S),int(y2*S)),fill=C.get(fill,fill),width=width*S)
def centered(x,y,v,size=18,fill='ink',bold=False): text(x-measure(v,size,bold)/2,y,v,size,fill,bold)
def number(v,p=2): return f'{v:,.{p}f}'
def valid(v): return isinstance(v,(int,float)) and not isinstance(v,bool)
def signed(v,p=1,unit='%'):
    if v is None:return '미제공'
    if isinstance(v,str): return v
    return ('+' if v>0 else '−' if v<0 else '')+number(abs(v),p)+unit
def fmt(v,unit='money',delta=False):
    if v is None:return '미제공'
    sg=('+' if v>0 else '−' if v<0 else '') if delta else ('−' if v<0 else '')
    a=abs(v)
    if unit=='money':return sg+SYM+(number(a,0 if a%1==0 else 1)+'M' if 0<a<1000 else number(a/1000)+'B')
    if unit=='money_trillion':return sg+SYM+number(a,1)+'T'
    if unit=='count_billion':return sg+number(a,1)+'B'
    if unit=='count_million':return sg+number(a,0)+'M'
    if unit=='eps':return sg+SYM+number(a)
    if unit=='percent':return sg+number(a,1)+('%p' if delta else '%')
    return sg+number(a,0)+'개'
def growth(v,p):
    if v is None or p is None:return None
    if p<0 and v>0:return '흑자전환'
    if p>0 and v<0:return '적자전환'
    if p<=0:return '산출 불가'
    return (v/p-1)*100
def source(sid):return next((s['label'] for s in D['sources'] if s['id']==sid),'미제공')
def section(y,no,title):
    box(40,y,34,34,fill='#62625A',outline=False,r=17)
    centered(57,y+4,no,18,'white',True)
    text(86,y,title,25,bold=True)
def month_period():
    p=D['reportPeriod']
    sy,sm=int(p['start'][:4]),int(p['start'][5:7])
    ey,em=int(p['end'][:4]),int(p['end'][5:7])
    if sy==ey:
        return str(sy)+'년 '+(str(sm)+'월' if sm==em else str(sm)+'–'+str(em)+'월')
    return f'{sy}년 {sm}월–{ey}년 {em}월'
def header():
    text(40,30,'EARNINGS REVIEW / '+('SAMPLE' if D['company']['isSample'] else 'REPORT'),15,'muted')
    name=D['company']['name'];ticker=D['company']['ticker']
    text(40,54,name,50,bold=True,width=1040)
    ticker_x=40+measure(name,50,True)+20
    fy='FY'+str(D['current']['year'])+' Q'+str(D['current']['quarter'])
    if ticker_x+measure(ticker,26,True)>1400:raise ValueError('기업명·티커가 헤더 너비를 초과합니다.')
    text(ticker_x,79,ticker,26,'muted',True)
    fy_w=measure(fy,20,True)+28
    box(40,124,fy_w,31,fill='#EAF1F7',outline=False,r=5)
    text(54,125,fy,20,'blue',True)
    currency={'USD':'미국 달러','EUR':'유로','KRW':'원화','JPY':'일본 엔','GBP':'영국 파운드','CNY':'중국 위안','TWD':'대만 달러'}[D['company']['currency']]
    text(40+fy_w+20,129,month_period()+'  ·  '+currency+'('+D['company']['currency']+')',18,'muted')
    line(40,166,1400,166)
def footer(page,total):
    line(40,H-60,1400,H-60)
    if D['company']['isSample']:text(40,H-46,'가상 기업 · 예시 데이터',12,'muted')
    v=f'{page} / {total}'
    text(1400-measure(v,12),H-46,v,12,'muted')

def market_section(y):
    m=D.get('marketData') or {}
    compact=D.get('presentation',{}).get('profile')=='compact-review-v1'
    section(y,'03','주가 · 밸류에이션')
    currency=m.get('currency') or D['company']['currency']
    symbol={'USD':'$','EUR':'€','KRW':'₩','JPY':'¥','GBP':'£','CNY':'¥','TWD':'NT$'}.get(currency,currency+' ')
    def price(v):return symbol+number(v,0 if currency in ('KRW','JPY') else 2) if valid(v) else '미제공'
    def cap(v):
        if not valid(v):return '미제공'
        return symbol+number(v/1e12)+'T' if v>=1e12 else symbol+number(v/1e9)+'B' if v>=1e9 else symbol+number(v/1e6)+'M'
    stamp=(m.get('asOf') or '미확보').replace('T',' ').replace('+00:00',' UTC')
    if not compact:text(42,y+43,'주가 기준 '+stamp+'  ·  '+currency,14,'muted',width=1356)
    items=[('최근 주가',price(m.get('price'))),('시가총액',cap(m.get('marketCap'))),
           ('PER · 이번 분기 EPS × 4',number(m['per'],1)+'배' if valid(m.get('per')) else '산출 불가')]
    for i,(label,value) in enumerate(items):
        offset=22 if compact else 0
        x=40+i*460;box(x,y+74-offset,440,116)
        text(x+18,y+86-offset,label,18,'muted',True,width=404)
        text(x+18,y+116-offset,value,37,'blue' if i==2 else 'ink',True,width=404)
    annual=m.get('annualizedEPS')
    eps='분기 EPS '+fmt(m.get('quarterEPS'),'eps')+' × 4 = '+fmt(annual,'eps')+' · '+D['company']['basis']
    reason=m.get('perReason') or ('주가 ÷ 연율화 EPS' if valid(m.get('per')) else '주가 자료 미제공')
    if not compact:text(42,y+202,eps+'  /  '+reason,14,'muted',width=1356)
    cy=y+(188 if compact else 258);box(40,cy,1360,264 if compact else 282)
    text(58,cy+14,'최근 1년 주가' if compact else '최근 1년 주가 · 일별 종가',20,bold=True)
    history=m.get('history') or []
    if len(history)<2:
        text(62,cy+120,'주가 시계열 미제공',18,'muted')
        return cy+(290 if compact else 308)
    values=[p['close'] for p in history]
    low,high=min(values),max(values)
    padding=max((high-low)*.12,abs(high)*.02,.01);low-=padding;high+=padding
    left,right,top,bottom=132,1370,cy+65,cy+224
    def point(i,v):return (left+(right-left)*i/(len(values)-1),bottom-(v-low)/(high-low)*(bottom-top))
    for i in range(5):
        value=low+(high-low)*i/4;yy=point(0,value)[1]
        line(left,yy,right,yy,'border')
        text(57,yy-8,number(value,0 if currency in ('KRW','JPY') else 2),13,'muted')
    coordinates=[point(i,v) for i,v in enumerate(values)]
    draw.line([(int(x*S),int(yy*S)) for x,yy in coordinates],fill=C['blue'],width=3*S)
    for i in (0,len(history)//2,len(history)-1):
        xx=coordinates[i][0];label=history[i]['date']
        text(max(58,min(1260,xx-measure(label,13)/2)),cy+238,label,13,'muted')
    if not compact:text(58,cy+263,'최근 봉은 장중 값일 수 있음 · '+m.get('historySource','Yahoo Finance'),11,'muted')
    return cy+(290 if compact else 308)
def metrics():
    section(191,'01','이번 분기 실적')
    labels={'revenue':'매출','operatingIncome':'영업이익','opm':'영업이익률','eps':'EPS · '+D['company']['basis']}
    colors={'revenue':'blue','operatingIncome':'green','opm':'amber','eps':'ink'}
    has_con=False
    height=306 if has_con else 226
    for i,m in enumerate(D['metrics']):
        x=40+i*344;box(x,240,328,height)
        text(x+18,253,labels[m['key']],21,bold=True,width=290)
        u='percent' if m['key']=='opm' else 'eps' if m['key']=='eps' else 'money'
        text(x+18,284,fmt(m['value'],u),48,colors[m['key']],True,width=292)
        v='YoY '+signed(m['yoy'],unit='%p' if u=='percent' else '%')+' · QoQ '+signed(m['qoq'],unit='%p' if u=='percent' else '%')
        text(x+18,350,v,16,colors[m['key']],True,width=292)
        line(x+18,382,x+310,382)
        rows=[('전년 동기',fmt(m['prior'],u)),('직전 분기',fmt(m['previous'],u))]
        if has_con:
            rows.extend([('컨센서스',fmt(m['consensus'],u)),('컨센서스 대비',fmt(m['difference'],u,True)+(' ('+signed(m['surprise'])+')' if valid(m['surprise']) else ''))])
        for j,(a,b) in enumerate(rows):
            yy=393+j*31;size=14 if j==3 else 17
            text(x+18,yy,a,size,'muted')
            text(x+310-measure(b,size,True),yy,b,size,'blue' if j==3 else 'ink',True,width=195)
    return 240+height+44
def nice(v):
    if v<=0:return 1
    p=10**math.floor(math.log10(v))
    return next((x*p for x in [1,2,2.5,5,10] if x*p>=v),10*p)
def chart(x,y,w,h,rows,annual=False):
    box(x,y,w,h)
    text(x+18,y+14,'연간 매출 · 영업이익' if annual else '분기 매출 · 영업이익',20,bold=True)
    box(x+w-205,y+21,13,9,fill='#85B8EC',outline=False,r=0);text(x+w-185,y+14,'매출',13)
    line(x+w-135,y+26,x+w-113,y+26,'green',2);text(x+w-104,y+14,'영업이익',13)
    unit={'USD':'달러','EUR':'유로','KRW':'원','JPY':'엔','GBP':'파운드','CNY':'위안','TWD':'대만 달러'}[D['company']['currency']]
    text(x+49,y+46,'단위: 십억 '+unit,13,'muted',True)
    if not rows: text(x+30,y+130,'자료 미제공',18,'muted');return
    vals=[r[k]/1000 for r in rows for k in ['revenue','operatingIncome'] if r[k] is not None]
    if not vals: text(x+30,y+130,'자료 미제공',18,'muted');return
    lo0=min([0]+vals);hi0=max([0]+vals);step=nice((hi0-lo0)/4)
    lo=math.floor(lo0/step)*step;hi=math.ceil(hi0/step)*step
    if hi==lo:hi=lo+step
    left=x+49;right=x+w-24;top=y+80;bottom=y+h-38
    yp=lambda v:bottom-(v-lo)/(hi-lo)*(bottom-top)
    xp=lambda i:left+(right-left)*(i+.5)/len(rows)
    ticks=int(round((hi-lo)/step))
    for j in range(ticks+1):
        v=lo+j*step;yy=yp(v);line(left,yy,right,yy,'#E4E6E6')
        label=number(v,0 if step>=1 else 1);text(left-10-measure(label,12),yy-8,label,12,'muted')
    line(left,yp(0),right,yp(0),'#9DA39E')
    prev=None
    for i,r in enumerate(rows):
        xx=xp(i);bw=min(52,(right-left)/len(rows)*.58)
        if r['revenue'] is not None:
            v=r['revenue']/1000;yy=yp(v)
            box(xx-bw/2,min(yy,yp(0)),bw,max(1,abs(yp(0)-yy)),fill='#378ADD' if i==len(rows)-1 else '#85B8EC',outline=False,r=2)
            centered(xx,yy-23 if v>=0 else yy+3,number(v),13,'blue',True)
        v=r['operatingIncome']
        if v is not None:
            point=(xx,yp(v/1000))
            if prev:line(*prev,*point,'green',3)
            prev=point
        else: prev=None
        label='FY'+str(r['year']) if annual else 'FY'+str(r['year'])[2:]+'Q'+str(r['quarter'])
        centered(xx,bottom+12,label,12,'muted')
    for i,r in enumerate(rows):
        if r['operatingIncome'] is not None:
            xx=xp(i);yy=yp(r['operatingIncome']/1000)
            draw.ellipse((int((xx-4)*S),int((yy-4)*S),int((xx+4)*S),int((yy+4)*S)),fill='white',outline=C['green'],width=2*S)
            centered(xx,yy-23,number(r['operatingIncome']/1000),13,'green',True)
def call_title(continued=False):
    c=D.get('conferenceCall')
    prefix=('FY'+str(c['year'])+' Q'+str(c['quarter'])+' ') if c else ''
    return prefix+'컨콜 주요 수치'+(' · 계속' if continued else '')
def drivers(items,y):
    if not items:return y
    if len(items)>3:raise ValueError('기본 사업 지표는 최대 3개입니다.')
    box(40,y,1360,68,fill='#EAF1F7',outline=False)
    for i,m in enumerate(items):
        x=60+i*453
        text(x,y+10,m['label'],16,bold=True,width=250)
        amount=signed(m['value']) if m['unit']=='percent' else fmt(m['value'],m['unit'])
        text(x+412-measure(amount,27,True),y+15,amount,27,'blue',True)
        text(x,y+37,m.get('context',''),13,'muted',width=290)
        if i<2:line(x+430,y+14,x+430,y+54,'#CCD8E2')
    return y+80

def call_cards(items):
    result=[]
    width=(1360-24)/3-40
    for item in items:
        body=wrapped_text(' '.join(item['details']),18,width=width)
        for offset in range(0,len(body),2):
            card={**item,'details':['\n'.join(body[offset:offset+2])]}
            if offset:card['label']=item['label']+' · 계속'
            result.append(card)
    return result

def calls(items,y=982,rowh=196):
    w=(1360-24)/3
    body_lines=[max(1,len(wrapped_text(' '.join(m['details']),18,width=w-40))) for m in items]
    row_heights=[max(rowh,124+max(body_lines[i:i+3])*27+18) for i in range(0,len(items),3)]
    row_tops=[]
    bottom=y
    for height in row_heights:
        row_tops.append(bottom)
        bottom+=height+12
    for i,m in enumerate(items):
        x=40+(i%3)*(w+12);yy=row_tops[i//3]
        box(x,yy,w,row_heights[i//3])
        text(x+20,yy+10,m['label'],19,bold=True,width=w-40)
        amount=fmt(m['value'],m['unit'])
        qualifier={'greaterThan':' 초과','atLeast':' 이상','lessThan':' 미만','atMost':' 이하'}.get(m.get('qualifier'),'')
        amount+=qualifier
        text(x+20,yy+37,amount,40,'blue',True,width=w-40)
        context=m.get('context')
        comp=m['comparison']
        if comp:
            v=comp['label']+' '+fmt(comp['value'],m['unit'])
            if m['value'] is not None and comp['value'] is not None:
                v+='  ·  '+(fmt(m['value']-comp['value'],m['unit'],True) if comp['kind']=='difference' else signed(growth(m['value'],comp['value'])))
            context=v
        if context:text(x+20,yy+91,context,16,width=w-40)
        line(x+20,yy+120,x+w-20,yy+120)
        body=' '.join(m['details'])
        text(x+20,yy+124,body,18,width=w-40,lines=body_lines[i])
    return bottom-12 if items else y
def rangefmt(a,u):
    if a is None:return '미제공'
    if a[0]==a[1]:return fmt(a[0],u)
    if u=='money':return SYM+number(a[0],1)+'–'+number(a[1],1)+'M' if 0<a[0]<=a[1]<1000 else SYM+number(a[0]/1000)+'–'+number(a[1]/1000)+'B'
    if u=='percent':
        p=2 if any(round(v,1)!=v for v in a) else 1
        return number(a[0],p)+'–'+number(a[1],p)+'%'
    return fmt(a[0],u)+'–'+fmt(a[1],u)
def guid_legacy(items,y=1602):
    cols=[255,220,230,170,215,270];heads=['기간 / 지표','직전 가이던스','이번 가이던스','범위 변경','시장 컨센서스','중간값 − 컨센서스']
    def row(yy,values,heading=False):
        x=40
        rh=max(42 if heading else 48,12+max(len(wrapped_text(v,14,width=w-24)) for w,v in zip(cols,values))*21)
        for i,(w,v) in enumerate(zip(cols,values)):
            box(x,yy,w,rh,fill='#EEEDE9' if heading else '#EAF3FC' if i==2 else 'white',r=0)
            size=15 if heading else 17
            bold=heading or i in [2,5]
            if '\n' not in v and measure(v,size,bold)<=w-24:
                tx=x+12 if i==0 else x+(w-measure(v,size,bold))/2
                text(tx,yy+(rh-size)/2-3,v,size,'blue' if not heading and i in [2,5] else 'ink',bold,width=w-24)
            else:
                text(x+12,yy+4,v,14,'blue' if not heading and i in [2,5] else 'ink',bold,width=w-24,lines=len(wrapped_text(v,14,bold,w-24)))
            x+=w
        return rh
    end=y+row(y,heads,True)
    if not items: end+=row(end,['가이던스 미제공','','','','',''])
    for j,g in enumerate(items):
        a,b=g['previous'],g['current'];change='미제공'
        if b:
            if a is None:change='직전 값 미확보'
            else:
                d0=b[0]-a[0];d1=b[1]-a[1]
                change=fmt(d0,g['unit'],True) if abs(d0-d1)<1e-9 else '하단 '+fmt(d0,g['unit'],True)+'\n상단 '+fmt(d1,g['unit'],True)
        delta=(sum(b)/2-g['consensus']) if b and g['consensus'] is not None else None
        label=g['period']+' '+g['metric']
        if g['basis']!=D['company']['basis']:label+='\n'+g['basis']
        end+=row(end,[label,rangefmt(a,g['unit']),g.get('currentText') or rangefmt(b,g['unit']),change,fmt(g['consensus'],g['unit']),fmt(delta,g['unit'],True)])
    text(42,end+10,'범위 변경은 하단·상단 기준. 컨센서스 차이는 이번 가이던스의 중간값 기준.',12,'muted',width=1356)
    return end+40

def guidance_groups(items):
    periods=list(dict.fromkeys(g['period'] for g in items))
    groups={}
    for g in items:
        key=(g['metric'],g['unit'],g['basis'])
        if g['period'] in groups.setdefault(key,{}):raise ValueError('중복 가이던스: '+g['period']+' '+g['metric'])
        groups[key][g['period']]=g
    return periods,groups

def compact_guidance(items):
    return bool(items) and len(guidance_groups(items)[0])<=3 and not any(g['previous'] is not None or g['consensus'] is not None for g in items)

def compact_guidance_layout(items):
    periods,groups=guidance_groups(items)
    widths=[300]+[int(840/len(periods))]*len(periods)+[220]
    rows=[['지표']+periods+['회계 기준']]
    for (metric,unit,basis),group in groups.items():
        rows.append([metric]+[(group[p].get('currentText') or rangefmt(group[p]['current'],unit)) if p in group else '—' for p in periods]+[basis])
    heights=[]
    for j,values in enumerate(rows):
        count=max(len(wrapped_text(value,17,j==0 or 0<i<len(widths)-1,width-24)) for i,(width,value) in enumerate(zip(widths,values)))
        heights.append(max(40 if j==0 else 44,20+count*17*1.5))
    return widths,rows,heights

def guidance_notes():
    return D.get('guidanceNotes',['직전 가이던스·동일 기준 컨센서스 미확보. 정성적 범위는 회사 표현을 유지.'])

def guidance_notes_height():
    return max(56,12+sum(22*len(wrapped_text(note,14,width=1356)) for note in guidance_notes()))

def guidance_height(items):
    matched,other=market_guidance_rows(items)
    if matched:return 40+58*len(matched)+(42+32*len(guidance_groups(other)[1]) if other else 0)+60
    return sum(compact_guidance_layout(items)[2])+guidance_notes_height() if compact_guidance(items) else 42+48*max(1,len(items))+40

def market_guidance_rows(items):
    matched=[];other=[]
    for g in items:
        estimate=next((e for e in D.get('marketEstimates',[]) if e['period']==g['period'] and e['guidanceMetric']==g['metric']),None)
        if estimate and g.get('convertedGuidance'):matched.append((g,estimate))
        else:other.append(g)
    periods=list(dict.fromkeys(g['period'] for g in items))
    matched.sort(key=lambda pair:(periods.index(pair[0]['period']),0 if pair[0]['metric']=='매출 증가율' else 1))
    return matched,other

def guid_market(items,y):
    matched,other=market_guidance_rows(items)
    widths=[260,260,230,230,380];starts=[40]
    for w in widths[:-1]:starts.append(starts[-1]+w)
    def cells(yy,heading=False):
        for i,(x,w) in enumerate(zip(starts,widths)):
            box(x,yy,w,40 if heading else 58,fill='#EEEDE9' if heading else '#EEF5FC' if i==1 else '#F2F4F5' if i==0 else 'white',r=0)
    def centered_cell(i,yy,value,size=21,color='ink',bold=True):
        x=starts[i];w=widths[i]
        text(x+(w-measure(value,size,bold))/2,yy,value,size,color,bold,width=w-24)
    def plain_money(value,unit,delta=False):
        if unit=='money':
            prefix=('+' if value>0 else '-' if value<0 else '') if delta else ('-' if value<0 else '')
            return prefix+SYM+number(abs(value)/1000)+'B'
        return fmt(value,unit,delta)
    cells(y,True)
    for i,label in enumerate(['기간 / 지표','회사 가이던스¹','시장 컨센서스','GAP²','비고 · 회사 원문']):
        centered_cell(i,y+9,label,18)
    for j,(g,e) in enumerate(matched):
        yy=y+40+j*58;cells(yy)
        period=g['period'];badge_w=measure(period,13,True)+16
        box(52,yy+5,badge_w,20,fill='#DDE7EF',outline=False,r=4)
        text(60,yy+5,period,13,'blue',True)
        label='매출' if e['unit']=='money' else 'EPS · Non-GAAP'
        text(56,yy+27,label,21,bold=True,width=widths[0]-30)
        c=g.get('convertedGuidance')
        if not c:raise ValueError('시장 비교 행에 숫자 환산값이 없습니다: '+g['period']+' '+g['metric'])
        values=c['values'];value=plain_money(values[0],c['unit']) if values[0]==values[1] else rangefmt(values,c['unit'])
        bound=c.get('bound');value+= {'atLeast':' 이상','atMost':' 이하','greaterThan':' 초과','nearUpper':' 상단 근접'}.get(bound,'')
        centered_cell(1,yy+5,value,22,'blue')
        rates=g['growthConversion']['range'] if g.get('growthConversion') else c.get('growthRange')
        rate=(signed(rates[0]) if rates[0]==rates[1] else rangefmt(rates,'percent')) if rates and all(valid(r) for r in rates) else '미제공'
        caption=('하한 YoY ' if bound=='atLeast' else 'YoY ' if not c.get('isApproximate') else '환산 YoY ')+rate
        centered_cell(1,yy+35,caption,14,'muted',False)
        centered_cell(2,yy+5,fmt(e['value'],e['unit']),22)
        centered_cell(2,yy+35,'YoY '+signed(e['yoy'],p=2),14,'muted',False)
        centered_cell(3,yy+5,plain_money(c['gap'],c['unit'],True),21)
        gap_caption=('하한 기준 ' if bound=='atLeast' else '컨센서스 대비 ')+signed(c['gapPercent'],p=2 if bound else 1)
        centered_cell(3,yy+35,gap_caption,14,'muted',False)
        quote='“'+(g.get('originalText') or g.get('currentText',''))+'”'
        text(starts[4]+16,yy+6,quote,16,width=widths[4]-32,lines=2)
    end=y+40+len(matched)*58
    if other:
        periods,groups=guidance_groups(other)
        widths2=[300]+[int(1060/len(periods))]*len(periods)
        end+=12
        def other_value(g,unit):
            converted=g.get('growthConversion')
            if converted:return rangefmt(converted['range'],'percent')
            if g.get('currentText'):return g['currentText']
            return rangefmt(g['current'],unit)+{'atLeast':' 이상','atMost':' 이하','greaterThan':' 초과','nearUpper':' 상단 근접'}.get(g.get('bound'),'')
        for j,values in enumerate([['기타 가이던스']+periods]+[[key[0]]+[other_value(group[p],key[1]) if p in group else '—' for p in periods] for key,group in groups.items()]):
            x=40;rh=30 if j==0 else 32
            for w,value in zip(widths2,values):
                box(x,end,w,rh,fill='#EEEDE9' if j==0 else 'white',r=0)
                tx=x+(w-measure(value,16,True))/2 if j==0 else x+14
                text(tx,end+5,value,16,bold=j==0,width=w-28);x+=w
            end+=rh
    for i,note in enumerate(D.get('guidanceNotes',[])):
        text(42,end+12+i*22,note,14,'muted',width=1356)
    return end+60

def guid(items,y):
    if market_guidance_rows(items)[0]:return guid_market(items,y)
    if not compact_guidance(items):return guid_legacy(items,y)
    widths,rows,heights=compact_guidance_layout(items)
    def row(yy,values,rh,heading=False):
        x=40
        for i,(w,value) in enumerate(zip(widths,values)):
            box(x,yy,w,rh,fill='#EEEDE9' if heading else '#EEF5FC' if 0<i<len(widths)-1 else 'white',r=0)
            size=17;bold=heading or 0<i<len(widths)-1
            tx=x+16 if i==0 else x+max(12,(w-measure(value,size,bold))/2)
            count=len(wrapped_text(value,size,bold,w-24))
            text(tx,yy+10,value,size,'blue' if not heading and 0<i<len(widths)-1 else 'ink',bold,width=w-24,lines=count)
            x+=w
    end=y
    for j,(values,rh) in enumerate(zip(rows,heights)):
        row(end,values,rh,j==0);end+=rh
    note_y=end+12
    for note in guidance_notes():
        count=len(wrapped_text(note,14,width=1356))
        text(42,note_y,note,14,'muted',width=1356,lines=count);note_y+=22*count
    return end+guidance_notes_height()

def review_outlook(y):
    """Revenue/EPS outlook, including consensus-only periods with no company guidance."""
    def metric_name(item,is_estimate=False):
        value=item.get('guidanceMetric' if is_estimate else 'metric','').strip().lower().replace(' ','')
        if value in ('매출','매출액','매출증가율','revenue','revenuegrowth'):return '매출'
        if 'eps' in value:return 'EPS'
        return None
    def period_key(value):
        import re
        match=re.match(r'FY(\d{4})(?: Q([1-4]))?',value)
        return 'FY'+match[1]+(' Q'+match[2] if match[2] else '') if match else value
    def period_sort(value):
        import re
        match=re.match(r'FY(\d{4})(?: Q([1-4]))?',value)
        return (int(match[1]),int(match[2]) if match[2] else 5) if match else (9999,value)
    def table_row(yy,values,widths,heading=False):
        size=16 if heading else 19
        counts=[len(wrapped_text(value,size,heading or i>0,w-28)) for i,(value,w) in enumerate(zip(values,widths))]
        height=max(42 if heading else 54,20+max(counts)*size*1.5)
        x=40
        for i,(value,w,count) in enumerate(zip(values,widths,counts)):
            box(x,yy,w,height,fill='#EEEDE9' if heading else '#EEF5FC' if i==len(widths)-2 else 'white',r=0)
            tx=x+14 if i==0 or count>1 else x+(w-measure(value,size,heading or i>0))/2
            text(tx,yy+10,value,size,'blue' if not heading and i==len(widths)-2 else 'ink',heading or i>0,width=w-28,lines=count)
            x+=w
        return height
    end=y
    for metric in ('매출','EPS'):
        estimates={period_key(e['period']):e for e in D.get('marketEstimates',[]) if metric_name(e,True)==metric}
        guidance={period_key(g['period']):g for g in D['guidance'] if metric_name(g)==metric
                  and (g.get('current') is not None or g.get('currentText') or g.get('convertedGuidance'))}
        title=metric
        if metric=='EPS' and estimates:
            bases=list(dict.fromkeys(e['basis'] for e in estimates.values()))
            title+=' · '+(' / '.join(bases))
        text(42,end,title,20,bold=True,width=1356)
        end+=38
        with_company=bool(guidance)
        widths=[180,480,360,340] if with_company else [240,660,460]
        headings=['기간']+(['회사 가이던스'] if with_company else [])+['시장 컨센서스','컨센서스 YoY']
        end+=table_row(end,headings,widths,True)
        periods=sorted(set(estimates)|set(guidance),key=period_sort)
        if not periods:
            end+=table_row(end,['—']+(['—'] if with_company else [])+['미제공','—'],widths)
        for period in periods:
            g=guidance.get(period);e=estimates.get(period)
            company='—'
            if g:
                converted=g.get('convertedGuidance')
                if converted:
                    company=rangefmt(converted['values'],converted['unit'])+(' (단순 환산)' if converted.get('isApproximate') else '')
                elif g.get('current') is not None:
                    company=rangefmt(g['current'],g['unit'])+{'atLeast':' 이상','atMost':' 이하','greaterThan':' 초과','nearUpper':' 상단 근접'}.get(g.get('bound'),'')
                else:company=g['currentText']
                if metric=='EPS':company+='\n'+g['basis']
            values=[period]+([company] if with_company else [])+[fmt(e['value'],e['unit']) if e else '—',signed(e.get('yoy')) if e else '—']
            end+=table_row(end,values,widths)
        end+=28
    return end
def newpage():
    global image,draw
    image=Image.new('RGB',(W*S,H*S),C['bg']);draw=ImageDraw.Draw(image);header()
def chunks(xs,k):return [xs[i:i+k] for i in range(0,len(xs),k)]
def main():
    global D,SYM,H
    inp,out=sys.argv[1:3];D=json.loads(Path(inp).read_text(encoding='utf8'))
    SYM={'USD':'$','EUR':'€','KRW':'₩','JPY':'¥','GBP':'£','CNY':'¥','TWD':'NT$'}[D['company']['currency']]
    out=Path(out)
    compact=D.get('presentation',{}).get('profile')=='compact-review-v1'
    def body():
        chart_title_y=metrics();section(chart_title_y,'02','과거 실적 추이')
        chart(40,chart_title_y+46,672,226,D['quarters'][-8:]);chart(728,chart_title_y+46,672,226,D['annuals'][-5:],True)
        call_y=market_section(chart_title_y+300)
        section(call_y,'04',call_title())
        text(1400-measure('증가율: 전년 동기 대비',14),call_y+10,'증가율: 전년 동기 대비',14,'muted')
        cards_y=drivers(D.get('operatingDrivers',[]),call_y+46)
        items=D['callMetrics']
        end=calls(items,cards_y)
        if not items:
            text(60,cards_y+20,'컨콜 수치 미제공',20,'muted');end=cards_y+60
        return end+20
    # Measure with the same typography, then draw a single canvas at its full height.
    newpage();bottom=body();H=max(1940,math.ceil(bottom+110))
    newpage();body();footer(1,1)
    name='report-01.png';image.save(out/name);print('저장: '+str(out/name))
    (out/'image-pages.json').write_text(json.dumps({'files':[name],'engine':'Pillow '+PIL_VERSION,'width':W*S,'height':H*S},ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':main()
