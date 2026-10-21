(() => {
  'use strict';
  const text = (parent, tag, value, cls) => { const el=document.createElement(tag); el.textContent=value; if(cls)el.className=cls; parent.append(el); return el; };
  function nodesMap(taxonomy) { return new Map(taxonomy.nodes.map(node => [node.id,node])); }
  function fillSelect(select, nodes, placeholder, value='') {
    select.replaceChildren(new Option(placeholder,''));
    for (const node of nodes) select.append(new Option(node.name,node.id));
    select.value=nodes.some(node=>node.id===value)?value:'';
  }
  function createFilters(elements, taxonomy, onChange=()=>{}, labels=['대분류 전체','중분류 전체','소분류 전체']) {
    const nodes=taxonomy.nodes;
    const [major,middle,minor]=elements;
    function values(){return {major:major.value,middle:middle.value,minor:minor.value};}
    function draw(value={}) {
      fillSelect(major,nodes.filter(n=>n.level==='major'),labels[0],value.major||'');
      fillSelect(middle,nodes.filter(n=>n.level==='middle'&&n.parent_id===major.value),labels[1],value.middle||'');
      fillSelect(minor,nodes.filter(n=>n.level==='minor'&&n.parent_id===middle.value),labels[2],value.minor||'');
      middle.disabled=!major.value; minor.disabled=!middle.value;
    }
    major.addEventListener('change',()=>{draw({major:major.value});onChange(values());});
    middle.addEventListener('change',()=>{draw({major:major.value,middle:middle.value});onChange(values());});
    minor.addEventListener('change',()=>onChange(values()));
    draw();
    return {values,set:value=>draw(value)};
  }
  function pathLabel(id,map) {
    const labels=[];let current=id;
    while(current){const n=map.get(current);if(!n)break;labels.unshift(n.name);current=n.parent_id;}
    return labels.join(' › ');
  }
  function terminal(ids,map) {
    const chosen=new Set(ids),covered=new Set();
    for(const id of chosen){let parent=map.get(id).parent_id;while(parent){covered.add(parent);parent=map.get(parent).parent_id;}}
    return [...chosen].filter(id=>!covered.has(id));
  }
  function matches(item,filters,status='') {
    if(status==='partial'&&!(item.has_partial_path??[1,2].includes(item.depth)))return false;
    if(status&&status!=='partial'&&item.status!==status)return false;
    return !Object.values(filters).some(Boolean)||item.paths.some(path=>Object.entries(filters).every(([level,id])=>!id||(path[level]&&path[level].id===id)));
  }
  async function openEditor({item,taxonomy,onSave}) {
    if(document.querySelector('.industry-dialog[open]'))return;
    const map=nodesMap(taxonomy);
    const dialog=document.createElement('dialog');dialog.className='industry-dialog';
    const title=text(dialog,'h2',item.name+' · '+item.symbol);title.id='industryEditorTitle';dialog.setAttribute('aria-labelledby',title.id);
    text(dialog,'p','분류가 확인된 단계까지 선택하고 추가한 뒤 저장하세요. 복수 사업은 산업을 여러 개 추가할 수 있습니다.','muted');
    const source=text(dialog,'div','원본: '+(item.source_path||item.path_label||'미분류')+' · '+(item.source_date||''),'industry-source-note');
    if(item.source_row)text(source,'small','KUIM 기업전체 '+item.source_row+'행 · '+(item.source_status||''));
    const fields=text(dialog,'div','','industry-editor-fields');const selects=[];
    for(const [index,label] of ['대분류','중분류','소분류'].entries()){
      const wrapper=document.createElement('label');wrapper.textContent=label;fields.append(wrapper);
      const select=document.createElement('select');select.setAttribute('aria-label','편집 '+label);wrapper.append(select);selects.push(select);
    }
    const definition=text(dialog,'p','','industry-definition');
    const filters=createFilters(selects,taxonomy,()=>describe(),['대분류 선택','중분류 미지정','소분류 미지정']);
    function describe(){const v=filters.values();const n=map.get(v.minor||v.middle||v.major);definition.textContent=n&&n.definition?[n.definition,n.include?'포함: '+n.include:'',n.exclude?'제외: '+n.exclude:''].filter(Boolean).join(' · '):'';}
    let selected=[...(item.node_ids||[])];
    const add=text(dialog,'button','선택한 산업 추가','industry-add');add.type='button';
    const selection=text(dialog,'div','','industry-selected');selection.setAttribute('aria-label','지정된 산업');
    const empty=text(dialog,'p','산업을 모두 지우면 미분류로 저장됩니다.','muted');
    function draw(){selection.replaceChildren();for(const id of selected){const line=text(selection,'div','','industry-selected-row');text(line,'span',pathLabel(id,map));const remove=text(line,'button','×');remove.type='button';remove.setAttribute('aria-label',pathLabel(id,map)+' 제거');remove.addEventListener('click',()=>{selected=selected.filter(value=>value!==id);draw();});}empty.hidden=selected.length>0;}
    add.addEventListener('click',()=>{const v=filters.values(),id=v.minor||v.middle||v.major;if(!id){message.textContent='대분류를 먼저 선택해 주세요.';return;}selected=terminal([...selected,id],map);message.textContent='';draw();});
    const noteLabel=document.createElement('label');noteLabel.className='industry-note-label';noteLabel.textContent='분류 근거·검토 메모';dialog.append(noteLabel);
    const note=document.createElement('textarea');note.maxLength=2000;note.rows=3;note.value=item.manual_note||'';note.placeholder='분류를 바꾼 이유나 확인한 사업 근거';noteLabel.append(note);
    const reviewLabel=document.createElement('label');dialog.append(reviewLabel);
    const reviewRequired=document.createElement('input');reviewRequired.type='checkbox';reviewRequired.checked=Boolean(item.review_required);reviewLabel.append(reviewRequired,document.createTextNode(' 추가 사업 검토 필요'));
    const message=text(dialog,'div','','update-status');message.setAttribute('role','status');message.setAttribute('aria-live','polite');
    const actions=text(dialog,'div','','industry-dialog-actions');
    const restore=text(actions,'button','KUIM 원본으로 복원');restore.type='button';restore.hidden=!item.manual_override;
    const close=text(actions,'button','취소');close.type='button';close.addEventListener('click',()=>dialog.close());
    const save=text(actions,'button','산업 분류 저장','update-button');save.type='button';
    async function commit(reset) {
      if(save.disabled)return;
      const nodes=selected;
      save.disabled=restore.disabled=close.disabled=add.disabled=true;
      dialog.setAttribute('aria-busy','true');message.dataset.state='running';message.textContent='저장 중…';
      const cancelWhileSaving=event=>event.preventDefault();dialog.addEventListener('cancel',cancelWhileSaving);
      try{
        const res=await fetch('/api/industry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({country:item.country,symbol:item.symbol,node_ids:nodes,note:note.value,reset,review_required:reviewRequired.checked})});
        const result=await res.json();if(!res.ok||!result.ok)throw Error(result.error||'저장에 실패했습니다.');
        if(onSave)await onSave(result.industry);dialog.close();
      }catch(error){message.dataset.state='error';message.textContent=error.message;}
      finally{save.disabled=restore.disabled=close.disabled=add.disabled=false;dialog.removeAttribute('aria-busy');dialog.removeEventListener('cancel',cancelWhileSaving);}
    }
    save.addEventListener('click',()=>commit(false));restore.addEventListener('click',()=>commit(true));
    dialog.addEventListener('close',()=>dialog.remove(),{once:true});
    draw();document.body.append(dialog);dialog.showModal();
  }
  window.FinanceIndustry={createFilters,matches,openEditor,pathLabel};
})();
