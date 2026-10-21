/* Reusable canvas chart. Input bars: {time, open, high, low, close, volume}. */
(function () {
  "use strict";

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const round = value => Math.round(value * 100) / 100;

  class CandlestickChart {
    constructor(canvas, options = {}) {
      if (!(canvas instanceof HTMLCanvasElement)) throw new TypeError("canvas must be an HTMLCanvasElement");
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.data = [];
      this.comparisons = [];
      this.primaryLabel = "기준 종목";
      this.comparisonMode = "percent";
      this.priceScaleMode = "price";
      this.onViewChange = options.onViewChange || (() => {});
      this.visibleCount = 130;
      this.rightOffset = 0;
      this.mode = "candles";
      this.indicatorConfigs = [];
      this.indicatorResults = [];
      this.dark = false;
      this.showVolume = true;
      this.tool = "crosshair";
      this.lines = [];
      this.lineStart = null;
      this.pointer = null;
      this.drag = null;
      this.onHover = options.onHover || (() => {});
      this.onLeave = options.onLeave || (() => {});
      this.frame = 0;
      this.width = 1;
      this.height = 1;
      this.dpr = 1;
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(canvas);
      this.handlers = {
        pointerdown: event => this.handlePointerDown(event),
        pointermove: event => this.handlePointerMove(event),
        pointerup: event => this.handlePointerUp(event),
        pointerleave: () => this.handlePointerLeave(),
        wheel: event => this.handleWheel(event),
        dblclick: () => this.fit(),
        contextmenu: event => event.preventDefault()
      };
      for (const [name, handler] of Object.entries(this.handlers)) canvas.addEventListener(name, handler, name === "wheel" ? {passive: false} : undefined);
      this.resize();
    }

    setData(bars, options = {}) {
      if (!Array.isArray(bars)) throw new TypeError("bars must be an array");
      this.data = bars.filter(bar => {
        const fields = ["time", "open", "high", "low", "close", "volume"];
        return fields.every(field => Number.isFinite(Number(bar[field]))) &&
          Number(bar.high) >= Math.max(Number(bar.open), Number(bar.close), Number(bar.low)) &&
          Number(bar.low) <= Math.min(Number(bar.open), Number(bar.close), Number(bar.high)) &&
          Number(bar.volume) >= 0;
      }).map(bar => ({
        time: Number(bar.time), open: Number(bar.open), high: Number(bar.high),
        low: Number(bar.low), close: Number(bar.close), volume: Number(bar.volume)
      })).sort((a, b) => a.time - b.time);
      this.data = this.data.filter((bar, index, all) => index === 0 || bar.time !== all[index - 1].time);
      this.recalculateIndicators();
      if (options.fit !== false) this.fit();
      else this.schedule();
    }

    setStyle({mode, dark, showVolume} = {}) {
      if (mode !== undefined) this.mode = mode === "line" ? "line" : "candles";
      if (dark !== undefined) this.dark = Boolean(dark);
      if (showVolume !== undefined) this.showVolume = Boolean(showVolume);
      this.schedule();
    }

    setIndicators(configs) {
      if (!Array.isArray(configs)) throw new TypeError("configs must be an array");
      this.indicatorConfigs = configs.map(config => ({id: config.id, params: {...(config.params || {})}}));
      this.recalculateIndicators();
      this.schedule();
    }

    recalculateIndicators() {
      this.indicatorResults = window.ChartIndicators
        ? window.ChartIndicators.calculate(this.indicatorConfigs, this.data) : [];
    }

    setTool(tool) {
      this.tool = tool === "trendline" ? "trendline" : "crosshair";
      this.lineStart = null;
      this.canvas.parentElement.classList.toggle("drawing", this.tool === "trendline");
      this.schedule();
    }

    setVisibleCount(count) {
      if (!this.data.length) return;
      this.visibleCount = clamp(Math.round(count), Math.min(12, this.data.length), this.data.length);
      this.rightOffset = clamp(this.rightOffset, 0, Math.max(0, this.data.length - this.visibleCount));
      this.schedule();
      this.onViewChange(this.getVisibleTimeRange());
    }

    fit() {
      this.visibleCount = Math.min(130, Math.max(1, this.data.length));
      this.rightOffset = 0;
      this.schedule();
      this.onViewChange(this.getVisibleTimeRange());
    }

    setComparisons(sets, primaryLabel = "기준 종목") {
      if (!Array.isArray(sets)) throw new TypeError("comparisons must be an array");
      this.comparisons = sets.slice(0, 5).map((set, index) => ({
        label: String(set.label || "비교 " + (index + 1)),
        closes: new Map((set.bars || []).filter(bar =>
          Number.isFinite(Number(bar.time)) && Number.isFinite(Number(bar.close)) && Number(bar.close) > 0
        ).map(bar => [Number(bar.time), Number(bar.close)]))
      }));
      this.primaryLabel = String(primaryLabel);
      if (this.comparisons.length) this.setTool("crosshair");
      this.schedule();
    }

    setComparisonMode(mode) {
      this.comparisonMode = mode === "index100" ? "index100" : "percent";
      this.schedule();
    }

    setPriceScale(mode) {
      this.priceScaleMode = ["percent", "index100"].includes(mode) ? mode : "price";
      this.schedule();
    }

    priceBaseline(items = this.visibleBars(this.geometry())) {
      const first = items.find(({bar}) => Number.isFinite(bar.close) && bar.close > 0);
      return first ? first.bar.close : null;
    }

    priceValue(value, baseline = this.priceBaseline()) {
      if (this.priceScaleMode === "price") return value;
      if (!Number.isFinite(value) || !Number.isFinite(baseline) || baseline <= 0) return null;
      return this.priceScaleMode === "index100" ? value / baseline * 100 : (value / baseline - 1) * 100;
    }

    formatAxisPrice(value, baseline = this.priceBaseline()) {
      const converted = this.priceValue(value, baseline);
      if (!Number.isFinite(converted)) return "—";
      return this.formatPrice(converted) + (this.priceScaleMode === "percent" ? "%" : "");
    }

    getVisibleTimeRange() {
      if (!this.data.length) return null;
      const count = Math.min(this.visibleCount, this.data.length);
      const end = Math.max(0, this.data.length - 1 - this.rightOffset);
      const start = Math.max(0, end - count + 1);
      return {start: this.data[start].time, end: this.data[end].time};
    }

    setTimeRange(startMs, endMs) {
      if (!this.data.length || !Number.isFinite(startMs) || !Number.isFinite(endMs) || startMs > endMs)
        return false;
      const first = this.data.findIndex(bar => bar.time >= startMs && bar.time <= endMs);
      if (first < 0) return false;
      let last = first;
      for (let index = first + 1; index < this.data.length && this.data[index].time <= endMs; index++)
        last = index;
      this.visibleCount = last - first + 1;
      this.rightOffset = this.data.length - 1 - last;
      this.schedule();
      this.onViewChange(this.getVisibleTimeRange());
      return true;
    }

    comparisonSnapshot(items = this.visibleBars(this.geometry())) {
      if (!this.comparisons.length || !items.length) return null;
      const firstCommon = items.find(({bar}) => bar.close > 0 &&
        this.comparisons.every(set => set.closes.has(bar.time)));
      if (!firstCommon) return null;
      const baselineTime = firstCommon.bar.time;
      const baseValue = firstCommon.bar.close;
      const transform = (value, baseline) => this.comparisonMode === "index100"
        ? value / baseline * 100 : (value / baseline - 1) * 100;
      const colors = ["#2962ff", "#f59e0b", "#8b5cf6", "#10b981", "#ec4899", "#06b6d4"];
      const lines = [{label: this.primaryLabel, color: colors[0],
        values: new Map(items.map(({bar}) => [bar.time, transform(bar.close, baseValue)]))}];
      this.comparisons.forEach((set, index) => {
        const baseline = set.closes.get(baselineTime);
        lines.push({label: set.label, color: colors[index + 1], values: new Map(items
          .filter(({bar}) => set.closes.has(bar.time))
          .map(({bar}) => [bar.time, transform(set.closes.get(bar.time), baseline)]))});
      });
      return {baselineTime, lines};
    }

    comparisonAt(index) {
      const snapshot = this.comparisonSnapshot();
      const bar = this.data[index];
      if (!snapshot || !bar) return [];
      return snapshot.lines.map(line => ({label: line.label, color: line.color,
        value: line.values.get(bar.time) ?? null}));
    }

    clearLines() {
      this.lines = [];
      this.lineStart = null;
      this.schedule();
    }

    destroy() {
      this.resizeObserver.disconnect();
      for (const [name, handler] of Object.entries(this.handlers)) this.canvas.removeEventListener(name, handler);
      cancelAnimationFrame(this.frame);
    }

    resize() {
      const rect = this.canvas.getBoundingClientRect();
      this.width = Math.max(1, rect.width);
      this.height = Math.max(1, rect.height);
      this.dpr = Math.min(window.devicePixelRatio || 1, 3);
      this.canvas.width = Math.round(this.width * this.dpr);
      this.canvas.height = Math.round(this.height * this.dpr);
      this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      this.schedule();
    }

    schedule() {
      if (this.frame) cancelAnimationFrame(this.frame);
      this.frame = requestAnimationFrame(() => { this.frame = 0; this.draw(); });
    }

    renderImage({width = this.width, height = this.height, pixelRatio = 2} = {}) {
      const output = document.createElement("canvas");
      const w = Math.max(1, Math.round(width));
      const h = Math.max(1, Math.round(height));
      const ratio = Math.max(1, Math.min(3, pixelRatio));
      output.width = Math.round(w * ratio);
      output.height = Math.round(h * ratio);
      const state = {canvas:this.canvas, ctx:this.ctx, width:this.width, height:this.height,
        dpr:this.dpr, pointer:this.pointer, lineStart:this.lineStart, scale:this.scale};
      try {
        this.canvas = output;
        this.ctx = output.getContext("2d");
        this.width = w; this.height = h; this.dpr = ratio;
        this.pointer = null; this.lineStart = null;
        this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        this.draw();
      } finally {
        Object.assign(this, state);
      }
      return output;
    }

    geometry() {
      const left = 10, right = 72, top = 10, bottom = 28;
      const plotRight = Math.max(left + 1, this.width - right);
      const axisY = this.height - bottom;
      const usable = Math.max(120, axisY - top);
      const paneCount = this.indicatorResults.filter(result => result.pane === "pane").length;
      const paneHeight = paneCount ? Math.max(35, Math.min(110, usable * 0.16)) : 0;
      const volumeHeight = this.showVolume ? Math.max(30, Math.min(110, usable * 0.17)) : 0;
      const priceBottom = Math.max(top + 28, axisY - volumeHeight - paneCount * paneHeight - 12);
      const volumeTop = priceBottom + 12;
      const volumeBottom = Math.min(axisY - paneCount * paneHeight - 8, volumeTop + volumeHeight - 8);
      const paneRegions = Array.from({length:paneCount}, (_, index) => {
        const top = axisY - (paneCount - index) * paneHeight;
        return {top, bottom:Math.min(axisY - 5, top + paneHeight - 8)};
      });
      const count = Math.max(1, this.visibleCount);
      const barWidth = (plotRight - left) / count;
      const first = this.data.length - count - this.rightOffset;
      const xAt = index => left + (index - first + 0.5) * barWidth;
      return {left, right, top, bottom, plotRight, volumeTop, volumeBottom, priceBottom, paneRegions, count, barWidth, first, xAt};
    }

    visibleBars(g) {
      const start = Math.max(0, Math.floor(g.first));
      const end = Math.min(this.data.length, Math.ceil(g.first + g.count));
      return this.data.slice(start, end).map((bar, position) => ({bar, index: start + position}));
    }

    palette() {
      return this.dark
        ? {background:"#171e2b", grid:"#273243", text:"#90a0b7", axis:"#344154", up:"#16b897", down:"#f45b69", blue:"#7da8ff", cross:"#8090a8", volumeUp:"#23695e", volumeDown:"#7a3e4b"}
        : {background:"#ffffff", grid:"#eef1f5", text:"#8a96a8", axis:"#e4e9ef", up:"#089981", down:"#f23645", blue:"#2962ff", cross:"#a8b3c2", volumeUp:"#9ad9ce", volumeDown:"#f6b1b7"};
    }

    draw() {
      const ctx = this.ctx, g = this.geometry(), c = this.palette();
      ctx.clearRect(0, 0, this.width, this.height);
      ctx.fillStyle = c.background;
      ctx.fillRect(0, 0, this.width, this.height);
      if (!this.data.length) {
        ctx.fillStyle = c.text; ctx.font = "13px sans-serif"; ctx.textAlign = "center";
        ctx.fillText("차트 데이터가 없습니다", this.width / 2, this.height / 2);
        return;
      }
      const items = this.visibleBars(g);
      if (!items.length) return;
      if (this.comparisons.length) { this.drawComparison(ctx, g, c, items); return; }
      const baseline = this.priceBaseline(items);
      const axisLabel = value => this.formatAxisPrice(value, baseline);
      const lows = items.map(item => item.bar.low), highs = items.map(item => item.bar.high);
      for (const result of this.indicatorResults.filter(result => result.pane === "overlay")) {
        for (const line of result.lines) for (const item of items) {
          const value = line.values[item.index];
          if (Number.isFinite(value)) {lows.push(value); highs.push(value);}
        }
      }
      let low = Math.min(...lows), high = Math.max(...highs);
      const padding = Math.max((high - low) * 0.08, Math.abs(high) * 0.002, 0.01);
      low -= padding; high += padding;
      const priceY = price => g.top + (high - price) / (high - low) * (g.priceBottom - g.top);
      const priceAt = y => high - (y - g.top) / (g.priceBottom - g.top) * (high - low);
      this.scale = {g, low, high, priceY, priceAt};

      ctx.font = "11px Inter, sans-serif";
      ctx.textBaseline = "middle";
      ctx.strokeStyle = c.grid; ctx.lineWidth = 1;
      for (let step = 0; step <= 5; step++) {
        const y = g.top + (g.priceBottom - g.top) * step / 5;
        ctx.beginPath(); ctx.moveTo(g.left, Math.round(y) + 0.5); ctx.lineTo(g.plotRight, Math.round(y) + 0.5); ctx.stroke();
        ctx.fillStyle = c.text; ctx.textAlign = "left";
        ctx.fillText(axisLabel(high - (high - low) * step / 5), g.plotRight + 8, y);
      }
      ctx.strokeStyle = c.axis;
      ctx.beginPath(); ctx.moveTo(g.plotRight + 0.5, 0); ctx.lineTo(g.plotRight + 0.5, this.height); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, this.height - g.bottom + 0.5); ctx.lineTo(this.width, this.height - g.bottom + 0.5); ctx.stroke();

      const tickEvery = Math.max(1, Math.ceil(90 / g.barWidth));
      ctx.textAlign = "center"; ctx.fillStyle = c.text;
      for (const item of items) {
        if (item.index % tickEvery !== 0) continue;
        const x = g.xAt(item.index);
        ctx.strokeStyle = c.grid;
        ctx.beginPath(); ctx.moveTo(Math.round(x) + 0.5, g.top); ctx.lineTo(Math.round(x) + 0.5, this.height - g.bottom); ctx.stroke();
        ctx.fillStyle = c.text;
        ctx.fillText(this.formatDate(item.bar.time), x, this.height - 14);
      }

      const maxVolume = Math.max(1, ...items.map(item => item.bar.volume));
      if (this.showVolume) for (const {bar, index} of items) {
        const x = g.xAt(index), rising = bar.close >= bar.open;
        const bodyWidth = Math.max(1, Math.min(g.barWidth * 0.67, 18));
        const volHeight = bar.volume / maxVolume * Math.max(1, g.volumeBottom - g.volumeTop);
        ctx.fillStyle = rising ? c.volumeUp : c.volumeDown;
        ctx.fillRect(Math.round(x - bodyWidth / 2), g.volumeBottom - volHeight, Math.max(1, Math.round(bodyWidth)), volHeight);
      }

      ctx.save(); ctx.beginPath(); ctx.rect(g.left, g.top, g.plotRight - g.left, g.priceBottom - g.top); ctx.clip();
      if (this.mode === "line") {
        ctx.beginPath();
        items.forEach(({bar, index}, position) => {
          const x = g.xAt(index), y = priceY(bar.close);
          if (position === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.strokeStyle = c.blue; ctx.lineWidth = 2; ctx.stroke();
      } else {
        for (const {bar, index} of items) {
          const x = g.xAt(index), rising = bar.close >= bar.open;
          const yOpen = priceY(bar.open), yClose = priceY(bar.close);
          const bodyWidth = Math.max(1, Math.min(g.barWidth * 0.67, 18));
          ctx.strokeStyle = rising ? c.up : c.down;
          ctx.fillStyle = ctx.strokeStyle;
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(Math.round(x) + 0.5, priceY(bar.high)); ctx.lineTo(Math.round(x) + 0.5, priceY(bar.low)); ctx.stroke();
          ctx.fillRect(Math.round(x - bodyWidth / 2), Math.min(yOpen, yClose), Math.max(1, Math.round(bodyWidth)), Math.max(1, Math.abs(yClose - yOpen)));
        }
      }

      this.drawOverlayIndicators(ctx, g, items, priceY);

      const drawLine = (a, b, dashed = false) => {
        if (!a || !b) return;
        ctx.save(); if (dashed) ctx.setLineDash([5, 4]);
        ctx.beginPath(); ctx.moveTo(g.xAt(a.index), priceY(a.price)); ctx.lineTo(g.xAt(b.index), priceY(b.price));
        ctx.strokeStyle = c.blue; ctx.lineWidth = 2; ctx.stroke(); ctx.restore();
        for (const point of [a, b]) {
          ctx.beginPath(); ctx.arc(g.xAt(point.index), priceY(point.price), 3, 0, Math.PI * 2);
          ctx.fillStyle = c.background; ctx.fill(); ctx.strokeStyle = c.blue; ctx.stroke();
        }
      };
      for (const line of this.lines) drawLine(line[0], line[1]);
      if (this.lineStart && this.pointer) drawLine(this.lineStart, this.pointAt(this.pointer.x, this.pointer.y), true);
      ctx.restore();
      this.drawIndicatorPanes(ctx, g, c, items);

      const last = this.data[this.data.length - 1], lastY = priceY(last.close);
      if (lastY >= g.top && lastY <= g.priceBottom) {
        ctx.save(); ctx.setLineDash([3, 3]); ctx.strokeStyle = last.close >= last.open ? c.up : c.down;
        ctx.beginPath(); ctx.moveTo(g.left, Math.round(lastY) + 0.5); ctx.lineTo(g.plotRight, Math.round(lastY) + 0.5); ctx.stroke(); ctx.restore();
        ctx.fillStyle = last.close >= last.open ? c.up : c.down;
        ctx.fillRect(g.plotRight, lastY - 11, this.width - g.plotRight, 22);
        ctx.fillStyle = "#fff"; ctx.textAlign = "left"; ctx.font = "bold 11px Inter, sans-serif";
        ctx.fillText(axisLabel(last.close), g.plotRight + 7, lastY);
      }

      if (this.pointer && this.pointer.x >= g.left && this.pointer.x <= g.plotRight) {
        const x = this.pointer.x, y = this.pointer.y;
        ctx.save(); ctx.setLineDash([4, 4]); ctx.strokeStyle = c.cross;
        ctx.beginPath(); ctx.moveTo(Math.round(x) + 0.5, g.top); ctx.lineTo(Math.round(x) + 0.5, this.height - g.bottom); ctx.stroke();
        if (y >= g.top && y <= g.priceBottom) {
          ctx.beginPath(); ctx.moveTo(g.left, Math.round(y) + 0.5); ctx.lineTo(g.plotRight, Math.round(y) + 0.5); ctx.stroke();
          ctx.setLineDash([]); ctx.fillStyle = c.cross; ctx.fillRect(g.plotRight, y - 10, this.width - g.plotRight, 20);
          ctx.fillStyle = "#fff"; ctx.textAlign = "left"; ctx.font = "11px Inter, sans-serif";
          ctx.fillText(axisLabel(priceAt(y)), g.plotRight + 7, y);
        }
        ctx.restore();
      }
    }

    drawComparison(ctx, g, colors, items) {
      const snapshot = this.comparisonSnapshot(items);
      if (!snapshot) {
        this.scale = null;
        ctx.fillStyle = colors.text; ctx.font = "12px sans-serif"; ctx.textAlign = "center";
        ctx.fillText("현재 구간에 공통 시각의 봉이 없습니다", this.width / 2, this.height / 2);
        return;
      }
      const values = snapshot.lines.flatMap(line => [...line.values.values()]);
      let low = Math.min(...values), high = Math.max(...values);
      const pad = Math.max((high - low) * 0.1, this.comparisonMode === "index100" ? 0.5 : 0.2);
      low -= pad; high += pad;
      const yFor = value => g.top + (high - value) / (high - low) * (this.height - g.bottom - g.top);
      const format = value => value.toFixed(2) + (this.comparisonMode === "percent" ? "%" : "");
      this.scale = {g, low, high, priceY: yFor,
        priceAt: y => high - (y - g.top) / (this.height - g.bottom - g.top) * (high - low)};
      ctx.font = "11px Inter, sans-serif"; ctx.textBaseline = "middle";
      for (let step = 0; step <= 5; step++) {
        const y = g.top + (this.height - g.bottom - g.top) * step / 5;
        ctx.strokeStyle = colors.grid; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(g.left, Math.round(y) + 0.5); ctx.lineTo(g.plotRight, Math.round(y) + 0.5); ctx.stroke();
        ctx.fillStyle = colors.text; ctx.textAlign = "left";
        ctx.fillText(format(high - (high - low) * step / 5), g.plotRight + 7, y);
      }
      ctx.strokeStyle = colors.axis;
      ctx.beginPath(); ctx.moveTo(g.plotRight + 0.5, 0); ctx.lineTo(g.plotRight + 0.5, this.height); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, this.height - g.bottom + 0.5); ctx.lineTo(this.width, this.height - g.bottom + 0.5); ctx.stroke();
      const tickEvery = Math.max(1, Math.ceil(90 / g.barWidth));
      for (const {bar, index} of items) {
        if (index % tickEvery !== 0) continue;
        const x = g.xAt(index);
        ctx.strokeStyle = colors.grid;
        ctx.beginPath(); ctx.moveTo(Math.round(x) + 0.5, g.top); ctx.lineTo(Math.round(x) + 0.5, this.height - g.bottom); ctx.stroke();
        ctx.fillStyle = colors.text; ctx.textAlign = "center";
        ctx.fillText(this.formatDate(bar.time), x, this.height - 14);
      }
      ctx.save(); ctx.beginPath(); ctx.rect(g.left, g.top, g.plotRight - g.left, this.height - g.bottom - g.top); ctx.clip();
      for (const line of snapshot.lines) {
        ctx.beginPath(); let started = false;
        for (const {bar, index} of items) {
          const value = line.values.get(bar.time);
          if (!Number.isFinite(value)) {started = false; continue;}
          const x = g.xAt(index), y = yFor(value);
          if (!started) {ctx.moveTo(x, y); started = true;} else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = line.color; ctx.lineWidth = 2; ctx.stroke();
      }
      ctx.restore();
      if (this.pointer && this.pointer.x >= g.left && this.pointer.x <= g.plotRight) {
        const x = this.pointer.x, y = this.pointer.y;
        ctx.save(); ctx.setLineDash([4, 4]); ctx.strokeStyle = colors.cross;
        ctx.beginPath(); ctx.moveTo(Math.round(x) + 0.5, g.top); ctx.lineTo(Math.round(x) + 0.5, this.height - g.bottom); ctx.stroke();
        if (y >= g.top && y <= this.height - g.bottom) {
          ctx.beginPath(); ctx.moveTo(g.left, Math.round(y) + 0.5); ctx.lineTo(g.plotRight, Math.round(y) + 0.5); ctx.stroke();
        }
        ctx.restore();
      }
    }

    drawSeries(ctx, g, items, line, yFor) {
      if (!line || !Array.isArray(line.values)) return;
      ctx.beginPath();
      let started = false;
      for (const {index} of items) {
        const value = line.values[index];
        if (!Number.isFinite(value)) {started = false; continue;}
        const x = g.xAt(index), y = yFor(value);
        if (!started) {ctx.moveTo(x, y); started = true;}
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = line.color || "#2962ff";
      ctx.lineWidth = 1.7;
      ctx.stroke();
    }

    drawOverlayIndicators(ctx, g, items, priceY) {
      const overlays = this.indicatorResults.filter(result => result.pane === "overlay");
      overlays.forEach((result, order) => {
        if (result.fill) {
          const upper = result.lines.find(line => line.label === result.fill.from);
          const lower = result.lines.find(line => line.label === result.fill.to);
          if (upper && lower) {
            const points = items.filter(({index}) =>
              Number.isFinite(upper.values[index]) && Number.isFinite(lower.values[index]));
            if (points.length > 1) {
              ctx.beginPath();
              points.forEach(({index}, position) => {
                const x = g.xAt(index), y = priceY(upper.values[index]);
                if (position === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
              });
              points.slice().reverse().forEach(({index}) => ctx.lineTo(g.xAt(index), priceY(lower.values[index])));
              ctx.closePath(); ctx.fillStyle = result.fill.color; ctx.fill();
            }
          }
        }
        for (const line of result.lines) this.drawSeries(ctx, g, items, line, priceY);
        ctx.fillStyle = result.lines[0]?.color || "#2962ff";
        ctx.textAlign = "left"; ctx.font = "11px Inter, sans-serif";
        ctx.fillText(result.label, g.left + 8, g.top + 16 + order * 16);
      });
    }

    drawIndicatorPanes(ctx, g, colors, items) {
      const panes = this.indicatorResults.filter(result => result.pane === "pane");
      panes.forEach((result, paneIndex) => {
        const region = g.paneRegions[paneIndex];
        if (!region || region.bottom <= region.top) return;
        const samples = [];
        for (const line of result.lines) for (const {index} of items) {
          const value = line.values[index];
          if (Number.isFinite(value)) samples.push(value);
        }
        if (result.histogram) for (const {index} of items) {
          const value = result.histogram.values[index];
          if (Number.isFinite(value)) samples.push(value);
        }
        let minimum = result.domain ? result.domain[0] : Math.min(0, ...samples);
        let maximum = result.domain ? result.domain[1] : Math.max(0, ...samples);
        if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {minimum = -1; maximum = 1;}
        if (maximum === minimum) {minimum -= 1; maximum += 1;}
        if (!result.domain) {
          const pad = (maximum - minimum) * 0.12;
          minimum -= pad; maximum += pad;
        }
        const valueY = value => region.top + (maximum - value) / (maximum - minimum) * (region.bottom - region.top);
        ctx.strokeStyle = colors.axis;
        ctx.beginPath(); ctx.moveTo(g.left, region.top - 3.5); ctx.lineTo(this.width, region.top - 3.5); ctx.stroke();
        for (const level of result.levels || []) {
          if (level < minimum || level > maximum) continue;
          const y = valueY(level);
          ctx.save(); ctx.setLineDash([3, 4]); ctx.strokeStyle = colors.grid;
          ctx.beginPath(); ctx.moveTo(g.left, y); ctx.lineTo(g.plotRight, y); ctx.stroke(); ctx.restore();
          ctx.fillStyle = colors.text; ctx.textAlign = "left"; ctx.font = "10px Inter, sans-serif";
          ctx.fillText(String(level), g.plotRight + 8, y);
        }
        ctx.save(); ctx.beginPath(); ctx.rect(g.left, region.top, g.plotRight - g.left, region.bottom - region.top); ctx.clip();
        if (result.histogram) {
          const zeroY = valueY(0);
          for (const {index} of items) {
            const value = result.histogram.values[index];
            if (!Number.isFinite(value)) continue;
            const x = g.xAt(index), y = valueY(value);
            ctx.fillStyle = value >= 0 ? result.histogram.positive : result.histogram.negative;
            ctx.fillRect(x - Math.max(1, g.barWidth * 0.3), Math.min(y, zeroY),
              Math.max(1, g.barWidth * 0.6), Math.max(1, Math.abs(zeroY - y)));
          }
        }
        for (const line of result.lines) this.drawSeries(ctx, g, items, line, valueY);
        ctx.restore();
        const lastIndex = items[items.length - 1].index;
        const value = result.lines[0]?.values[lastIndex];
        ctx.fillStyle = result.lines[0]?.color || colors.text;
        ctx.textAlign = "left"; ctx.font = "11px Inter, sans-serif";
        const caption = result.label + (Number.isFinite(value) ? "  " + value.toFixed(2) : "");
        ctx.fillText(caption, g.left + 8, region.top + 12);
      });
    }

    pointAt(x, y) {
      if (!this.scale) return null;
      const {g, priceAt} = this.scale;
      const index = clamp(Math.floor(g.first + (x - g.left) / g.barWidth), 0, this.data.length - 1);
      return {index, price: round(priceAt(clamp(y, g.top, g.priceBottom)))};
    }

    barAt(x) {
      if (!this.scale) return null;
      const {g} = this.scale;
      if (x < g.left || x > g.plotRight) return null;
      const index = Math.floor(g.first + (x - g.left) / g.barWidth);
      return this.data[index] ? {bar: this.data[index], index} : null;
    }

    position(event) {
      const rect = this.canvas.getBoundingClientRect();
      return {x: event.clientX - rect.left, y: event.clientY - rect.top};
    }

    handlePointerDown(event) {
      if (event.button !== 0) return;
      const point = this.position(event);
      this.canvas.setPointerCapture(event.pointerId);
      this.drag = {x: point.x, y: point.y, offset: this.rightOffset, moved: false};
    }

    handlePointerMove(event) {
      const point = this.position(event);
      this.pointer = point;
      if (this.drag && this.tool !== "trendline") {
        const delta = point.x - this.drag.x;
        if (Math.abs(delta) > 3) this.drag.moved = true;
        const g = this.geometry();
        this.rightOffset = clamp(Math.round(this.drag.offset + delta / g.barWidth), 0, Math.max(0, this.data.length - this.visibleCount));
        this.onViewChange(this.getVisibleTimeRange());
        this.canvas.parentElement.classList.toggle("panning", this.drag.moved);
      }
      const hit = this.barAt(point.x);
      if (hit) this.onHover(hit.bar, hit.index, point); else this.onLeave();
      this.schedule();
    }

    handlePointerUp(event) {
      if (!this.drag) return;
      const point = this.position(event);
      if (this.tool === "trendline" && !this.drag.moved && this.scale && point.x <= this.scale.g.plotRight) {
        const anchor = this.pointAt(point.x, point.y);
        if (anchor) {
          if (!this.lineStart) this.lineStart = anchor;
          else {this.lines.push([this.lineStart, anchor]); this.lineStart = null;}
        }
      }
      this.drag = null;
      this.canvas.parentElement.classList.remove("panning");
      this.schedule();
    }

    handlePointerLeave() {
      if (this.drag) return;
      this.pointer = null; this.onLeave(); this.schedule();
    }

    handleWheel(event) {
      event.preventDefault();
      if (!this.data.length) return;
      const factor = event.deltaY > 0 ? 1.13 : 0.88;
      this.setVisibleCount(this.visibleCount * factor);
    }

    formatPrice(value) {
      return Number(value).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }

    formatDate(time) {
      const date = new Date(time);
      return new Intl.DateTimeFormat("ko-KR", this.visibleCount > 200
        ? {month:"numeric", day:"numeric"}
        : {month:"numeric", day:"numeric"}).format(date);
    }
  }

  window.CandlestickChart = CandlestickChart;
})();
