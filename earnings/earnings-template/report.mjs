import fs from 'node:fs/promises';
export const TEMPLATE_VERSION='1.8.0';
export const GUIDANCE_CONVERSION_RULES={
 version:'1',isOfficial:false,
 bands:{'low double digits':[10,12],'low teens':[11,13],'mid teens':[14,16]},
 selectors:{'high end':'upper','low end':'lower'},
 gap:'converted midpoint minus consensus',
 basis:'simple prior-year conversion; no FX or acquisition bridge'
};
function qualitativeGrowth(raw){
 if(!raw)return null;
 const phrase=raw.toLowerCase().replace(/상단/g,'high end').replace(/하단/g,'low end').replace(/[^a-z0-9]+/g,' ').trim();
 const band=Object.keys(GUIDANCE_CONVERSION_RULES.bands).find(k=>phrase.includes(k)||phrase.includes(k.replace(/s$/,'')));
 if(!band)return null; // Preserve non-growth guidance as text; do not invent a growth range.
 const range=GUIDANCE_CONVERSION_RULES.bands[band];
 const selector=phrase.includes('high end')?'upper':phrase.includes('low end')?'lower':'range';
 return {range:selector==='upper'?[range[1],range[1]]:selector==='lower'?[range[0],range[0]]:[...range],band,selector,isOfficial:false};
}
const has=v=>typeof v==='number'&&Number.isFinite(v);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n=(v,p=2)=>Number(v).toLocaleString('en-US',{minimumFractionDigits:p,maximumFractionDigits:p});
const sign=v=>v>0?'+':v<0?'−':'';
export function validate(data,schema,path='$'){
 if(schema.anyOf){if(!schema.anyOf.some(s=>{try{validate(data,s,path);return true}catch{return false}}))throw Error(path+': 허용되지 않는 형식');return}
 if(schema.const!==undefined&&data!==schema.const)throw Error(path+': '+schema.const+' 필요');
 if(schema.enum&&!schema.enum.includes(data))throw Error(path+': 허용값 '+schema.enum.join(', '));
 if(schema.type){const ts=[schema.type].flat();if(!ts.some(t=>t==='null'?data===null:t==='array'?Array.isArray(data):t==='integer'?Number.isInteger(data):t==='object'?data!==null&&typeof data==='object'&&!Array.isArray(data):t==='number'?has(data):typeof data===t))throw Error(path+': '+ts.join('/')+' 필요')}
 if(typeof data==='string'&&((schema.maxLength&&[...data].length>schema.maxLength)||(schema.minLength&&data.length<schema.minLength)))throw Error(path+': 문장 길이 제한 '+schema.minLength+'–'+schema.maxLength);
 if(has(data)&&((schema.minimum!==undefined&&data<schema.minimum)||(schema.maximum!==undefined&&data>schema.maximum)))throw Error(path+': 수치 범위 오류');
 if(Array.isArray(data)){if((schema.maxItems!==undefined&&data.length>schema.maxItems)||(schema.minItems!==undefined&&data.length<schema.minItems))throw Error(path+': 항목 개수 오류');data.forEach((v,i)=>validate(v,schema.items,path+'['+i+']'))}
 if(data&&typeof data==='object'&&!Array.isArray(data)){for(const k of schema.required||[])if(!(k in data))throw Error(path+'.'+k+': 필수');for(const [k,v]of Object.entries(data)){if(schema.properties?.[k])validate(v,schema.properties[k],path+'.'+k);else if(schema.additionalProperties===false)throw Error(path+'.'+k+': 알 수 없는 항목')}}
}
export function growth(v,p){
 if(!has(v)||!has(p))return null;
 if(p<0&&v>0)return '흑자전환';
 if(p>0&&v<0)return '적자전환';
 if(p<=0)return '산출 불가';
 return (v/p-1)*100;
}
function signed(v,unit='%',p=1){return has(v)?sign(v)+n(Math.abs(v),p)+unit:typeof v==='string'?v:'미제공'}
export function normalize(d){
 if((d.callMetrics.length+(d.operatingDrivers||[]).length)>6)throw Error('컨콜 주요 수치는 중복을 제거해 최대 6개로 선정하세요.');
 const ids=new Set();for(const s of d.sources){if(ids.has(s.id))throw Error('중복 sourceId: '+s.id);ids.add(s.id)}
 const check=id=>{if(id!==null&&!ids.has(id))throw Error('없는 출처: '+id)};
 for(const x of [...d.quarters,...d.annuals,...d.callMetrics,...d.guidance])check(x.sourceId);
 for(const x of d.operatingDrivers||[])check(x.sourceId);
 const marketKeys=new Set();
 const marketEstimates=(d.marketEstimates||[]).map(e=>{
  check(e.sourceId);
  if(e.basisSourceId)check(e.basisSourceId);
  const key=e.period+'|'+e.guidanceMetric;
  if(marketKeys.has(key))throw Error('중복 시장 컨센서스: '+key);
  marketKeys.add(key);
  return {...e,yoy:has(e.reportedGrowth)?e.reportedGrowth:growth(e.value,e.priorValue)};
 });
 if(d.consensus)check(d.consensus.sourceId);
 check(d.reportPeriod.sourceId);
 const dateOK=s=>/^\d{4}-\d{2}-\d{2}$/.test(s)&&!isNaN(Date.parse(s))&&new Date(s).toISOString().slice(0,10)===s;
 if(!dateOK(d.reportPeriod.start)||!dateOK(d.reportPeriod.end)||d.reportPeriod.start>d.reportPeriod.end)throw Error('reportPeriod는 원문 기준 실제 기간을 YYYY-MM-DD로 입력하세요');
 if(d.callMetrics.length&&!d.conferenceCall)throw Error('컨콜 수치가 있으면 conferenceCall에 대상 분기와 출처를 입력하세요');
 if(d.conferenceCall)check(d.conferenceCall.sourceId);
 const qs=[...d.quarters].sort((a,b)=>a.year-b.year||a.quarter-b.quarter);
 const annuals=[...d.annuals].sort((a,b)=>a.year-b.year);
 if(new Set(qs.map(q=>q.year+'-'+q.quarter)).size!==qs.length)throw Error('중복 회계 분기');
 if(new Set(annuals.map(q=>q.year)).size!==annuals.length)throw Error('중복 회계연도');
 const current=qs.at(-1),prior=qs.find(q=>q.year===current.year-1&&q.quarter===current.quarter),prev=qs.find(q=>q.year*4+q.quarter===current.year*4+current.quarter-1);
 if(annuals.some(a=>a.year>current.year||(a.year===current.year&&current.quarter!==4)))throw Error('annuals에는 완료된 회계연도만(Q4 발표 시 당해 연도 포함 가능) 입력하세요');
 const con=d.consensus;
 if(con&&(con.year!==current.year||con.quarter!==current.quarter||con.basis!==d.company.basis))throw Error('이번 분기 컨센서스 기간 또는 회계 기준 불일치');
 const margin=q=>has(q?.operatingIncome)&&has(q?.revenue)&&q.revenue!==0?q.operatingIncome/q.revenue*100:null;
 const metrics=['revenue','operatingIncome','opm','eps'].map(key=>{
  const get=q=>key==='opm'?margin(q):q?.[key]??null;
  const value=get(current),y=get(prior),p=get(prev),e=con?.[key]??null;
  return {key,value,prior:y,previous:p,consensus:e,yoy:key==='opm'?(has(value)&&has(y)?value-y:null):growth(value,y),qoq:key==='opm'?(has(value)&&has(p)?value-p:null):growth(value,p),difference:has(value)&&has(e)?value-e:null,surprise:key==='opm'?null:growth(value,e)};
 });
 // AI extraction may put numeric guidance conditions in currentText. Keep those
 // conditions separately so they cannot replace the numeric range in the table.
 const guidanceInput=d.guidance.map(g=>{
  if(!g.currentText||g.current===null)return g;
  const {currentText,...numeric}=g;
  return {...numeric,currentNote:currentText};
 });
 for(const g of guidanceInput){
  check(g.consensusSourceId);
  if(g.previous&&g.previous[0]>g.previous[1]||g.current&&g.current[0]>g.current[1])throw Error('가이던스 하단이 상단보다 큼: '+g.period);
  if(has(g.consensus)&&(!g.consensusAsOf||!g.consensusSourceId))throw Error('가이던스 컨센서스 시점·출처 필요');
 }
 const guidance=guidanceInput.map(g=>{
  const estimate=marketEstimates.find(e=>e.period===g.period&&e.guidanceMetric===g.metric);
  if(g.current&&estimate&&g.unit===estimate.unit){
   const values=[...g.current],midpoint=(values[0]+values[1])/2;
   const growthRange=values.map(v=>growth(v,estimate.priorValue));
   return {...g,growthConversion:null,convertedGuidance:{values,midpoint,unit:g.unit,priorValue:estimate.priorValue,baseSourceId:estimate.sourceId,baseLocation:estimate.location+' · Year Ago EPS',consensus:estimate.value,gap:midpoint-estimate.value,gapPercent:estimate.value>0?(midpoint/estimate.value-1)*100:null,growthRange,bound:g.bound||null,isApproximate:false,unbridged:false}};
  }
  const conversion=g.current?null:qualitativeGrowth(g.originalText||g.currentText);
  if(!conversion)return {...g,growthConversion:null,convertedGuidance:null};
  if(!estimate)return {...g,growthConversion:conversion,convertedGuidance:null};
  const fiscal=/^FY(\d{4}) (Q([1-4])|연간)$/.exec(g.period);
  if(!fiscal)throw Error('환산 기준 기간을 확인하세요: '+g.period);
  let priorValue,baseSourceId,baseLocation;
  if(estimate.unit==='money'){
   const base=fiscal[3]?qs.find(q=>q.year===Number(fiscal[1])-1&&q.quarter===Number(fiscal[3])):annuals.find(a=>a.year===Number(fiscal[1])-1);
   if(!has(base?.revenue))throw Error('매출 가이던스 환산에 필요한 전년 실적이 없습니다: '+g.period);
   priorValue=base.revenue;baseSourceId=base.sourceId;baseLocation=fiscal[3]?'전년 동기 매출':'전년 연간 매출';
  }else{
   if(!/Non-GAAP/i.test(estimate.basis)||!has(estimate.priorValue))throw Error('EPS 환산에는 동일 기준 전년 Non-GAAP EPS가 필요합니다: '+g.period);
   priorValue=estimate.priorValue;baseSourceId=estimate.sourceId;baseLocation=estimate.location+' · Year Ago EPS';
  }
  const values=conversion.range.map(rate=>priorValue*(1+rate/100));
  const midpoint=(values[0]+values[1])/2;
  return {...g,growthConversion:conversion,convertedGuidance:{values,midpoint,unit:estimate.unit,priorValue,baseSourceId,baseLocation,consensus:estimate.value,gap:midpoint-estimate.value,gapPercent:estimate.value>0?(midpoint/estimate.value-1)*100:null,isApproximate:true,unbridged:true}};
 });
 let marketData=null;
 if(d.marketData){
  check(d.marketData.sourceId);
  if(d.marketData.symbol.toUpperCase()!==d.company.ticker.toUpperCase())throw Error('주가 자료의 종목이 다릅니다.');
  const annualizedEPS=has(current.eps)?current.eps*4:null;
  const reason=!has(d.marketData.price)||d.marketData.price<=0?'주가 미확보'
   :d.marketData.currency!==d.company.currency?'주가·EPS 통화 불일치'
   :d.marketData.splitSinceReport?'주식분할 이후 EPS 기준 확인 필요'
   :annualizedEPS===null?'분기 EPS 미제공':annualizedEPS<=0?'분기 EPS가 0 이하':'';
  marketData={...d.marketData,quarterEPS:current.eps,annualizedEPS,epsBasis:d.company.basis,
   per:reason?null:d.marketData.price/annualizedEPS,perReason:reason};
 }
 return {...d,quarters:qs,annuals,current,metrics,marketEstimates,guidance,marketData,guidanceConversionRules:GUIDANCE_CONVERSION_RULES};
}
