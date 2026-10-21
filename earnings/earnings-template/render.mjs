import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {createHash} from 'node:crypto';
import {validate,normalize,TEMPLATE_VERSION} from './report.mjs';
const run=promisify(execFile),here=path.dirname(fileURLToPath(import.meta.url));
const hash=s=>createHash('sha256').update(s).digest('hex');
const escape=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function main(){
 if(!process.argv[2])throw Error('입력 JSON 경로가 필요합니다. 자료 폴더의 원문을 먼저 정리한 뒤 node earnings-template/render.mjs "결과/회사_분기/input.snapshot.json"으로 실행하세요.');
 const input=path.resolve(process.argv[2]);
 const raw=await fs.readFile(input,'utf8'),data=JSON.parse(raw.replace(/^\uFEFF/,'')),schema=JSON.parse(await fs.readFile(path.join(here,'schema.json'),'utf8'));
 Object.assign(data,{consensus:null,guidance:[],guidanceNotes:[],marketEstimates:[]});
 validate(data,schema);const normalized=normalize(data);
 const ticker=data.company.ticker.replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').replace(/[. ]+$/g,'_');
 const reportName=ticker+'_FY'+normalized.current.year+'Q'+normalized.current.quarter;
 const out=path.resolve(process.argv[3]||path.join(here,'..','결과',reportName));
 await fs.mkdir(out,{recursive:true});
 // Fail closed: a previous manifest must never claim a failed run succeeded.
 await fs.rm(path.join(out,'render-manifest.json'),{force:true});
 const fonts=path.join(here,'.runtime','fonts');await fs.mkdir(fonts,{recursive:true});
 for(const [name,win]of [['regular','malgun.ttf'],['bold','malgunbd.ttf']]){
  const target=path.join(fonts,name+'.ttf');
  try{await fs.access(target)}catch{await fs.copyFile(path.join(process.env.WINDIR||'C:\\Windows','Fonts',win),target)}
 }
 await fs.writeFile(path.join(out,'normalized.json'),JSON.stringify(normalized,null,2));
 await fs.writeFile(path.join(out,'input.snapshot.json'),raw);
 const pythonCandidates=[process.env.EARNINGS_PYTHON,path.join(os.homedir(),'anaconda3','python.exe'),'python'].filter(Boolean);
 let python,result;for(const p of pythonCandidates){
  try{const r=await run(p,['-c','import PIL;print(PIL.__version__)'],{timeout:10000,windowsHide:true});python=p;break}catch{}
 }
 if(!python)throw Error('Python + Pillow가 필요합니다. EARNINGS_PYTHON에 Python 경로를 지정하세요.');
 result=await run(python,[path.join(here,'draw_report.py'),path.join(out,'normalized.json'),out],{timeout:60000,maxBuffer:1024*1024,windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
 console.log(result.stdout.trim());
 const pages=JSON.parse(await fs.readFile(path.join(out,'image-pages.json'),'utf8'));
 const manifest={templateVersion:TEMPLATE_VERSION,inputHash:hash(raw),templateHash:hash(await fs.readFile(path.join(here,'draw_report.py'),'utf8')+await fs.readFile(path.join(here,'report.mjs'),'utf8')),fontHashes:{regular:hash(await fs.readFile(path.join(fonts,'regular.ttf'))),bold:hash(await fs.readFile(path.join(fonts,'bold.ttf')))},engine:pages.engine,width:pages.width,height:pages.height,files:[],sourceIds:data.sources.map(s=>s.id)};
 for(const name of pages.files){
  const buf=await fs.readFile(path.join(out,name));
  if(pages.files.length!==1||buf.readUInt32BE(16)!==2880||buf.readUInt32BE(20)!==pages.height)throw Error('단일 페이지 출력 이미지 크기 불일치');
  manifest.files.push({file:name,sha256:hash(buf)});
 }
 const estimateNotes=(normalized.marketEstimates||[]).map(e=>'<p>'+escape(e.period+' '+e.guidanceMetric+' · 시장: '+e.sourceId+' · EPS 기준 확인: '+(e.basisSourceId||'해당 없음')+' · 회계 기준: '+e.basis+' · 조회 시점: '+(e.asOf||'미기재')+' · 예상치: '+e.value+' · 전년: '+e.priorValue+' · YoY: '+e.yoy+'% ('+(e.reportedGrowth!==null?'제공 원문 값':'제공 예상치/전년 수치로 계산')+') · 원문 위치: '+e.location)+'</p>').join('');
 const conversionNotes=normalized.guidance.filter(g=>g.convertedGuidance).map(g=>{
  const c=g.convertedGuidance;
  const growth=g.growthConversion?.range||c.growthRange;
  const explanation=c.isApproximate?'회사 공식 숫자가 아닌 단순 환산 추정; FX·인수 효과 재조정 미반영':'회사 제시 숫자; '+(c.bound==='atLeast'?'하한 기준 비교':c.bound==='atMost'?'상한 기준 비교':'제시 범위 중간값 기준 비교');
  return '<p>'+escape(g.period+' '+g.metric+' · 원문: '+(g.originalText||g.currentText)+' · 성장률: '+(growth?growth.join('–'):'미제공')+'% · 전년 기준값: '+c.priorValue+' · 전년 출처: '+c.baseSourceId+' / '+c.baseLocation+' · 숫자 범위: '+c.values.join('–')+' · 비교 기준값: '+c.midpoint+' · GAP: '+c.gap+' ('+c.gapPercent+'%) · '+explanation)+'</p>';
 }).join('');
 const guidanceConditions=normalized.guidance.filter(g=>g.currentNote).map(g=>'<p>'+escape(g.period+' '+g.metric+' · '+g.currentNote+' · 원문: '+(g.originalText||'미제공')+' · 출처: '+g.sourceId+' / '+(g.location||'미기재'))+'</p>').join('');
 const market=normalized.marketData;
 const marketNotes=market?'<h2>주가·밸류에이션 기준</h2><p>'+escape('주가 기준: '+(market.asOf||'미확보')+' · 통화: '+(market.currency||'미확보')+' · 주가: '+(market.price??'미제공')+' · 시가총액: '+(market.marketCap??'미제공')+' · 시가총액 조회: '+(market.marketCapAsOf||'미확보'))+'</p><p>'+escape('분기 EPS: '+market.quarterEPS+' · EPS 회계 기준: '+market.epsBasis+' · 연율화 EPS: '+market.annualizedEPS+' · PER = 주가 ÷ (분기 EPS × 4): '+(market.per??('산출 불가 / '+market.perReason)))+'</p><p>'+escape('주가 출처: '+(market.priceSource||'미확보')+' · 시가총액 출처: '+(market.marketCapSource||'미확보')+' · 시계열: '+(market.historySource||'미확보'))+'</p><p>'+escape((market.notes||[]).join(' · '))+'</p>':'';
 for(const g of data.guidance){
  const estimate=(normalized.marketEstimates||[]).find(e=>e.period===g.period&&e.guidanceMetric===g.metric);
  if(estimate&&!g.consensusSourceId){g.consensusSourceId=estimate.sourceId;g.consensusAsOf=estimate.asOf||'조회 시점 미기재'}
 }
 const html='<!doctype html><html lang="ko"><meta charset="utf-8"><title>'+escape(data.company.name)+' 실적 리포트</title><style>body{margin:0;background:#ddd;font-family:Malgun Gothic,sans-serif}img{display:block;width:min(1440px,100%);height:auto;margin:0 auto 24px}aside{max-width:1360px;margin:auto;padding:40px;background:white;line-height:1.7}</style>'+pages.files.map(name=>'<img src="'+name+'" alt="'+escape(data.company.name)+' 실적 리포트">').join('')+'<aside><h2>출처 목록</h2>'+data.sources.map(s=>'<p>'+escape(s.id+' — '+s.label)+'</p>').join('')+data.guidance.map(g=>'<p>'+escape(g.period+' '+g.metric+' · 회사: '+g.sourceId+' · 컨센서스: '+(g.consensusSourceId||'미제공')+' · 시점: '+(g.consensusAsOf||'미제공'))+'</p>').join('')+'</aside></html>';
 await fs.writeFile(path.join(out,'report.html'),html.replace('</aside>',marketNotes+(estimateNotes?'<h2>제공 컨센서스</h2>'+estimateNotes:'')+(guidanceConditions?'<h2>가이던스 부연 설명</h2>'+guidanceConditions:'')+(conversionNotes?'<h2>가이던스 환산 근거</h2>'+conversionNotes+'<pre>'+escape(JSON.stringify(normalized.guidanceConversionRules,null,2))+'</pre>':'')+'</aside>'));
 await fs.writeFile(path.join(out,'render-manifest.json'),JSON.stringify(manifest,null,2));
 console.log('완료: '+manifest.files.length+'페이지 / '+pages.engine+' / 고정 템플릿 '+TEMPLATE_VERSION);
}
main().catch(e=>{console.error('오류: '+e.message);process.exitCode=1});
