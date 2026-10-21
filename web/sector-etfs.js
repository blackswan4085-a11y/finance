(function () {
  "use strict";
  const body = document.getElementById("mappingRows");
  const status = document.getElementById("status");
  const saveButton = document.getElementById("save");
  const benchmark = document.getElementById("benchmark");
  const sectorInput = document.getElementById("assignedSector");
  const openChart = document.getElementById("openChart");
  const symbol = new URLSearchParams(location.search).get("symbol") || "";
  let instrument = null;
  let dirty = false;
  let optionIndex = 0;

  function setStatus(text, kind="") {
    status.textContent = text;
    status.className = "status " + kind;
  }
  function markDirty() { dirty = true; setStatus("변경 내용을 저장해 주세요."); }
  function wireEtfSearch(input) {
    const list = document.createElement("datalist");
    list.id = "etf-options-" + optionIndex++;
    input.setAttribute("list", list.id);
    input.setAttribute("autocomplete", "off");
    input.parentElement.appendChild(list);
    let timer, sequence = 0;
    input.addEventListener("input", () => {
      markDirty();
      clearTimeout(timer);
      const request = ++sequence;
      const query = input.value.trim().split(":").pop();
      timer = setTimeout(async () => {
        try {
          const response = await fetch("/api/instruments?asset_type=ETF&q=" + encodeURIComponent(query));
          if (!response.ok) return;
          const result = await response.json();
          if (request !== sequence) return;
          list.replaceChildren();
          for (const item of result.items) {
            const option = document.createElement("option");
            option.value = item.code;
            option.label = item.name;
            list.appendChild(option);
          }
        } catch (_) {}
      }, 180);
    });
  }
  function updateSectorNames() {
    const list = document.getElementById("sectorNames");
    list.replaceChildren();
    for (const row of body.rows) {
      const option = document.createElement("option");
      option.value = row.querySelector(".sector-name").value;
      list.appendChild(option);
    }
  }
  function addRow(sector, etf="", count=0) {
    const row = document.createElement("tr");
    const nameCell = row.insertCell();
    const input = document.createElement("input");
    input.value = sector;
    input.readOnly = true;
    input.className = "sector-name";
    input.setAttribute("aria-label", "섹터 이름");
    nameCell.appendChild(input);
    const etfCell = row.insertCell();
    const etfInput = document.createElement("input");
    etfInput.className = "sector-etf";
    etfInput.value = etf;
    etfInput.placeholder = "ETF 코드 또는 이름";
    etfInput.setAttribute("aria-label", sector + " ETF");
    etfCell.appendChild(etfInput);
    wireEtfSearch(etfInput);
    row.insertCell().textContent = String(count);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove";
    remove.textContent = "삭제";
    remove.setAttribute("aria-label", sector + " 연결 삭제");
    remove.addEventListener("click", () => { row.remove(); updateSectorNames(); markDirty(); });
    row.insertCell().appendChild(remove);
    body.appendChild(row);
    updateSectorNames();
    return row;
  }
  function render(result) {
    instrument = result.instrument;
    benchmark.value = result.benchmark;
    body.replaceChildren();
    result.sectors.sort((a,b) => b.count-a.count || a.sector.localeCompare(b.sector,"ko"))
      .forEach(item => addRow(item.sector,item.etf,item.count));
    document.getElementById("instrumentContext").hidden = !instrument;
    if (instrument) {
      document.getElementById("contextName").textContent = instrument.code + " · " + instrument.name;
      sectorInput.value = instrument.sector;
      const evidence = instrument.classification;
      const detail = document.getElementById('classificationEvidence');
      detail.textContent = (instrument.manual_override ? '수동 설정 우선 적용. ' : '') +
        (evidence ? (evidence.sector ? '자동 분류: '+evidence.sector+' · ' : '자동 분류 보류 · ') +
                    [evidence.source,evidence.industry,evidence.reason].filter(Boolean).join(' · ') : '자동 분류 근거가 없습니다.');
      document.getElementById('resetSector').hidden = !instrument.manual_override || !evidence;
      openChart.href = "/chart?symbol=" + encodeURIComponent(instrument.symbol);
      openChart.hidden = false;
    }
    dirty = false;
    saveButton.disabled = false;
  }
  async function save(resetSector=false) {
    const mapping = {};
    for (const row of body.rows) {
      const label = row.querySelector(".sector-name").value.trim();
      mapping[label] = row.querySelector(".sector-etf").value.trim();
    }
    const payload = {benchmark:benchmark.value.trim(),mapping};
    if (instrument) { payload.symbol = instrument.symbol; payload.sector = sectorInput.value.trim(); payload.assign_sector = resetSector || payload.sector !== instrument.sector; payload.reset_sector = resetSector; }
    saveButton.disabled = true;
    setStatus("저장하는 중…");
    try {
      const response = await fetch("/api/sector-etfs", {
        method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "저장에 실패했습니다.");
      render(result);
      setStatus("저장했습니다. 새 차트 또는 기본 구성 적용 시 반영됩니다.","success");
      return true;
    } catch (error) {
      setStatus(error.message,"error");
      return false;
    } finally { saveButton.disabled = false; }
  }
  saveButton.addEventListener("click", () => save());
  document.getElementById("resetSector").addEventListener("click", () => save(true));
  openChart.addEventListener("click", async event => {
    if (!dirty) return;
    event.preventDefault();
    if (await save()) location.assign(openChart.href);
  });
  document.getElementById("addSector").addEventListener("click", () => {
    const input = document.getElementById("newSector");
    const label = input.value.trim();
    if (!label) { setStatus("섹터 이름을 입력해 주세요.","error"); return; }
    if (Array.from(body.rows).some(row => row.querySelector(".sector-name").value.toLowerCase() === label.toLowerCase())) {
      setStatus("이미 있는 섹터입니다.","error"); return;
    }
    addRow(label).querySelector(".sector-etf").focus();
    input.value = "";
    markDirty();
  });
  document.getElementById("filter").addEventListener("input", event => {
    const query = event.currentTarget.value.trim().toLowerCase();
    for (const row of body.rows) row.hidden = !row.querySelector(".sector-name").value.toLowerCase().includes(query);
  });
  sectorInput.addEventListener("input", markDirty);
  wireEtfSearch(benchmark);
  fetch("/api/sector-etfs" + (symbol ? "?symbol=" + encodeURIComponent(symbol) : ""))
    .then(async response => {
      if (!response.ok) throw new Error("설정을 불러오지 못했습니다. 서버를 재시작한 뒤 다시 열어 주세요.");
      return response.json();
    }).then(result => { render(result); setStatus(""); })
    .catch(error => setStatus(error.message,"error"));
})();
