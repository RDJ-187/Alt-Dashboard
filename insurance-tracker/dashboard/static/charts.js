/* Minimal SVG chart kit: columns (stacked), horizontal stacked bars, donut, calendar heatmap.
   Specs: bars <= 24px, 4px rounded data-end and square at baseline, 2px surface gaps,
   hairline recessive grid, hover tooltips via [data-tip], text never in series colour. */
const Charts = (() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => Number(n).toLocaleString("en-IN");

  /** Tooltip HTML: title + rows [{color, label, value}] */
  function tip(title, rows = [], foot = "") {
    const r = rows.map((x) => `<div class="tt-r"><span>${x.color ? `<i class="sw" style="background:${x.color}"></i>` : ""}${esc(x.label)}</span><b>${esc(x.value)}</b></div>`).join("");
    return esc(`<div class="tt-h">${esc(title)}</div>${r}${foot ? `<div class="muted" style="margin-top:4px">${esc(foot)}</div>` : ""}`);
  }

  function niceMax(v, ticks = 4) {
    if (v <= 0) return { max: ticks, step: 1 };
    const raw = v / ticks;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw && (s >= 1 || mag < 1)) || 10 * mag;
    const st = Math.max(1, Math.ceil(step));
    return { max: Math.ceil(v / st) * st, step: st };
  }

  /** Bar path: square at baseline, 4px rounded at the data end. Vertical (grows up). */
  function colPath(x, y, w, h, r = 4) {
    if (h <= 0) return "";
    r = Math.min(r, w / 2, h);
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  }
  /** Horizontal: square at left baseline, rounded at right end (only if `endRound`). */
  function rowPath(x, y, w, h, endRound, r = 4) {
    if (w <= 0) return "";
    if (!endRound) return `M${x},${y}H${x + w}V${y + h}H${x}Z`;
    r = Math.min(r, h / 2, w);
    return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
  }

  /**
   * Vertical columns, optionally stacked.
   * cats:   [{key, label, sub?}]
   * series: [{key, label, color}]
   * data:   {catKey: {seriesKey: n}}
   */
  function columns({ width, height = 260, cats, series, data, capLabels = true, marker = null, tipFn, onClickAttr }) {
    const m = { t: 20, r: 8, b: 40, l: 36 };
    const W = Math.max(width, 240), H = height;
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const totals = cats.map((c) => series.reduce((s, se) => s + (data[c.key]?.[se.key] || 0), 0));
    const { max, step } = niceMax(Math.max(...totals, 1));
    const band = iw / cats.length;
    const bw = Math.min(24, band * 0.62);
    const y = (v) => m.t + ih - (v / max) * ih;
    let g = "";
    for (let v = 0; v <= max; v += step) {
      g += `<line class="${v === 0 ? "baseline" : "gridline"}" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/>`;
      g += `<text x="${m.l - 8}" y="${y(v) + 3.5}" text-anchor="end" class="num">${v >= 10000 ? fmt(v / 1000) + "K" : fmt(v)}</text>`;
    }
    const labelEvery = Math.ceil(cats.length / Math.max(1, Math.floor(iw / 46)));
    cats.forEach((c, i) => {
      const cx = m.l + band * i + band / 2;
      const x = cx - bw / 2;
      let acc = 0;
      const segs = series.map((se) => ({ se, v: data[c.key]?.[se.key] || 0 })).filter((s) => s.v > 0);
      segs.forEach((s, j) => {
        const y0 = y(acc), y1 = y(acc + s.v);
        const top = j === segs.length - 1;
        const gap = j > 0 ? 2 : 0; // 2px surface gap between stacked segments
        const h = Math.max(0, y0 - y1 - gap);
        const p = top ? colPath(x, y1, bw, h) : `M${x},${y1}H${x + bw}V${y1 + h}H${x}Z`;
        g += `<path class="mark" d="${p}" fill="${s.se.color}"/>`;
        acc += s.v;
      });
      if (capLabels && totals[i] > 0) g += `<text x="${cx}" y="${y(totals[i]) - 6}" text-anchor="middle" class="t-sec num">${fmt(totals[i])}</text>`;
      if (i % labelEvery === 0) {
        g += `<text x="${cx}" y="${H - m.b + 16}" text-anchor="middle" class="t-sec">${esc(c.label)}</text>`;
        if (c.sub) g += `<text x="${cx}" y="${H - m.b + 29}" text-anchor="middle">${esc(c.sub)}</text>`;
      }
      const t = tipFn ? tipFn(c, totals[i]) : tip(c.label, series.map((se) => ({ color: se.color, label: se.label, value: fmt(data[c.key]?.[se.key] || 0) })));
      g += `<rect class="hit" x="${m.l + band * i}" y="${m.t}" width="${band}" height="${ih}" data-tip="${t}" ${onClickAttr ? onClickAttr(c) : ""}/>`;
    });
    if (marker != null) {
      const mx = m.l + band * marker.index + band * marker.frac;
      g += `<line class="today-line" x1="${mx}" x2="${mx}" y1="${m.t - 6}" y2="${m.t + ih}"/>`;
      g += `<text x="${mx + 4}" y="${m.t - 8}" class="t-sec">${esc(marker.label)}</text>`;
    }
    return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img">${g}</svg>`;
  }

  /**
   * Horizontal stacked bars. rows: [{label, key, parts: {seriesKey: n}}]
   */
  function hbars({ width, rows, series, rowH = 30, labelW = 120, tipFn, onClickAttr }) {
    const m = { t: 4, r: 44, b: 4, l: labelW };
    const W = Math.max(width, 260);
    const H = m.t + m.b + rows.length * rowH;
    const iw = W - m.l - m.r;
    const totals = rows.map((r) => series.reduce((s, se) => s + (r.parts[se.key] || 0), 0));
    const max = Math.max(...totals, 1);
    const bh = Math.min(16, rowH * 0.56);
    let g = "";
    rows.forEach((r, i) => {
      const y0 = m.t + i * rowH;
      const by = y0 + (rowH - bh) / 2;
      g += `<text x="${m.l - 10}" y="${y0 + rowH / 2 + 4}" text-anchor="end" class="t-sec">${esc(r.label.length > 18 ? r.label.slice(0, 17) + "…" : r.label)}</text>`;
      let acc = 0;
      const segs = series.map((se) => ({ se, v: r.parts[se.key] || 0 })).filter((s) => s.v > 0);
      segs.forEach((s, j) => {
        const x = m.l + (acc / max) * iw + (j > 0 ? 2 : 0);
        const w = Math.max(0, (s.v / max) * iw - (j > 0 ? 2 : 0));
        g += `<path class="mark" d="${rowPath(x, by, w, bh, j === segs.length - 1)}" fill="${s.se.color}"/>`;
        acc += s.v;
      });
      g += `<text x="${m.l + (totals[i] / max) * iw + 8}" y="${y0 + rowH / 2 + 4}" class="t-sec num">${fmt(totals[i])}</text>`;
      const t = tipFn ? tipFn(r, totals[i]) : tip(r.label, segs.map((s) => ({ color: s.se.color, label: s.se.label, value: fmt(s.v) })), `Total ${fmt(totals[i])}`);
      g += `<rect class="hit" x="0" y="${y0}" width="${W}" height="${rowH}" data-tip="${t}" ${onClickAttr ? onClickAttr(r) : ""}/>`;
    });
    g += `<line class="baseline" x1="${m.l}" x2="${m.l}" y1="${m.t}" y2="${H - m.b}"/>`;
    return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img">${g}</svg>`;
  }

  /** Donut. items: [{key, label, value, color}] */
  function donut({ size = 168, items, centerValue, centerLabel, onClickAttr }) {
    const total = items.reduce((s, x) => s + x.value, 0) || 1;
    const R = size / 2, r0 = R - 22, cx = R, cy = R;
    const gapAngle = items.filter((x) => x.value > 0).length > 1 ? 0.035 : 0; // surface gap between slices
    let a = -Math.PI / 2, g = "";
    items.forEach((it) => {
      if (!it.value) return;
      const sweep = (it.value / total) * Math.PI * 2;
      const a0 = a + gapAngle / 2, a1 = a + sweep - gapAngle / 2;
      a += sweep;
      if (a1 <= a0) return;
      const large = a1 - a0 > Math.PI ? 1 : 0;
      const p = (ang, rad) => `${cx + rad * Math.cos(ang)},${cy + rad * Math.sin(ang)}`;
      let d;
      if (sweep >= Math.PI * 2 - 1e-6) {
        d = `M${cx},${cy - R}A${R},${R} 0 1 1 ${cx - 0.01},${cy - R}Z M${cx},${cy - r0}A${r0},${r0} 0 1 0 ${cx + 0.01},${cy - r0}Z`;
      } else {
        d = `M${p(a0, R)}A${R},${R} 0 ${large} 1 ${p(a1, R)}L${p(a1, r0)}A${r0},${r0} 0 ${large} 0 ${p(a0, r0)}Z`;
      }
      const share = ((it.value / total) * 100).toFixed(1);
      g += `<path class="mark" data-key="${esc(it.key)}" d="${d}" fill="${it.color}" fill-rule="evenodd" data-tip="${tip(it.label, [{ color: it.color, label: "Vehicles", value: fmt(it.value) }, { label: "Share", value: share + "%" }])}" ${onClickAttr ? onClickAttr(it) : ""}/>`;
    });
    g += `<text x="${cx}" y="${cy + 2}" text-anchor="middle" class="t-strong" style="font-size:24px;letter-spacing:-0.02em">${esc(centerValue ?? fmt(total))}</text>`;
    g += `<text x="${cx}" y="${cy + 20}" text-anchor="middle">${esc(centerLabel ?? "Total")}</text>`;
    return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img">${g}</svg>`;
  }

  function donutLegend(items, { clickable = false } = {}) {
    const total = items.reduce((s, x) => s + x.value, 0) || 1;
    return `<div class="donut-legend">${items.map((it) => `
      <div class="dl${clickable ? " clickable" : ""}" data-key="${esc(it.key)}" ${clickable ? `data-filter-key="${esc(it.key)}"` : ""}>
        <i class="sw" style="background:${it.color}"></i><span class="nm" title="${esc(it.label)}">${esc(it.label)}</span>
        <span class="vv">${fmt(it.value)}</span><span class="pp">${((it.value / total) * 100).toFixed(1)}%</span>
      </div>`).join("")}</div>`;
  }

  /** Calendar heatmap: one cell per day, weeks as columns, sequential single-hue ramp. */
  function calendar({ width, start, end, counts, today, tipFn }) {
    const cell = 13, gap = 3, m = { t: 22, l: 30, r: 4, b: 4 };
    const s = new Date(start); s.setDate(s.getDate() - ((s.getDay() + 6) % 7)); // Monday
    const days = [];
    for (let d = new Date(s); d <= end; d.setDate(d.getDate() + 1)) days.push(new Date(d));
    const weeks = Math.ceil(days.length / 7);
    const W = Math.max(width, m.l + weeks * (cell + gap) + m.r);
    const H = m.t + 7 * (cell + gap) + m.b;
    const max = Math.max(...counts.values(), 1);
    const ramp = ["var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)", "var(--seq-6)"];
    const level = (n) => (n <= 0 ? "var(--seq-0)" : ramp[Math.min(ramp.length - 1, Math.floor((Math.log(n) / Math.log(max + 1)) * ramp.length))]);
    let g = "", lastMonth = -1;
    ["Mon", "", "Wed", "", "Fri", "", ""].forEach((d, i) => { if (d) g += `<text x="0" y="${m.t + i * (cell + gap) + 10}">${d}</text>`; });
    days.forEach((d, i) => {
      const w = Math.floor(i / 7), dow = i % 7;
      const x = m.l + w * (cell + gap), y = m.t + dow * (cell + gap);
      if (d < start) return;
      if (d.getDate() <= 7 && dow === 0 && d.getMonth() !== lastMonth || (i === 0)) {
        if (d.getMonth() !== lastMonth) {
          g += `<text x="${x}" y="${m.t - 8}" class="t-sec">${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getMonth()]}${d.getMonth() === 0 || lastMonth === -1 ? " " + String(d.getFullYear()).slice(2) : ""}</text>`;
          lastMonth = d.getMonth();
        }
      }
      const key = isoDay(d);
      const n = counts.get(key) || 0;
      const isToday = today && key === isoDay(today);
      g += `<rect class="mark" x="${x}" y="${y}" width="${cell}" height="${cell}" rx="3" fill="${level(n)}" ${isToday ? 'stroke="var(--text)" stroke-width="1.5"' : ""} data-tip="${tipFn(d, n)}"/>`;
    });
    return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img">${g}</svg>`;
  }

  function isoDay(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  /* ---- global hover layer ---- */
  function installTooltips() {
    const tt = document.getElementById("tooltip");
    let cur = null;
    const place = (e) => {
      const pad = 14, r = tt.getBoundingClientRect();
      let x = e.clientX + pad, y = e.clientY + pad;
      if (x + r.width > innerWidth - 8) x = e.clientX - r.width - pad;
      if (y + r.height > innerHeight - 8) y = e.clientY - r.height - pad;
      tt.style.left = x + "px"; tt.style.top = y + "px";
    };
    document.addEventListener("mouseover", (e) => {
      const t = e.target.closest?.("[data-tip]");
      if (t === cur) return;
      if (cur) { cur.closest(".chart")?.classList.remove("dim"); cur.classList.remove("hl"); }
      cur = t;
      if (!t) { tt.hidden = true; return; }
      tt.innerHTML = t.getAttribute("data-tip");
      tt.hidden = false;
      if (t.classList.contains("mark") && t.closest(".chart.donut")) { t.closest(".chart").classList.add("dim"); t.classList.add("hl"); }
      place(e);
    });
    document.addEventListener("mousemove", (e) => { if (cur) place(e); });
    document.addEventListener("scroll", () => { tt.hidden = true; cur = null; }, true);
  }

  return { columns, hbars, donut, donutLegend, calendar, tip, installTooltips, isoDay, esc, fmt };
})();
