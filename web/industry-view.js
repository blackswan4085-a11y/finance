(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const rows=$('industryRows'),message=$('industryMessage'),search=$('industrySearch'),country=$('industryCountry'),status=$('filterStatus');
  const previous=$('industryPrevious'),next=$('industryNext');
  let taxonomy,filters,offset=0,sequence=0,timer,view='companies';
  const params=new URLSearchParams(location.search);search.value=params.get('symbol')||params.get('q')||'';country.value=['KR','US'].includes(params.get('country'))?params.get('country'):'';
  function text(parent,tag,value,cls){const e=document.createElement(tag);e.textContent=value;if(cls)e.className=cls;parent.append(e);return e;}
  function link(parent,label,url){const a=text(parent,'a',label);a.href=url;return a;}
  function badge(parent,item){return text(parent,'span',item.status_label,'industry-state '+item.status);}
  function levelsCell(parent,paths,level){const values=[...new Set(paths.filter(p=>p[level]).map(p=>p[level].name))];if(!values.length){text(parent,'span',level==='major'?'미분류':'미지정','muted');return;}for(const label of values)text(parent,'div',label,'industry-cell-value');}
  async function loadCompanies(){
    const request=++sequence;message.dataset.state='running';message.textContent='기업 분류를 불러오는 중…';previous.disabled=next.disabled=true;rows.setAttribute('aria-busy','true');
    try{
      const res=await fetch('/api/industries?'+new URLSearchParams({q:search.value.trim(),country:country.value,status:status.value,...filters.values(),offset,limit:100}),{cache:'no-store'});
      const data=await res.json();if(request!==sequence||view!=='companies')return;if(!res.ok)throw Error(data.error||'기업 분류를 불러오지 못했습니다.');
      offset=data.offset;rows.replaceChildren();
      for(const item of data.items){
        const tr=rows.insertRow(),name=tr.insertCell();
        const chart=link(name,item.symbol,'/chart?symbol='+encodeURIComponent((item.country==='KR'?'KRX:':'')+item.symbol));chart.target='_blank';chart.rel='noopener';text(name,'div',item.name,'industry-company-name');
        if(!item.in_source)text(name,'small','KUIM 원본에 없는 종목','muted');else if(!item.in_catalogue)text(name,'small','KUIM 원본 기업 · 종목 DB 미등록','muted');
        text(tr.insertCell(),'div',(item.country==='KR'?'한국':'미국')+' · '+item.market);
        for(const level of ['major','middle','minor'])levelsCell(tr.insertCell(),item.paths,level);
        const evidence=tr.insertCell();badge(evidence,item);
        if(item.manual_note){
          const detail=text(evidence,'details','');text(detail,'summary','검토 메모·출처');
          for(const line of item.manual_note.split('\n')){
            if(/^https?:\/\//.test(line)){const source=link(detail,'사업자료 출처 ↗',line);source.target='_blank';source.rel='noopener noreferrer';}
            else if(line.trim())text(detail,'small',line);
          }
        }
        if(item.source_method)text(evidence,'small',({'CURATED_BUSINESS':'사업 검토','KIND_INDUSTRY_CROSSWALK':'KIND 업종 대응','KIND_INDUSTRY_PRODUCT_RULE':'KIND 업종·제품 기준','STOCKANALYSIS_INDUSTRY':'StockAnalysis 업종','OFFICIAL_BUSINESS_REVIEW':'공식 사업 자료 검토','OFFICIAL_ASSET_REVIEW':'공식 증권 유형 검토'})[item.source_method]||item.source_method);
        if(item.source_row){const detail=text(evidence,'details','');text(detail,'summary','원본 근거·검토 사유');text(detail,'small','기업전체 '+item.source_row+'행 · '+item.source_status);for(const reason of item.review_reason_labels)text(detail,'small',reason);if(item.source_url){for(const url of item.source_url.split(/\s*;\s*/)){if(/^https?:\/\//.test(url)){const source=link(detail,'자료 출처 ↗',url);source.target='_blank';source.rel='noopener noreferrer';}}}}
        const action=tr.insertCell();if(item.status==='excluded'){text(action,'span','제외','muted');}else{const button=text(action,'button','분류 수정','industry-edit-button');button.type='button';button.setAttribute('aria-label',item.name+' 산업 분류 수정');button.addEventListener('click',()=>FinanceIndustry.openEditor({item,taxonomy,onSave:()=>loadCompanies()}));}
      }
      if(!data.items.length){const tr=rows.insertRow(),cell=tr.insertCell();cell.colSpan=7;cell.className='industry-empty';cell.textContent='일치하는 기업이 없습니다.';}
      const stats=$('industryStats');stats.replaceChildren();for(const [label,value] of [['기업·종목',data.total],['미분류',data.counts.unclassified||0],['자동 분류 초안',data.counts.draft||0],['사업 검토 필요',data.counts.review||0],['사업 검토 완료',data.counts.approved||0],['직접 지정',data.counts.manual||0],['분류 제외',data.counts.excluded||0]]){const cell=text(stats,'div',label);text(cell,'strong',value.toLocaleString());}
      message.dataset.state='';message.textContent=data.filtered.toLocaleString()+'개 기업 · 국가·종목코드 기준';
      $('industryRange').textContent=data.filtered?(offset+1)+'–'+Math.min(offset+data.limit,data.filtered)+' / '+data.filtered.toLocaleString():'';
      previous.disabled=offset===0;next.disabled=offset+data.limit>=data.filtered;
    }catch(error){if(request!==sequence)return;message.dataset.state='error';message.textContent=error.message;rows.replaceChildren();}
    finally{if(request===sequence)rows.removeAttribute('aria-busy');}
  }
  function renderTaxonomy(){
    ++sequence;const map=new Map(taxonomy.nodes.map(n=>[n.id,n])),chosen=filters.values(),needle=search.value.trim().toLowerCase(),body=$('taxonomyRows');body.replaceChildren();let count=0;
    for(const minor of taxonomy.nodes.filter(n=>n.level==='minor')){
      const middle=map.get(minor.parent_id),major=map.get(middle.parent_id);
      if(chosen.major&&major.id!==chosen.major||chosen.middle&&middle.id!==chosen.middle||chosen.minor&&minor.id!==chosen.minor)continue;
      if(needle&&![major.name,middle.name,minor.name,minor.definition,minor.include,minor.exclude].join(' ').toLowerCase().includes(needle))continue;
      const tr=body.insertRow();for(const node of [major,middle,minor]){const td=tr.insertCell();text(td,'div',node.name);text(td,'small',node.id,'muted');}
      const info=tr.insertCell();text(info,'div',minor.definition);const detail=text(info,'details','');text(detail,'summary','포함·제외 기준');text(detail,'small','포함: '+(minor.include||'—'));text(detail,'small','제외: '+(minor.exclude||'—'));count++;
    }
    message.dataset.state='';message.textContent=count+'개 소분류';
  }
  function load(){return view==='companies'?loadCompanies():renderTaxonomy();}
  function showView(name){view=name;const company=name==='companies';$('companiesPanel').hidden=!company;$('taxonomyPanel').hidden=company;$('countryLabel').hidden=$('statusLabel').hidden=!company;for(const id of ['companiesTab','taxonomyTab']){const active=(id==='companiesTab')===company;$(id).setAttribute('aria-selected',String(active));$(id).tabIndex=active?0:-1;}load();}
  for(const [index,id] of ['companiesTab','taxonomyTab'].entries()){$(id).addEventListener('click',()=>showView(index?'taxonomy':'companies'));$(id).addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const target=event.key==='Home'?0:event.key==='End'?1:1-index;showView(target?'taxonomy':'companies');$(['companiesTab','taxonomyTab'][target]).focus();}});}
  async function init(){try{const res=await fetch('/api/industry-taxonomy');taxonomy=await res.json();if(!res.ok)throw Error(taxonomy.error||'분류 체계를 불러오지 못했습니다.');filters=FinanceIndustry.createFilters([$('filterMajor'),$('filterMiddle'),$('filterMinor')],taxonomy,()=>{offset=0;load();});const c=taxonomy.source.counts;$('sourceInfo').textContent='KUIM '+taxonomy.source.source_date+' 기준 · 대분류 '+c.major+' · 중분류 '+c.middle+' · 소분류 '+c.minor+(taxonomy.source.extension_count?' (원본 '+taxonomy.source.original_counts.minor+' + 보완 '+taxonomy.source.extension_count+')':'')+' · 원본 기업 '+taxonomy.source.company_rows.toLocaleString()+'행';search.addEventListener('input',()=>{clearTimeout(timer);offset=0;timer=setTimeout(load,180);});for(const e of [country,status])e.addEventListener('change',()=>{offset=0;load();});previous.addEventListener('click',()=>{offset=Math.max(0,offset-100);load();});next.addEventListener('click',()=>{offset+=100;load();});await loadCompanies();}catch(error){message.dataset.state='error';message.textContent=error.message;}}
  init();
})();
