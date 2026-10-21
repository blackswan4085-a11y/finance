(function(){
  'use strict';
  let offset=0, sequence=0, timer;
  const rows=document.getElementById('rows'), message=document.getElementById('message');
  const input=document.getElementById('search'), filter=document.getElementById('status');
  const previous=document.getElementById('previous'), next=document.getElementById('next');
  function text(parent,tag,value){const e=document.createElement(tag);e.textContent=value;parent.appendChild(e);return e;}
  function link(parent,label,url){const a=text(parent,'a',label);a.href=url;return a;}
  async function load(){
    const request=++sequence;
    message.textContent='불러오는 중…';
    previous.disabled=next.disabled=true;
    try{
      const response=await fetch('/api/sector-classifications?'+new URLSearchParams({q:input.value.trim(),status:filter.value,offset}));
      const data=await response.json();
      if(request!==sequence)return;
      if(!response.ok)throw Error(data.error||'분류를 불러오지 못했습니다. 서버를 재시작해 주세요.');
      const stats=document.getElementById('stats');stats.replaceChildren();
      for(const [label,value] of [['미국 DB 항목',data.total],['자동 연결',data.counts.mapped||0],['수동 설정',data.counts.manual||0],['검토 필요',data.counts.review||0]]){const cell=text(stats,'div',label);text(cell,'strong',value.toLocaleString());}
      document.getElementById('asof').textContent=data.classified_at?'분류 적용: '+data.classified_at.replace('T',' '):'아직 자동 분류 결과가 없습니다.';
      rows.replaceChildren();
      for(const item of data.items){
        const row=rows.insertRow();const name=row.insertCell();
        link(name,item.symbol,'/chart?symbol='+encodeURIComponent(item.symbol)).target='_blank';
        text(name,'small',item.source_name||item.name);
        row.insertCell().textContent=item.effective_sector||'미지정';
        row.insertCell().textContent=item.etf?item.etf.split(':').pop():'—';
        const state=text(row.insertCell(),'span',({manual:'수동 설정',mapped:'자동 연결',review:'검토 필요'})[item.effective_status]);state.className='state '+item.effective_status;
        const evidence=row.insertCell();text(evidence,'div',item.reason);
        text(evidence,'small',[item.method,item.raw_sector,item.industry].filter(Boolean).join(' · '));
        if(/^https:\/\//.test(item.source_url)){const source=link(evidence,item.source,item.source_url);source.target='_blank';source.rel='noopener noreferrer';source.style.fontSize='12px';}
        link(row.insertCell(),'수정','/sector-etfs?symbol='+encodeURIComponent(item.symbol));
      }
      message.className='';message.textContent=data.filtered.toLocaleString()+'개'+(data.filtered?'':' · 일치하는 종목이 없습니다.');
      document.getElementById('range').textContent=data.filtered?(offset+1)+'–'+Math.min(offset+100,data.filtered)+' / '+data.filtered.toLocaleString():'';
      previous.disabled=offset===0;next.disabled=offset+100>=data.filtered;
    }catch(e){if(request!==sequence)return;message.className='error';message.textContent=e.message;rows.replaceChildren();}
  }
  input.addEventListener('input',()=>{clearTimeout(timer);offset=0;timer=setTimeout(load,180);});
  filter.addEventListener('change',()=>{offset=0;load();});
  previous.addEventListener('click',()=>{offset=Math.max(0,offset-100);load();});next.addEventListener('click',()=>{offset+=100;load();});
  load();
})();