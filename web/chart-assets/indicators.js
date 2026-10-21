/* Indicator calculations and extension registry. No Pine Script interpreter is used. */
(function () {
  "use strict";
  const definitions = new Map();
  const number = value => value == null || !Number.isFinite(Number(value)) ? null : Number(value);
  const lengthOf = value => Math.max(1, Math.floor(Number(value) || 1));
  const closes = bars => bars.map(bar => Number(bar.close));

  function sma(values, length) {
    length = lengthOf(length);
    const out = Array(values.length).fill(null);
    let sum = 0, valid = 0;
    for (let i = 0; i < values.length; i++) {
      const current = number(values[i]);
      if (current !== null) {sum += current; valid++;}
      if (i >= length) {
        const previous = number(values[i - length]);
        if (previous !== null) {sum -= previous; valid--;}
      }
      if (i >= length - 1 && valid === length) out[i] = sum / length;
    }
    return out;
  }

  function exponential(values, length, alpha) {
    length = lengthOf(length);
    const out = Array(values.length).fill(null);
    const seed = [];
    let previous = null;
    for (let i = 0; i < values.length; i++) {
      const value = number(values[i]);
      if (value === null) continue;
      if (previous === null) {
        seed.push(value);
        if (seed.length === length) {
          previous = seed.reduce((a, b) => a + b, 0) / length;
          out[i] = previous;
        }
      } else {
        previous = alpha * value + (1 - alpha) * previous;
        out[i] = previous;
      }
    }
    return out;
  }
  const ema = (values, length) => exponential(values, length, 2 / (lengthOf(length) + 1));
  const rma = (values, length) => exponential(values, length, 1 / lengthOf(length));

  function bollinger(values, length = 20, multiplier = 2) {
    length = lengthOf(length);
    const basis = sma(values, length);
    const upper = Array(values.length).fill(null), lower = Array(values.length).fill(null);
    for (let i = length - 1; i < values.length; i++) {
      if (basis[i] === null) continue;
      let variance = 0, valid = true;
      for (let j = i - length + 1; j <= i; j++) {
        const value = number(values[j]);
        if (value === null) {valid = false; break;}
        variance += (value - basis[i]) ** 2;
      }
      if (!valid) continue;
      const deviation = Math.sqrt(variance / length) * Number(multiplier);
      upper[i] = basis[i] + deviation;
      lower[i] = basis[i] - deviation;
    }
    return {basis, upper, lower};
  }

  function rsi(values, length = 14) {
    length = lengthOf(length);
    const gains = Array(values.length).fill(null), losses = Array(values.length).fill(null);
    for (let i = 1; i < values.length; i++) {
      const change = Number(values[i]) - Number(values[i - 1]);
      gains[i] = Math.max(0, change);
      losses[i] = Math.max(0, -change);
    }
    const averageGain = rma(gains, length), averageLoss = rma(losses, length);
    return values.map((_, index) => {
      const gain = averageGain[index], loss = averageLoss[index];
      if (gain === null || loss === null) return null;
      if (loss === 0) return gain === 0 ? 50 : 100;
      return 100 - 100 / (1 + gain / loss);
    });
  }

  function macd(values, fast = 12, slow = 26, signalLength = 9) {
    const fastLine = ema(values, fast), slowLine = ema(values, slow);
    const macdLine = values.map((_, index) =>
      fastLine[index] === null || slowLine[index] === null ? null : fastLine[index] - slowLine[index]);
    const signal = ema(macdLine, signalLength);
    const histogram = macdLine.map((value, index) =>
      value === null || signal[index] === null ? null : value - signal[index]);
    return {macd: macdLine, signal, histogram};
  }

  function register(definition) {
    if (!definition || typeof definition.id !== "string" || !/^[a-z][a-z0-9_-]*$/.test(definition.id) ||
        typeof definition.name !== "string" || typeof definition.compute !== "function" ||
        !["overlay", "pane"].includes(definition.pane)) {
      throw new TypeError("Invalid indicator definition");
    }
    definitions.set(definition.id, {
      ...definition,
      parameters: Array.isArray(definition.parameters) ? definition.parameters : []
    });
  }

  function calculate(configs, bars) {
    return configs.map(config => {
      const definition = definitions.get(config.id);
      if (!definition) return null;
      const params = {};
      for (const field of definition.parameters) {
        const raw = config.params?.[field.key] ?? field.default;
        const value = Number(raw);
        params[field.key] = Number.isFinite(value)
          ? Math.min(field.max ?? Infinity, Math.max(field.min ?? 1, value))
          : field.default;
      }
      const result = definition.compute(bars, params);
      if (!result || !Array.isArray(result.lines)) return null;
      return {
        ...result, id: definition.id, name: definition.name, pane: definition.pane, params,
        label: definition.name + (definition.id === "macd" ? "" : " " + (params.length ?? ""))
      };
    }).filter(Boolean);
  }

  const period = (value = 20) => [{key:"length", label:"기간", default:value, min:2, max:200, step:1}];
  register({
    id:"sma", name:"SMA", pane:"overlay", description:"단순 이동평균",
    parameters:period(20),
    compute:(bars, params) => ({lines:[{label:"SMA", color:"#f5a623", values:sma(closes(bars), params.length)}]})
  });
  register({
    id:"ema", name:"EMA", pane:"overlay", description:"지수 이동평균",
    parameters:period(20),
    compute:(bars, params) => ({lines:[{label:"EMA", color:"#8b5cf6", values:ema(closes(bars), params.length)}]})
  });
  register({
    id:"bb", name:"볼린저 밴드", pane:"overlay", description:"평균 ± 표준편차",
    parameters:[...period(20), {key:"multiplier", label:"σ", default:2, min:0.1, max:5, step:0.1}],
    compute:(bars, params) => {
      const band = bollinger(closes(bars), params.length, params.multiplier);
      return {
        lines:[
          {label:"상단", color:"#5687e8", values:band.upper},
          {label:"중심", color:"#739de9", values:band.basis},
          {label:"하단", color:"#5687e8", values:band.lower}
        ],
        fill:{from:"상단", to:"하단", color:"rgba(86,135,232,0.09)"}
      };
    }
  });
  register({
    id:"rsi", name:"RSI", pane:"pane", description:"상대강도지수",
    parameters:period(14),
    compute:(bars, params) => ({
      domain:[0,100], levels:[30,70],
      lines:[{label:"RSI", color:"#8b5cf6", values:rsi(closes(bars), params.length)}]
    })
  });
  register({
    id:"macd", name:"MACD", pane:"pane", description:"이동평균 수렴·확산",
    parameters:[
      {key:"fast", label:"빠름", default:12, min:2, max:100, step:1},
      {key:"slow", label:"느림", default:26, min:3, max:200, step:1},
      {key:"signal", label:"신호", default:9, min:2, max:100, step:1}
    ],
    compute:(bars, params) => {
      const result = macd(closes(bars), params.fast, Math.max(params.fast + 1, params.slow), params.signal);
      return {
        levels:[0],
        lines:[
          {label:"MACD", color:"#4388e8", values:result.macd},
          {label:"시그널", color:"#f5a623", values:result.signal}
        ],
        histogram:{values:result.histogram, positive:"#71c5b4", negative:"#e9939a"}
      };
    }
  });

  window.ChartIndicators = {
    register,
    get:id => definitions.get(id),
    list:() => Array.from(definitions.values()),
    calculate,
    sma, ema, rma, bollinger, rsi, macd
  };
})();
