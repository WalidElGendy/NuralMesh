/* ==========================================================================
   Charts — hand-rolled SVG, no charting dependency.

   Follows the house data-viz method:
     · form chosen by the data's job (magnitude / change / relation / headline)
     · categorical hues assigned in FIXED slot order, never cycled
     · palette validated against this surface:
         validate_palette.js "#3987e5,#d95926,#199e70,#c98500,#d55181,#008300"
           --mode dark --surface "#12151a"   →  ALL CHECKS PASS
     · one axis only — never a second y-scale
     · thin marks, 4px rounded data-ends on the baseline, 2px lines,
       2px surface gap between adjacent fills
     · hover layer by default; legend for ≥2 series; table view always available
   ========================================================================== */

import { esc, fmt, $, clamp } from './00-core.js';
import { parseNum } from './10-markdown.js';

const SERIES = ['var(--series-1)','var(--series-2)','var(--series-3)',
                'var(--series-4)','var(--series-5)','var(--series-6)'];
const MAX_SERIES = 6;

const svgNS = 'http://www.w3.org/2000/svg';

/* ------------------------------ form choice ------------------------------ */

/**
 * Pick the chart form from the data's job, not from taste.
 *   1 number, no dimension          → stat tile (not a chart)
 *   time-like x                     → line (change over time)
 *   ≤ 2 numeric cols, 2 series      → scatter (relation)
 *   many categories / long labels   → horizontal bar (identity + magnitude)
 *   otherwise                       → vertical bar (magnitude)
 */
export function chooseForm({ rows, xKey, yKeys }) {
  if (rows.length === 1 && yKeys.length <= 3) return 'tiles';
  const xs = rows.map(r => r[xKey]);
  if (looksTemporal(xs)) return 'line';
  const longLabels = xs.some(v => String(v).length > 12);
  if (rows.length > 12 || longLabels) return 'hbar';
  return 'bar';
}

function looksTemporal(vals) {
  const hits = vals.filter(v => {
    const s = String(v).trim();
    if (/^(19|20)\d{2}$/.test(s)) return true;                       // year
    if (/^(19|20)\d{2}[-/](Q[1-4]|\d{1,2})/i.test(s)) return true;   // 2024-Q1, 2024-03
    if (/^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/i.test(s)) return true;
    if (/^\d{4}-\d{2}-\d{2}/.test(s)) return true;
    return false;
  }).length;
  return hits / Math.max(vals.length, 1) > 0.6;
}

/* --------------------------- spec normalisation -------------------------- */

/** Accepts a mesh-chart JSON spec OR a parsed markdown table. */
export function normalise(input) {
  let rows, xKey, yKeys, title, subtitle, unit, type;
  let unitByKey = null;

  if (input.head) {                                   // markdown table
    const { head, body, numeric } = input;
    const xi = numeric.findIndex(n => !n);
    xKey = head[xi < 0 ? 0 : xi];
    yKeys = head.filter((_, i) => numeric[i] && i !== xi);
    rows = body.map(r => {
      const o = {};
      head.forEach((h, i) => { o[h] = numeric[i] ? parseNum(r[i]) : r[i]; });
      return o;
    });
    title = null; subtitle = null;
    // Per-column units read off the RAW cells — "$13.10" and "40%" are
    // unambiguous, where the header word alone is not.
    unitByKey = {};
    head.forEach((h, i) => { if (numeric[i]) unitByKey[h] = columnUnit(body.map(r => r[i]), h); });
    const units = [...new Set(yKeys.map(k => unitByKey[k]))];
    unit = units.length === 1 ? units[0] : null;
  } else {                                            // explicit spec
    rows = input.data || input.rows || [];
    xKey = input.x || Object.keys(rows[0] || {})[0];
    yKeys = input.y ? [].concat(input.y)
      : Object.keys(rows[0] || {}).filter(k => k !== xKey && typeof rows[0][k] === 'number');
    title = input.title; subtitle = input.subtitle; unit = input.unit; type = input.type;
    rows = rows.map(r => {
      const o = { ...r };
      yKeys.forEach(k => { o[k] = typeof o[k] === 'number' ? o[k] : parseNum(o[k]); });
      return o;
    });
  }

  if (!rows.length || !yKeys.length) return null;

  // Cap at 6 series; the rest folds into "Other" rather than inventing hues.
  if (yKeys.length > MAX_SERIES) {
    const keep = yKeys.slice(0, MAX_SERIES - 1);
    const fold = yKeys.slice(MAX_SERIES - 1);
    rows = rows.map(r => ({ ...r, Other: fold.reduce((s, k) => s + (r[k] || 0), 0) }));
    yKeys = [...keep, 'Other'];
  }

  // ONE AXIS. Measures that are not commensurable must not share a scale —
  // a % column and a $ column on one y-axis is the dual-axis mistake wearing
  // a disguise. Chart the largest commensurable group; the rest stay
  // available as legend toggles and in the table view.
  // An explicit spec-level unit is a declaration that every series shares it,
  // so only magnitude can split those.
  if (!unitByKey) unitByKey = Object.fromEntries(yKeys.map(k => [k, unit || 'declared']));
  const groups = commensurableGroups(rows, yKeys, unitByKey);
  const active = groups[0] || yKeys.slice(0, 1);
  const split = groups.length > 1;

  type = type || chooseForm({ rows, xKey, yKeys: active });
  return { rows, xKey, yKeys, active: [...active], groups, split, title, subtitle, unit, unitByKey, type };
}

/**
 * Partition measures into sets that can honestly share one axis.
 * Two columns are commensurable when their unit matches AND their typical
 * magnitudes are within ~25x of each other.
 */
function commensurableGroups(rows, keys, unitByKey) {
  const info = keys.map(k => {
    const vals = rows.map(r => r[k]).filter(Number.isFinite).map(Math.abs).filter(v => v > 0)
      .sort((a, b) => a - b);
    return { k, unit: unitByKey[k] ?? 'other', med: vals.length ? vals[Math.floor(vals.length / 2)] : 0 };
  });
  const groups = [];
  for (const it of info) {
    const g = groups.find(g =>
      g.unit === it.unit &&
      (!it.med || !g.med || Math.max(it.med, g.med) / Math.min(it.med, g.med) <= 25));
    if (g) { g.keys.push(it.k); g.med = Math.max(g.med, it.med); }
    else groups.push({ unit: it.unit, med: it.med, keys: [it.k] });
  }
  return groups.sort((a, b) => b.keys.length - a.keys.length).map(g => g.keys);
}

/** Unit of a table column, read off the cell text first, the header second. */
function columnUnit(cells, header) {
  const txt = cells.join(' ');
  if (/%/.test(txt)) return 'pct_raw';
  if (/[$€£¥₹﷼]/.test(txt)) return 'usd';
  if (/\d\s*ms\b/i.test(txt)) return 'ms';
  const h = String(header).toLowerCase();
  if (/%|percent|share|\brate\b|نسبة/.test(h)) return 'pct_raw';
  if (/\$|usd|cost|price|revenue|spend|margin|profit|payout|سعر|تكلفة|إيراد/.test(h)) return 'usd';
  if (/\bms\b|latency|زمن/.test(h)) return 'ms';
  return 'count';
}

const fmtUnit = (v, unit) =>
  unit === 'usd' ? fmt(v, { usd: true })
  : unit === 'ms' ? fmt(v, { ms: true })
  : unit === 'pct' ? fmt(v, { pct: true })
  : unit === 'pct_raw' ? fmt(v) + '%'
  : fmt(v);

/* -------------------------------- scales --------------------------------- */

/** "Nice" axis ticks — the 1/2/5 ladder. */
function ticks(min, max, count = 5) {
  if (min === max) { min = Math.min(0, min); max = max || 1; }
  const span = max - min;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const out = [];
  for (let v = lo; v <= hi + step / 2; v += step) out.push(+v.toFixed(10));
  return out;
}

/* ------------------------------ the renderer ----------------------------- */

let figSeq = 0;

/**
 * Render a figure: caption + chart + legend + table toggle.
 * Returns an HTMLElement ready to insert.
 */
export function figure(specIn, opts = {}) {
  const spec = normalise(specIn);
  const wrap = document.createElement('div');
  wrap.className = 'figure';
  if (!spec) { wrap.remove(); return null; }

  const id = 'fig' + (++figSeq);
  const { title, subtitle, yKeys, type } = spec;

  wrap.innerHTML = `
    <div class="figure__cap">
      ${title ? `<span class="figure__t">${esc(title)}</span>` : ''}
      ${subtitle ? `<span class="figure__s">${esc(subtitle)}</span>` : ''}
      <span class="figure__actions">
        <button class="tablebtn" data-act="table" aria-pressed="false">table</button>
        ${opts.pinnable !== false ? '<button class="tablebtn" data-act="pin">pin</button>' : ''}
      </span>
    </div>
    <div class="figure__body" id="${id}"></div>`;

  const body = wrap.querySelector('.figure__body');
  const tableBtn = wrap.querySelector('[data-act="table"]');
  const shown = () => spec.yKeys.filter(k => spec.active.includes(k));

  const draw = () => {
    if (tableBtn.getAttribute('aria-pressed') === 'true') {
      body.innerHTML = ''; body.appendChild(dataTable(spec)); return;
    }
    body.innerHTML = '';
    if (type === 'tiles') { body.appendChild(tiles(spec)); return; }

    // Width comes from the live container, so text stays legible in the
    // narrow canvas pane instead of being scaled down with the viewBox.
    const w = Math.max(240, Math.round(body.clientWidth || 560));
    body.appendChild(plot(spec, w, shown()));

    if (spec.yKeys.length >= 2) {
      body.appendChild(legend(spec, (k) => {
        const i = spec.active.indexOf(k);
        if (i >= 0) { if (spec.active.length > 1) spec.active.splice(i, 1); }
        else spec.active.push(k);
        draw();
      }));
    }
  };
  draw();

  // Table view is the accessibility fallback and the "show me the numbers" path.
  tableBtn.addEventListener('click', (e) => {
    const on = e.currentTarget.getAttribute('aria-pressed') === 'true';
    e.currentTarget.setAttribute('aria-pressed', String(!on));
    e.currentTarget.textContent = on ? 'table' : 'chart';
    draw();
  });
  wrap.querySelector('[data-act="pin"]')?.addEventListener('click', () => opts.onPin?.(specIn, spec));

  // Redraw on container resize so the chart never overflows its pane.
  if (typeof ResizeObserver !== 'undefined') {
    let w = 0;
    new ResizeObserver(([e]) => {
      const nw = Math.round(e.contentRect.width);
      if (Math.abs(nw - w) > 24) { w = nw; draw(); }
    }).observe(body);
  }
  return wrap;
}

/* --------------------------------- tiles --------------------------------- */

function tiles(spec) {
  const { rows, yKeys, unit } = spec;
  const el = document.createElement('div');
  el.className = 'tiles';
  el.style.border = '1px solid var(--line)';
  el.style.borderRadius = '8px';
  el.innerHTML = yKeys.map(k => `
    <div class="tile">
      <span class="tile__k">${esc(k)}</span>
      <span class="tile__v">${esc(fmtUnit(rows[0][k], unit))}</span>
    </div>`).join('');
  return el;
}

export function tileRow(items) {
  const el = document.createElement('div');
  el.className = 'tiles';
  el.innerHTML = items.map(t => `
    <div class="tile">
      <span class="tile__k">${esc(t.k)}</span>
      <span class="tile__v">${esc(t.v)}</span>
      ${t.d ? `<span class="tile__d"${t.dir ? ` data-dir="${t.dir}"` : ''}>${esc(t.d)}</span>` : ''}
    </div>`).join('');
  return el;
}

/* -------------------------------- the plot ------------------------------- */

function plot(spec, W = 560, activeKeys) {
  const { rows, xKey, type } = spec;
  const yKeys = activeKeys?.length ? activeKeys : spec.yKeys;
  // The axis carries the unit of the group actually on screen.
  const unit = spec.unit || spec.unitByKey?.[yKeys[0]] || null;
  const horizontal = type === 'hbar';

  const rowH = 26;
  const H = horizontal
    ? clamp(rows.length * rowH * Math.max(1, yKeys.length * 0.8) + 34, 120, 620)
    : clamp(Math.round(W * 0.42), 190, 280);

  const padL = horizontal
    ? clamp(8 + maxLabel(rows.map(r => r[xKey])) * 6.4, 40, Math.min(170, W * 0.38))
    : 48;
  const pad = { t: 12, r: 14, b: horizontal ? 24 : 30, l: padL };
  const iw = W - pad.l - pad.r;
  const ih = H - pad.t - pad.b;

  const all = rows.flatMap(r => yKeys.map(k => r[k])).filter(v => Number.isFinite(v));
  const min = Math.min(0, ...all);
  const max = Math.max(...all, 0);
  const tk = ticks(min, max, horizontal ? 4 : 5);
  const vLo = tk[0], vHi = tk[tk.length - 1];
  const vscale = (v) => (v - vLo) / (vHi - vLo || 1);

  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('class', 'chart');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  svg.setAttribute('role', 'img');
  svg.style.height = H + 'px';
  svg.style.maxHeight = '100%';

  const add = (tag, attrs, txt) => {
    const n = document.createElementNS(svgNS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (txt != null) n.textContent = txt;
    svg.appendChild(n);
    return n;
  };

  /* ---- gridlines (recessive) + value axis ---- */
  if (horizontal) {
    tk.forEach(v => {
      const x = pad.l + vscale(v) * iw;
      add('line', { class: 'grid', x1: x, x2: x, y1: pad.t, y2: pad.t + ih });
      add('text', { class: 'lbl', x, y: H - 8, 'text-anchor': 'middle' }, fmtUnit(v, unit));
    });
  } else {
    tk.forEach(v => {
      const y = pad.t + ih - vscale(v) * ih;
      add('line', { class: 'grid', x1: pad.l, x2: pad.l + iw, y1: y, y2: y });
      add('text', { class: 'lbl', x: pad.l - 7, y: y + 3.5, 'text-anchor': 'end' }, fmtUnit(v, unit));
    });
  }
  // zero baseline sits above the grid
  const zeroPos = vscale(0);
  if (vLo < 0 && vHi > 0) {
    if (horizontal) add('line', { class: 'axis', x1: pad.l + zeroPos * iw, x2: pad.l + zeroPos * iw, y1: pad.t, y2: pad.t + ih });
    else add('line', { class: 'axis', x1: pad.l, x2: pad.l + iw, y1: pad.t + ih - zeroPos * ih, y2: pad.t + ih - zeroPos * ih });
  } else {
    if (horizontal) add('line', { class: 'axis', x1: pad.l, x2: pad.l, y1: pad.t, y2: pad.t + ih });
    else add('line', { class: 'axis', x1: pad.l, x2: pad.l + iw, y1: pad.t + ih, y2: pad.t + ih });
  }

  const n = rows.length, ns = yKeys.length;

  /* --------------------------- bar / hbar --------------------------- */
  if (type === 'bar' || type === 'hbar') {
    const band = (horizontal ? ih : iw) / n;
    const GAP = 2;                                        // 2px surface gap
    const groupW = Math.min(band * 0.72, 46 * ns);
    const barW = Math.max(3, (groupW - GAP * (ns - 1)) / ns);

    rows.forEach((r, i) => {
      const base = (horizontal ? pad.t : pad.l) + band * i + (band - groupW) / 2;
      yKeys.forEach((k, s) => {
        const v = r[k]; if (!Number.isFinite(v)) return;
        const off = base + s * (barW + GAP);
        const col = SERIES[s % MAX_SERIES];
        let d;
        if (horizontal) {
          const x0 = pad.l + Math.min(vscale(0), vscale(v)) * iw;
          const x1 = pad.l + Math.max(vscale(0), vscale(v)) * iw;
          d = roundedRect(x0, off, Math.max(1, x1 - x0), barW, 4, v >= 0 ? 'r' : 'l');
        } else {
          const y0 = pad.t + ih - Math.max(vscale(0), vscale(v)) * ih;
          const y1 = pad.t + ih - Math.min(vscale(0), vscale(v)) * ih;
          d = roundedRect(off, y0, barW, Math.max(1, y1 - y0), 4, v >= 0 ? 't' : 'b');
        }
        const p = add('path', { class: 'mark', d, fill: col });
        hover(p, `${r[xKey]}`, [[k, fmtUnit(v, unit)]]);
      });

      // category label
      if (horizontal) {
        add('text', { class: 'lbl', x: pad.l - 8, y: pad.t + band * i + band / 2 + 3.5, 'text-anchor': 'end' },
            trunc(String(r[xKey]), 24));
      } else if (n <= 14 || i % Math.ceil(n / 12) === 0) {
        add('text', { class: 'lbl', x: pad.l + band * i + band / 2, y: H - 10, 'text-anchor': 'middle' },
            trunc(String(r[xKey]), 11));
      }
    });

    // direct value labels when there is room and ≤ 1 series
    if (ns === 1 && n <= 12) {
      rows.forEach((r, i) => {
        const v = r[yKeys[0]]; if (!Number.isFinite(v)) return;
        const band2 = (horizontal ? ih : iw) / n;
        if (horizontal) {
          add('text', { class: 'val', x: pad.l + vscale(v) * iw + 6, y: pad.t + band2 * i + band2 / 2 + 3.5 },
              fmtUnit(v, unit));
        } else {
          add('text', { class: 'val', x: pad.l + band2 * i + band2 / 2, y: pad.t + ih - vscale(v) * ih - 6, 'text-anchor': 'middle' },
              fmtUnit(v, unit));
        }
      });
    }
  }

  /* ----------------------------- line / area ---------------------------- */
  if (type === 'line' || type === 'area') {
    const step = n > 1 ? iw / (n - 1) : 0;
    const X = (i) => pad.l + (n > 1 ? step * i : iw / 2);
    const Y = (v) => pad.t + ih - vscale(v) * ih;

    yKeys.forEach((k, s) => {
      const col = SERIES[s % MAX_SERIES];
      const pts = rows.map((r, i) => Number.isFinite(r[k]) ? [X(i), Y(r[k])] : null).filter(Boolean);
      if (!pts.length) return;

      if (type === 'area' && ns === 1) {
        const d = `M${pts[0][0]},${Y(0)}` + pts.map(p => `L${p[0]},${p[1]}`).join('') + `L${pts.at(-1)[0]},${Y(0)}Z`;
        add('path', { d, fill: col, 'fill-opacity': '.13' });
      }
      add('path', {
        class: 'mark', d: 'M' + pts.map(p => `${p[0]},${p[1]}`).join('L'),
        fill: 'none', stroke: col, 'stroke-width': 2,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round',
      });
      // markers: only when sparse enough to read
      if (n <= 24) pts.forEach((p, i) => {
        const c = add('circle', { class: 'mark', cx: p[0], cy: p[1], r: 4, fill: col, stroke: 'var(--s-1)', 'stroke-width': 2 });
        hover(c, String(rows[i][xKey]), [[k, fmtUnit(rows[i][k], unit)]]);
      });
      // direct label at the series end (≤4 series)
      if (ns <= 4) {
        const last = pts.at(-1);
        add('text', { class: 'val', x: last[0] - 4, y: last[1] - 9, 'text-anchor': 'end', fill: 'var(--ink-2)' }, k);
      }
    });

    rows.forEach((r, i) => {
      if (n <= 14 || i % Math.ceil(n / 10) === 0 || i === n - 1)
        add('text', { class: 'lbl', x: X(i), y: H - 10, 'text-anchor': 'middle' }, trunc(String(r[xKey]), 11));
    });

    // crosshair band — one hit target per x position
    rows.forEach((r, i) => {
      const h = add('rect', { class: 'hit', x: X(i) - step / 2, y: pad.t, width: step || iw, height: ih });
      hover(h, String(r[xKey]), yKeys.map(k => [k, fmtUnit(r[k], unit)]));
    });
  }

  /* ------------------------------- scatter ------------------------------ */
  if (type === 'scatter') {
    const xs = rows.map(r => parseNum(r[xKey])).filter(Number.isFinite);
    const xt = ticks(Math.min(...xs), Math.max(...xs), 5);
    const xLo = xt[0], xHi = xt.at(-1);
    const X = (v) => pad.l + ((v - xLo) / (xHi - xLo || 1)) * iw;
    const Y = (v) => pad.t + ih - vscale(v) * ih;
    xt.forEach(v => add('text', { class: 'lbl', x: X(v), y: H - 10, 'text-anchor': 'middle' }, fmt(v)));
    rows.forEach(r => {
      const x = parseNum(r[xKey]), y = r[yKeys[0]];
      if (!Number.isFinite(x) || !Number.isFinite(y)) return;
      const c = add('circle', { class: 'mark', cx: X(x), cy: Y(y), r: 5,
        fill: SERIES[0], 'fill-opacity': .82, stroke: 'var(--s-1)', 'stroke-width': 2 });
      hover(c, r.label || `${fmt(x)}`, [[xKey, fmt(x)], [yKeys[0], fmtUnit(y, unit)]]);
    });
  }

  return svg;
}

/* --------------------------- shapes and helpers -------------------------- */

/** Rect with 4px rounding on the data end only; the baseline end stays square. */
function roundedRect(x, y, w, h, r, end) {
  r = Math.min(r, w / 2, h / 2);
  if (end === 't') return `M${x},${y + h}V${y + r}a${r},${r} 0 0 1 ${r},-${r}h${w - 2 * r}a${r},${r} 0 0 1 ${r},${r}V${y + h}Z`;
  if (end === 'b') return `M${x},${y}V${y + h - r}a${r},${r} 0 0 0 ${r},${r}h${w - 2 * r}a${r},${r} 0 0 0 ${r},-${r}V${y}Z`;
  if (end === 'r') return `M${x},${y}h${w - r}a${r},${r} 0 0 1 ${r},${r}v${h - 2 * r}a${r},${r} 0 0 1 -${r},${r}h${-(w - r)}Z`;
  return `M${x + r},${y}h${w - r}v${h}h${-(w - r)}a${r},${r} 0 0 1 -${r},-${r}v${-(h - 2 * r)}a${r},${r} 0 0 1 ${r},-${r}Z`;
}

const trunc = (s, n) => (s.length > n ? s.slice(0, n - 1) + '…' : s);
const maxLabel = (vals) => Math.max(...vals.map(v => String(v).length), 4);

/* -------------------------------- hover ---------------------------------- */

function hover(node, title, rows) {
  const tt = $('#tt');
  const show = (e) => {
    tt.innerHTML = `<div class="tt__k">${esc(title)}</div>` +
      rows.filter(r => r[1] !== '—').map(r =>
        `<div class="tt__r"><span>${esc(r[0])}</span><b>${esc(r[1])}</b></div>`).join('');
    tt.dataset.on = '1';
    move(e);
  };
  const move = (e) => {
    const r = tt.getBoundingClientRect();
    tt.style.left = clamp(e.clientX + 12, 8, innerWidth - r.width - 8) + 'px';
    tt.style.top  = clamp(e.clientY - r.height - 10, 8, innerHeight - r.height - 8) + 'px';
  };
  const hide = () => { tt.dataset.on = '0'; };
  node.addEventListener('pointerenter', show);
  node.addEventListener('pointermove', move);
  node.addEventListener('pointerleave', hide);
  node.setAttribute('tabindex', '0');
  node.addEventListener('focus', (e) => show({ clientX: node.getBoundingClientRect().x, clientY: node.getBoundingClientRect().y }));
  node.addEventListener('blur', hide);
}

/* ------------------------------- legend ---------------------------------- */

function legend(spec, onToggle) {
  const el = document.createElement('div');
  el.className = 'legend';
  const shown = spec.yKeys.filter(k => spec.active.includes(k));
  el.innerHTML = spec.yKeys.map((k) => {
    const on = spec.active.includes(k);
    const i = shown.indexOf(k);
    return `<button class="legend__i" type="button" aria-pressed="${on}" data-k="${esc(k)}">
      <span class="legend__s" style="background:${on ? SERIES[i % MAX_SERIES] : 'var(--ink-4)'}"></span>${esc(k)}</button>`;
  }).join('') + (spec.split
    ? `<span class="legend__note" title="These measures are not on the same scale, so they do not share an axis">
         ${spec.groups.length} scales — toggle to compare</span>`
    : '');
  el.querySelectorAll('.legend__i').forEach(b => b.onclick = () => onToggle(b.dataset.k));
  return el;
}

/* ------------------------------ table view ------------------------------- */

export function dataTable(spec) {
  const { rows, xKey, yKeys, unit } = spec;
  const el = document.createElement('div');
  el.style.overflowX = 'auto';
  el.innerHTML = `<table>
    <thead><tr><th>${esc(xKey)}</th>${yKeys.map(k => `<th class="num">${esc(k)}</th>`).join('')}</tr></thead>
    <tbody>${rows.map(r => `<tr><td>${esc(String(r[xKey]))}</td>${
      yKeys.map(k => `<td class="num">${esc(fmtUnit(r[k], unit))}</td>`).join('')
    }</tr>`).join('')}</tbody></table>`;
  return el;
}

/* ---------------------- markdown table → figure ------------------------- */

/** Only chart a table when charting actually helps. */
export function tableWorthCharting(table) {
  const numCols = table.numeric.filter(Boolean).length;
  return numCols >= 1 && table.body.length >= 3 && table.body.length <= 60 && table.head.length <= 8;
}

export function tableElement(table) {
  const el = document.createElement('div');
  el.style.overflowX = 'auto';
  el.innerHTML = `<table>
    <thead><tr>${table.head.map((h, i) => `<th${table.numeric[i] ? ' class="num"' : ''}>${esc(h)}</th>`).join('')}</tr></thead>
    <tbody>${table.body.map(r => `<tr>${r.map((c, i) =>
      `<td${table.numeric[i] ? ' class="num"' : ''}>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  return el;
}

export { SERIES };
