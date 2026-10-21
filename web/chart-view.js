(function () {
  "use strict";
  const periods = [
    {key:"daily", label:"일봉", visible:130},
    {key:"weekly", label:"주봉", visible:100},
    {key:"monthly", label:"월봉", visible:30},
    {key:"quarterly", label:"분기봉", visible:12}
  ];
  const grid = document.getElementById("grid");
  const dateStart = document.getElementById("rangeStart");
  const dateEnd = document.getElementById("rangeEnd");
  const sharedMessage = document.getElementById("sharedMessage");
  const payloadCache = new Map();
  const panes = [];
  let sharedRange = null;
  let syncingRange = false;
  const number = value => Number(value).toLocaleString("ko-KR", {maximumFractionDigits:2});
  const volume = value => value >= 1e9 ? (value / 1e9).toFixed(2) + "B"
    : value >= 1e6 ? (value / 1e6).toFixed(2) + "M"
    : value >= 1e3 ? (value / 1e3).toFixed(1) + "K" : String(Math.round(value));
  const dateValue = time => {
    const date = new Date(time);
    return date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0") +
      "-" + String(date.getDate()).padStart(2, "0");
  };
  const setSharedMessage = value => { sharedMessage.textContent = value || ""; };

  function monthsBefore(time, months) {
    const date = new Date(time);
    const day = date.getDate();
    date.setDate(1);
    date.setMonth(date.getMonth() - months);
    const lastDay = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
    date.setDate(Math.min(day, lastDay));
    date.setHours(0, 0, 0, 0);
    return date.getTime();
  }

  function emptyPayload(expression, title) {
    return {symbol:expression || "", name:title || expression || "기본 구성",
      market:"", currency:"", ratio:Boolean(expression && expression.includes(" / ")),
      series:Object.fromEntries(periods.map(period => [period.key, []]))};
  }

  function parseExpression(value) {
    const symbols = value.trim().toUpperCase().split(/\s+\/\s+/);
    if (symbols.length < 1 || symbols.length > 2 || symbols.some(symbol =>
      !symbol || symbol.length > 120 || /[\x00-\x1f]/.test(symbol)))
      throw new Error("종목 코드·이름을 입력하고, 비율식은 ' / '로 구분해 주세요.");
    return symbols;
  }

  function fetchPayload(symbol) {
    const key = symbol.trim().toUpperCase();
    if (!payloadCache.has(key)) {
      const request = fetch("/api/chart?symbol=" + encodeURIComponent(key)).then(async response => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || key + " 시세를 불러오지 못했습니다.");
        return result;
      }).catch(error => { payloadCache.delete(key); throw error; });
      payloadCache.set(key, request);
    }
    return payloadCache.get(key);
  }

  function ratioPayload(numerator, denominator) {
    const series = {};
    for (const period of periods) {
      const byTime = new Map((denominator.series[period.key] || []).map(bar => [bar.time, bar]));
      series[period.key] = (numerator.series[period.key] || []).flatMap(bar => {
        const divisor = byTime.get(bar.time);
        if (!divisor || [divisor.open, divisor.high, divisor.low, divisor.close].some(value => value <= 0))
          return [];
        const ratio = {time:bar.time, open:bar.open / divisor.open,
          high:bar.high / divisor.low, low:bar.low / divisor.high,
          close:bar.close / divisor.close, volume:0};
        return Object.values(ratio).every(Number.isFinite) ? [ratio] : [];
      });
    }
    if (!series.daily.length) throw new Error("두 종목에 공통 일봉 시각이 없습니다.");
    return {symbol:numerator.symbol + " / " + denominator.symbol,
      name:numerator.symbol + " / " + denominator.symbol, market:"상대가격",
      currency:"", asof:numerator.asof, series, ratio:true};
  }

  async function resolveExpression(value) {
    const symbols = parseExpression(value);
    if (symbols.length === 1) return fetchPayload(symbols[0]);
    const [numerator, denominator] = await Promise.all(symbols.map(fetchPayload));
    return ratioPayload(numerator, denominator);
  }

  function updateSharedRange(start, end, source) {
    if (!Number.isFinite(start) || !Number.isFinite(end) || start > end) return false;
    sharedRange = {start, end};
    dateStart.value = dateValue(start);
    dateEnd.value = dateValue(end);
    syncingRange = true;
    for (const pane of panes) {
      if (pane === source || pane.loading) continue;
      pane.applyRange();
    }
    if (source) source.showLast();
    syncingRange = false;
    setSharedMessage("");
    return true;
  }

  function wireSearch(input, id) {
    const list = document.createElement("datalist");
    list.id = id;
    input.setAttribute("list", id);
    input.setAttribute("autocomplete", "off");
    input.parentElement.appendChild(list);
    let timer;
    let sequence = 0;
    input.addEventListener("input", () => {
      clearTimeout(timer);
      const request = ++sequence;
      const query = input.value.trim();
      if (query.includes(" / ")) { list.replaceChildren(); return; }
      timer = setTimeout(async () => {
        try {
          const response = await fetch("/api/instruments?q=" + encodeURIComponent(query));
          if (!response.ok) return;
          const data = await response.json();
          if (request !== sequence) return;
          list.replaceChildren();
          for (const item of data.items) {
            const option = document.createElement("option");
            option.value = item.code;
            option.label = item.name + " · " + (item.asset_type === "ETF" ? "ETF" : "주식");
            list.appendChild(option);
          }
        } catch (_) { /* Direct symbol entry remains available. */ }
      }, 180);
    });
  }

  function makePane(index, initialPayload, options = {}) {
    const period = periods.find(item => item.key === options.interval) || periods[index];
    const panel = document.createElement("section");
    panel.className = "mini-panel";
    panel.setAttribute("aria-label", String(index + 1) + "번 차트");
    panel.innerHTML =
      '<div class="pane-config">' +
      '<div class="pane-row"><select class="pane-interval" aria-label="봉 주기">' +
      periods.map(item => '<option value="' + item.key + '">' + item.label + '</option>').join("") +
      '</select><input class="pane-symbol" aria-label="종목 또는 비율식" spellcheck="false" placeholder="주식·ETF 코드 / 이름 / 비율식">' +
      '<button class="apply-symbol" type="button">적용</button></div>' +
      '<div class="pane-row"><input class="pane-compare" aria-label="비교 종목" spellcheck="false" placeholder="비교 종목">' +
      '<button class="add-comparison" type="button">비교 +</button>' +
      '<select class="pane-mode" aria-label="세로축" title="세로축 기준"><option value="price">가격</option><option value="percent">시작 0%</option><option value="index100">시작 100</option></select>' +
      '<div class="pane-chips"></div></div><div class="pane-message" role="status" aria-live="polite"></div></div>' +
      '<div class="chart-toolbar"><strong class="pane-title"></strong><div class="pane-toolbar">' +
      '<select class="select-control chart-type" aria-label="차트 방식"><option value="candles">캔들</option><option value="line">라인</option></select>' +
      '<button class="text-button indicator-trigger" type="button" aria-expanded="false">지표 +</button>' +
      '<button class="text-button fit-button" type="button" title="화면 맞춤">맞춤</button>' +
      '<button class="text-button trend-button" type="button" title="두 점을 클릭해 추세선 그리기">추세선</button>' +
      '<button class="text-button clear-button" type="button" title="추세선 지우기">지우기</button></div></div>' +
      '<div class="indicator-menu" hidden></div>' +
      '<div class="chart-heading"><div><div class="instrument-title"><span class="symbol-badge"></span><strong class="instrument-name"></strong><span class="exchange-name"></span></div><div class="ohlc-readout"></div></div></div>' +
      '<div class="chart-stage"><canvas aria-label="가격 및 거래량 차트"></canvas><div class="chart-tooltip" hidden></div><div class="volume-caption">거래량 <span></span></div><div class="chart-error"></div></div>';
    grid.appendChild(panel);
    const find = selector => panel.querySelector(selector);
    wireSearch(find(".pane-symbol"), "symbol-options-" + index);
    wireSearch(find(".pane-compare"), "compare-options-" + index);
    const stage = find(".chart-stage");
    const tooltip = find(".chart-tooltip");
    const readout = find(".ohlc-readout");
    const activeIndicators = new Map();
    const pane = {
      panel, payload:initialPayload, period, comparisons:new Map(), loading:false, sequence:0,
      message(value) { find(".pane-message").textContent = value || ""; },
      applyRange() {
        const bars = this.chart.data;
        const error = find(".chart-error");
        if (!bars.length) {
          error.textContent = "표시할 " + this.period.label + " 데이터가 없습니다.";
          error.classList.add("visible");
          return;
        }
        let available = true;
        if (sharedRange) {
          const previousSync = syncingRange;
          syncingRange = true;
          try { available = this.chart.setTimeRange(sharedRange.start, sharedRange.end); }
          finally { syncingRange = previousSync; }
        }
        if (!available) {
          error.textContent = "공통 기간에 " + this.period.label + " 데이터가 없습니다.";
          error.classList.add("visible");
          return;
        }
        error.classList.remove("visible");
        this.showLast();
      },
      applyComparisons() {
        const selected = [...this.comparisons.values()];
        this.chart.setComparisons(selected.map(item => ({
          label:item.symbol, bars:item.series[this.period.key] || []
        })), this.payload.symbol);
        const active = selected.length > 0;
        const axis = find(".pane-mode");
        if (active && axis.value === "price") axis.value = "percent";
        axis.querySelector('option[value="price"]').disabled = active;
        this.chart.setPriceScale(axis.value);
        this.chart.setComparisonMode(axis.value);
        find(".chart-type").disabled = active;
        find(".indicator-trigger").disabled = active;
        find(".trend-button").disabled = active;
        find(".clear-button").disabled = active;
        find(".indicator-menu").hidden = true;
        if (active) {
          this.chart.setTool("crosshair");
          find(".trend-button").classList.remove("active");
        }
        this.chart.setIndicators(active ? [] : Array.from(activeIndicators, ([id, params]) => ({id, params})));
        this.chart.setStyle({showVolume:!this.payload.ratio && !active});
        find(".volume-caption").hidden = Boolean(this.payload.ratio || active);
        this.showLast();
        const chips = find(".pane-chips");
        chips.replaceChildren();
        selected.forEach((item, chipIndex) => {
          const chip = document.createElement("span");
          chip.className = "comparison-chip";
          chip.style.color = ["#d99000","#8b5cf6","#10b981","#ec4899","#06b6d4"][chipIndex];
          const label = document.createElement("span");
          label.textContent = item.symbol;
          const remove = document.createElement("button");
          remove.type = "button";
          remove.textContent = "×";
          remove.setAttribute("aria-label", item.symbol + " 비교 제거");
          remove.addEventListener("click", () => {
            this.comparisons.delete(item.symbol);
            this.applyComparisons();
          });
          chip.append(label, remove);
          chips.appendChild(chip);
        });
        placeVolumeLabel();
      },
      showLast() {
        const bars = this.chart.data;
        if (!bars.length) { readout.textContent = ""; return; }
        const visible = this.chart.visibleBars(this.chart.geometry());
        const hit = visible[visible.length - 1] || {bar:bars[bars.length - 1], index:bars.length - 1};
        showBar(hit.bar, hit.index);
        if (this.chart.comparisons.length && !readout.childNodes.length)
          readout.textContent = "현재 구간에 공통 시각의 봉이 없습니다";
      },
      async applyDefault(config, primaryPayload) {
        const sequence = ++this.sequence;
        this.period = periods.find(item => item.key === config.interval) || periods[0];
        find(".pane-interval").value = this.period.key;
        find(".pane-title").textContent = String(index + 1) + " · " + this.period.label;
        find(".pane-mode").value = config.axis;
        find(".chart-type").value = config.mode || "candles";
        this.chart.setStyle({mode:config.mode || "candles"});
        this.chart.clearLines();
        this.chart.setTool("crosshair");
        find(".trend-button").classList.remove("active");
        this.comparisons.clear();
        this.setPayload(emptyPayload(config.expression, ["종목 일봉","종목 / 섹터","섹터 / S&P500","종목 · 섹터 · S&P500 비교"][index]));
        const error = find(".chart-error");
        if (config.error) {
          error.textContent = config.error;
          error.classList.add("visible");
          return {ok:false, configuration:true};
        }
        error.textContent = "기본 구성을 불러오는 중…";
        error.classList.add("visible");
        try {
          const requested = config.comparisons || [];
          const [payload, ...compared] = await Promise.all([
            config.expression === primaryPayload.symbol ? Promise.resolve(primaryPayload) : resolveExpression(config.expression),
            ...requested.map(fetchPayload)
          ]);
          if (sequence !== this.sequence) return {ok:true, cancelled:true};
          compared.forEach(item => this.comparisons.set(item.symbol, item));
          this.setPayload(payload);
          return {ok:true};
        } catch (exception) {
          if (sequence !== this.sequence) return {ok:true, cancelled:true};
          error.textContent = exception.message;
          error.classList.add("visible");
          this.message("기본 구성의 시세를 불러오지 못했습니다. 종목을 바꾸거나 다시 적용할 수 있습니다.");
          return {ok:false};
        }
      },
      setPayload(payload) {
        this.payload = payload;
        find(".pane-symbol").value = payload.symbol;
        find(".symbol-badge").textContent = payload.symbol.charAt(0);
        find(".instrument-name").textContent = payload.name;
        find(".exchange-name").textContent = (payload.market ? "· " + payload.market : "") + (payload.asset_type === "ETF" ? " · ETF" : "");
        this.loading = true;
        this.chart.setData(payload.series[this.period.key] || []);
        this.loading = false;
        this.applyComparisons();
        this.applyRange();
        if (!sharedRange && this.chart.data.length)
          updateSharedRange(this.chart.getVisibleTimeRange().start, this.chart.getVisibleTimeRange().end);
        this.message("");
      },
      async loadSymbol(value) {
        const sequence = ++this.sequence;
        this.message("시세를 불러오는 중…");
        try {
          const payload = await resolveExpression(value);
          if (sequence !== this.sequence) return;
          this.setPayload(payload);
        } catch (error) {
          if (sequence === this.sequence) this.message(error.message);
        }
      },
      async addComparison(value) {
        if (this.comparisons.size >= 5) { this.message("비교 종목은 최대 5개입니다."); return; }
        const sequence = this.sequence;
        try {
          const tokens = parseExpression(value);
          if (tokens.length !== 1) throw new Error("비교 입력에는 종목 하나를 넣어 주세요.");
          const payload = await fetchPayload(tokens[0]);
          if (sequence !== this.sequence) return;
          if (this.comparisons.has(payload.symbol)) {
            this.message("이미 추가한 비교 종목입니다."); return;
          }
          this.comparisons.set(payload.symbol, payload);
          this.applyComparisons();
          find(".pane-compare").value = "";
          this.message("");
        } catch (error) { this.message(error.message); }
      }
    };
    function showBar(bar, barIndex, point) {
      if (!bar) return;
      readout.replaceChildren();
      tooltip.replaceChildren();
      const date = document.createElement("strong");
      date.textContent = new Intl.DateTimeFormat("ko-KR",
        {year:"numeric",month:"long",day:"numeric"}).format(new Date(bar.time));
      tooltip.appendChild(date);
      if (pane.chart.comparisons.length) {
        for (const item of pane.chart.comparisonAt(barIndex)) {
          const text = item.label + " " + (item.value == null ? "—" :
            item.value.toFixed(2) + (pane.chart.comparisonMode === "percent" ? "%" : ""));
          const span = document.createElement("span");
          span.style.color = item.color;
          span.textContent = text;
          readout.appendChild(span);
          const line = span.cloneNode(true);
          tooltip.appendChild(line);
        }
      } else {
        const fields = [["시",bar.open],["고",bar.high],["저",bar.low],["종",bar.close]];
        for (const [label, value] of fields) {
          const span = document.createElement("span");
          span.textContent = label + " " + pane.chart.formatAxisPrice(value);
          if (label === "종") span.className = bar.close >= bar.open ? "positive" : "negative";
          readout.appendChild(span);
          const line = document.createElement("span");
          line.textContent = label + "  " + pane.chart.formatAxisPrice(value);
          tooltip.appendChild(line);
        }
        if (pane.chart.priceScaleMode !== "price") {
          const rawPrice = document.createElement("span");
          rawPrice.textContent = "실제 종가  " + number(bar.close) + (pane.payload.currency ? " " + pane.payload.currency : "");
          tooltip.appendChild(rawPrice);
        }
        if (!pane.payload.ratio) {
          find(".volume-caption span").textContent = volume(bar.volume);
          const line = document.createElement("span");
          line.textContent = "거래량  " + volume(bar.volume);
          tooltip.appendChild(line);
        }
        for (const result of pane.chart.indicatorResults) {
          for (const series of result.lines) {
            const value = series.values[barIndex];
            if (!Number.isFinite(value)) continue;
            const line = document.createElement("span");
            line.textContent = result.name + " " + series.label + "  " +
              (result.pane === "overlay" ? pane.chart.formatAxisPrice(value) : number(value));
            tooltip.appendChild(line);
          }
        }
      }
      if (!point) { tooltip.hidden = true; return; }
      tooltip.hidden = false;
      tooltip.style.left = Math.max(4, Math.min(point.x + 18, stage.clientWidth - tooltip.offsetWidth - 8)) + "px";
      tooltip.style.top = Math.max(4, Math.min(point.y + 12, stage.clientHeight - tooltip.offsetHeight - 8)) + "px";
    }
    pane.chart = new window.CandlestickChart(find("canvas"), {
      onHover:showBar,
      onViewChange:range => {
        if (syncingRange || pane.loading || !range) return;
        updateSharedRange(range.start, range.end, pane);
      },
      onLeave:() => {
        tooltip.hidden = true;
        pane.showLast();
      }
    });
    pane.chart.setStyle({dark:FinanceUI.isDark()});
    function placeVolumeLabel() {
      const caption = find(".volume-caption");
      if (caption.hidden) return;
      caption.style.top = Math.max(0, pane.chart.geometry().volumeTop + 5) + "px";
      caption.style.bottom = "auto";
    }
    new ResizeObserver(placeVolumeLabel).observe(stage);
    find(".pane-title").textContent = String(index + 1) + " · " + period.label;
    find(".pane-interval").value = period.key;
    find(".pane-interval").addEventListener("change", event => {
      pane.period = periods.find(item => item.key === event.target.value);
      find(".pane-title").textContent = String(index + 1) + " · " + pane.period.label;
      pane.setPayload(pane.payload);
    });
    find(".apply-symbol").addEventListener("click", () => pane.loadSymbol(find(".pane-symbol").value));
    find(".pane-symbol").addEventListener("keydown", event => {
      if (event.key === "Enter") pane.loadSymbol(event.currentTarget.value);
    });
    find(".add-comparison").addEventListener("click", () => pane.addComparison(find(".pane-compare").value));
    find(".pane-compare").addEventListener("keydown", event => {
      if (event.key === "Enter") pane.addComparison(event.currentTarget.value);
    });
    find(".pane-mode").addEventListener("change", () => pane.applyComparisons());
    find(".chart-type").addEventListener("change", event => pane.chart.setStyle({mode:event.target.value}));
    find(".fit-button").addEventListener("click", () => {
      pane.chart.setVisibleCount(Math.min(pane.period.visible, pane.chart.data.length));
      pane.chart.rightOffset = 0;
      pane.chart.schedule();
      const range = pane.chart.getVisibleTimeRange();
      if (range) updateSharedRange(range.start, range.end, pane);
    });
    find(".trend-button").addEventListener("click", event => {
      const active = event.currentTarget.classList.toggle("active");
      pane.chart.setTool(active ? "trendline" : "crosshair");
    });
    find(".clear-button").addEventListener("click", () => pane.chart.clearLines());
    const menu = find(".indicator-menu");
    const trigger = find(".indicator-trigger");
    const heading = document.createElement("div");
    heading.className = "indicator-menu-title";
    heading.textContent = "지표";
    menu.appendChild(heading);
    function applyIndicators() {
      pane.chart.setIndicators(pane.chart.comparisons.length ? [] :
        Array.from(activeIndicators, ([id, params]) => ({id, params})));
      trigger.textContent = activeIndicators.size ? "지표 " + activeIndicators.size : "지표 +";
      trigger.classList.toggle("active", activeIndicators.size > 0);
      placeVolumeLabel();
    }
    for (const definition of window.ChartIndicators.list()) {
      const row = document.createElement("div");
      row.className = "indicator-row";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.id = "pane-" + index + "-" + definition.id;
      const label = document.createElement("label");
      label.className = "indicator-name";
      label.htmlFor = checkbox.id;
      label.textContent = definition.name;
      const description = document.createElement("span");
      description.className = "indicator-description";
      description.textContent = definition.description || "";
      label.appendChild(description);
      const parameters = document.createElement("div");
      parameters.className = "indicator-params";
      const inputs = [];
      for (const field of definition.parameters) {
        const fieldLabel = document.createElement("label");
        const input = document.createElement("input");
        input.type = "number";
        input.id = checkbox.id + "-" + field.key;
        input.min = field.min ?? 1;
        input.max = field.max ?? 200;
        input.step = field.step ?? 1;
        input.value = field.default;
        fieldLabel.htmlFor = input.id;
        fieldLabel.textContent = field.label;
        parameters.append(fieldLabel, input);
        inputs.push([field.key, input]);
      }
      const update = () => {
        if (checkbox.checked) activeIndicators.set(definition.id,
          Object.fromEntries(inputs.map(([key, input]) => [key, Number(input.value)])));
        else activeIndicators.delete(definition.id);
        applyIndicators();
      };
      checkbox.addEventListener("change", update);
      for (const [, input] of inputs) input.addEventListener("change", () => {
        checkbox.checked = true; update();
      });
      row.append(checkbox, label, parameters);
      menu.appendChild(row);
    }
    trigger.addEventListener("click", () => {
      menu.hidden = !menu.hidden;
      trigger.setAttribute("aria-expanded", String(!menu.hidden));
    });
    document.addEventListener("pointerdown", event => {
      if (!menu.hidden && !menu.contains(event.target) && event.target !== trigger) {
        menu.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
      }
    });
    find(".pane-mode").value = options.axis || "price";
    find(".chart-type").value = options.mode || "candles";
    pane.chart.setStyle({mode:options.mode || "candles"});
    pane.setPayload(initialPayload);
    panes.push(pane);
    return pane;
  }

  function applyDateRange(start, end) {
    if (!start || !end) { setSharedMessage("시작 날짜와 종료 날짜를 입력해 주세요."); return false; }
    const startMs = new Date(start + "T00:00:00").getTime();
    const endMs = new Date(end + "T23:59:59.999").getTime();
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || startMs > endMs) {
      setSharedMessage("기간을 다시 확인해 주세요."); return false;
    }
    return updateSharedRange(startMs, endMs);
  }

  const copyImageButton = document.getElementById("copyChartImage");
  const saveImageButton = document.getElementById("saveChartImage");
  const exportMessage = document.getElementById("exportMessage");

  function setExportEnabled(enabled) {
    copyImageButton.disabled = !enabled;
    saveImageButton.disabled = !enabled;
  }

  function copyRenderedStyles(source, target) {
    const style = getComputedStyle(source);
    for (const property of style) {
      target.style.setProperty(property, style.getPropertyValue(property));
    }
    // The detached snapshot has no stylesheet or body theme to inherit from.
    target.style.setProperty("animation", "none");
    target.style.setProperty("transition", "none");
  }

  function cloneChartSurface(source, images) {
    if (source.nodeType === Node.TEXT_NODE) return source.cloneNode();
    if (source.nodeType !== Node.ELEMENT_NODE) return null;
    if (source.matches(".pane-config, .pane-toolbar, .indicator-menu, .chart-tooltip")) return null;
    const image = images.get(source);
    const clone = image ? document.createElement("img") : source.cloneNode(false);
    clone.removeAttribute("id");
    copyRenderedStyles(source, clone);
    if (image) {
      clone.src = image.toDataURL("image/png");
      clone.alt = source.getAttribute("aria-label") || "차트";
      clone.style.objectFit = "fill";
    } else {
      for (const child of source.childNodes) {
        const copied = cloneChartSurface(child, images);
        if (copied) clone.appendChild(copied);
      }
    }
    return clone;
  }

  async function makeFourChartImage() {
    if (panes.length !== 4) throw new Error("네 차트가 준비된 후 다시 시도해 주세요.");
    // Freeze the actual CSS layout and chart geometry. Only export pixel density
    // changes; no fixed-size chart, alternative header, or replacement legend.
    const pixelRatio = Math.max(2, Math.min(3, window.devicePixelRatio || 1));
    const gridRect = grid.getBoundingClientRect();
    if (!gridRect.width || !gridRect.height) throw new Error("차트 화면을 표시한 뒤 다시 시도해 주세요.");
    const images = new Map();
    const layout = panes.map(pane => {
      const panel = pane.panel.getBoundingClientRect();
      const stage = pane.panel.querySelector(".chart-stage").getBoundingClientRect();
      const config = pane.panel.querySelector(".pane-config").getBoundingClientRect();
      images.set(pane.chart.canvas, pane.chart.renderImage({
        width:pane.chart.width, height:pane.chart.height, pixelRatio
      }));
      return {top:panel.top, height:panel.height - config.height, stageHeight:stage.height};
    });
    const snapshot = cloneChartSurface(grid, images);
    const rowHeights = [];
    const rowTops = [];
    layout.forEach(item => {
      let row = rowTops.findIndex(top => Math.abs(top - item.top) < 1);
      if (row < 0) { row = rowTops.length; rowTops.push(item.top); rowHeights.push(0); }
      rowHeights[row] = Math.max(rowHeights[row], item.height);
    });
    const gridStyle = getComputedStyle(grid);
    const gap = parseFloat(gridStyle.rowGap) || 0;
    const padding = (parseFloat(gridStyle.paddingTop) || 0) + (parseFloat(gridStyle.paddingBottom) || 0);
    const borders = (parseFloat(gridStyle.borderTopWidth) || 0) + (parseFloat(gridStyle.borderBottomWidth) || 0);
    const height = Math.ceil(rowHeights.reduce((sum, value) => sum + value, 0) + gap * (rowHeights.length - 1) + padding + borders);
    const width = Math.ceil(gridRect.width);
    Object.assign(snapshot.style, {
      width:gridRect.width + "px", height:height + "px", minHeight:"0", maxHeight:"none",
      position:"relative", inset:"auto", margin:"0", flex:"none",
      gridTemplateRows:rowHeights.map(value => value + "px").join(" ")
    });
    Array.from(snapshot.children).forEach((panel, index) => {
      panel.style.height = layout[index].height + "px";
      panel.style.minHeight = "0";
      panel.style.flex = "none";
      panel.style.alignSelf = "start";
      const stage = panel.querySelector(".chart-stage");
      stage.style.height = layout[index].stageHeight + "px";
      stage.style.minHeight = "0";
      stage.style.flex = "none";
    });
    const markup = new XMLSerializer().serializeToString(snapshot);
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + width + '" height="' + height +
      '" viewBox="0 0 ' + width + ' ' + height + '"><foreignObject x="0" y="0" width="100%" height="100%">' +
      markup + '</foreignObject></svg>';
    const rendered = new Image();
    // A self-contained SVG data URL keeps all chart bitmaps local and exportable.
    await new Promise((resolve, reject) => {
      rendered.onload = resolve;
      rendered.onerror = () => reject(new Error("화면 디자인을 이미지로 변환하지 못했습니다."));
      rendered.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    });
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(width * pixelRatio);
    canvas.height = Math.round(height * pixelRatio);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    ctx.drawImage(rendered, 0, 0, width, height);
    return canvas;
  }

  async function chartImageBlob() {
    const canvas = await makeFourChartImage();
    return new Promise((resolve, reject) => canvas.toBlob(blob => {
      if (blob) resolve(blob);
      else reject(new Error("차트 이미지를 만들지 못했습니다."));
    }, "image/png"));
  }

  copyImageButton.addEventListener("click", async () => {
    if (!navigator.clipboard || !navigator.clipboard.write || !window.ClipboardItem) {
      exportMessage.textContent = "이 브라우저에서는 이미지 복사를 지원하지 않습니다. PNG 저장을 이용해 주세요.";
      return;
    }
    setExportEnabled(false);
    exportMessage.textContent = "이미지를 복사하는 중…";
    try {
      // Pass the image promise immediately to preserve browser user activation.
      const pendingImage = chartImageBlob();
      await navigator.clipboard.write([new ClipboardItem({"image/png":pendingImage})]);
      exportMessage.textContent = "네 차트 이미지를 복사했습니다.";
    } catch (error) {
      exportMessage.textContent = error.name === "NotAllowedError" ?
        "이미지 복사 권한이 필요합니다. 브라우저 권한을 확인하거나 PNG 저장을 이용해 주세요." :
        (error.message || "이미지 복사에 실패했습니다.");
    } finally { setExportEnabled(panes.length === 4); }
  });

  saveImageButton.addEventListener("click", async () => {
    setExportEnabled(false);
    exportMessage.textContent = "이미지를 저장하는 중…";
    let url;
    try {
      const blob = await chartImageBlob();
      url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "charts-4panel-" + dateStart.value + "-" + dateEnd.value + ".png";
      document.body.appendChild(link);
      link.click();
      link.remove();
      exportMessage.textContent = "PNG 이미지를 저장했습니다.";
    } catch (error) {
      exportMessage.textContent = error.message || "이미지 저장에 실패했습니다.";
    } finally {
      if (url) setTimeout(() => URL.revokeObjectURL(url), 1000);
      setExportEnabled(panes.length === 4);
    }
  });

  const catalogButton = document.getElementById("refreshCatalog");
  const catalogMessage = document.getElementById("catalogMessage");
  const catalogUpdate = (state, label, message) => FinanceUI.update(catalogButton, state, label, message, catalogMessage);
  let catalogPolling = false;
  async function pollCatalog() {
    if (catalogPolling) return;
    catalogPolling = true;
    try {
      const response = await fetch("/api/instruments/status", {cache:"no-store"});
      if (!response.ok) throw new Error("ETF 목록 상태를 확인하지 못했습니다.");
      const status = await response.json();
      if (status.state === "running") {
        catalogUpdate("running", "ETF 목록 수집 중…", "차트에서 검색할 ETF 목록을 업데이트합니다.");
        setTimeout(pollCatalog, 1500);
      } else if (status.state === "error") {
        catalogUpdate("error", "ETF 목록 재시도", status.error || "목록 업데이트 실패 · 저장된 목록은 계속 사용할 수 있습니다.");
      } else if (catalogButton.dataset.state === "running") {
        if (status.state === "done") {
          const count = status.counts && status.counts.ETF || 0;
          const partial = status.sources && status.sources.some(source => !source.ok);
          catalogUpdate("success", "ETF 목록 업데이트", "업데이트 완료 · ETF " + count + "개" + (partial ? " · 일부 목록 조회 실패" : ""));
        } else {
          catalogUpdate("idle", "ETF 목록 업데이트", "진행 중인 업데이트가 없습니다. 다시 시작할 수 있습니다.");
        }
      }
    } catch (error) {
      if (catalogButton.dataset.state === "running") {
        catalogUpdate("running", "ETF 목록 수집 중…", "연결을 다시 확인하고 있습니다.");
        setTimeout(pollCatalog, 5000);
      } else { catalogUpdate("error", "ETF 목록 재시도", error.message); }
    } finally { catalogPolling = false; }
  }
  catalogButton.addEventListener("click", async () => {
    if (catalogButton.disabled) return;
    catalogUpdate("running", "ETF 목록 수집 중…", "ETF 목록 업데이트를 시작합니다.");
    try {
      const response = await fetch("/api/instruments/refresh", {method:"POST"});
      if (!response.ok) throw new Error("ETF 목록 업데이트를 시작하지 못했습니다.");
      pollCatalog();
    } catch (error) { catalogUpdate("error", "ETF 목록 재시도", error.message); }
  });
  pollCatalog();

  window.addEventListener("finance-theme-change", event => {
    for (const pane of panes) pane.chart.setStyle({dark:event.detail.dark});
  });
  document.getElementById("applyRange").addEventListener("click", () =>
    applyDateRange(dateStart.value, dateEnd.value));
  document.querySelectorAll("[data-range]").forEach(button => button.addEventListener("click", () => {
    const data = panes.flatMap(pane => pane.chart.data);
    if (!data.length) return;
    const end = Math.max(...data.map(bar => bar.time));
    const monthCount = {30:1, 90:3, 180:6, 365:12}[button.dataset.range];
    const start = button.dataset.range === "all" ? Math.min(...data.map(bar => bar.time)) :
      monthsBefore(end, monthCount);
    updateSharedRange(start, end);
  }));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") document.querySelectorAll(".indicator-menu").forEach(menu => {
      menu.hidden = true;
      menu.parentElement.querySelector(".indicator-trigger").setAttribute("aria-expanded", "false");
    });
  });
  window.screenChart = {
    loadSymbol(index, expression) {
      if (expression === undefined) { expression = index; index = 0; }
      return panes[index] && panes[index].loadSymbol(expression);
    },
    addComparison(index, symbol) {
      if (symbol === undefined) { symbol = index; index = 0; }
      return panes[index] && panes[index].addComparison(symbol);
    },
    setDateRange:applyDateRange
  };
  const initial = new URLSearchParams(location.search).get("symbol") || "AAPL";
  const templateButton = document.getElementById("applyChartDefaults");
  const templateMessage = document.getElementById("templateMessage");
  const settingsLink = document.getElementById("sectorEtfLink");
  settingsLink.href = "/sector-etfs?symbol=" + encodeURIComponent(initial);
  let templateSequence = 0;

  async function applyChartDefaults() {
    const sequence = ++templateSequence;
    templateButton.disabled = true;
    setExportEnabled(false);
    templateMessage.textContent = "종목의 섹터와 기본 구성을 불러오는 중…";
    try {
      const [payload, response] = await Promise.all([
        resolveExpression(initial), fetch("/api/chart-defaults?symbol=" + encodeURIComponent(initial))
      ]);
      if (sequence !== templateSequence) return;
      let defaults;
      if (response.ok) defaults = await response.json();
      else if (response.status === 404) {
        const warning = "새 기본 구성을 적용하려면 서버를 재시작해 주세요.";
        defaults = {months:6,warning,panes:Array.from({length:4}, (_, index) => ({
          expression:payload.symbol, interval:"daily", axis:index ? "index100" : "price", mode:index ? "line" : "candles",
          comparisons:[], error:index ? warning : ""
        }))};
      } else {
        const failure = await response.json();
        throw new Error(failure.error || "기본 구성을 불러오지 못했습니다.");
      }
      settingsLink.href = defaults.settings_url || settingsLink.href;
      const bars = payload.series.daily || [];
      if (!bars.length) throw new Error("종목의 일봉 데이터가 없습니다.");
      const end = bars[bars.length - 1].time;
      updateSharedRange(monthsBefore(end, defaults.months || 6), end);
      if (!panes.length) defaults.panes.forEach((config, index) =>
        makePane(index, emptyPayload(config.expression), config));
      document.title = "4분할 차트 · " + payload.symbol;
      const results = await Promise.all(defaults.panes.map((config, index) =>
        panes[index].applyDefault(config, payload)));
      if (sequence !== templateSequence) return;
      const industrySummary = defaults.industry ? "산업: " + (defaults.industry.path_label || "미분류") + " · " + defaults.industry.status_label : "";
      const summary = defaults.sector_etf ? "비교: " + payload.symbol + " · " + defaults.sector +
        " → " + defaults.sector_etf + " · S&P500 " + defaults.benchmark : "";
      templateMessage.textContent = [industrySummary, defaults.warning ? defaults.warning : summary].filter(Boolean).join(" · ") +
        (results.some(result => !result.ok) && !defaults.warning ? " · 일부 차트의 시세 조회에 실패했습니다." : "");
      setSharedMessage("");
    } catch (error) {
      if (sequence === templateSequence) templateMessage.textContent = error.message;
    } finally {
      if (sequence === templateSequence) {
        templateButton.disabled = false;
        setExportEnabled(panes.length === 4);
      }
    }
  }
  templateButton.addEventListener("click", applyChartDefaults);
  window.screenChart.applyDefaults = applyChartDefaults;
  applyChartDefaults();
})();
