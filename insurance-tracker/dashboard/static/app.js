/* Policy Tracker - single-page app (no framework, no network beyond the local server). */
(() => {
  const { esc, fmt, tip } = Charts;
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  /* ------------------------------------------------------------------ model */
  const STATUS = [
    { key: "expired", label: "Expired", short: "", color: "var(--st-expired)", range: "Past end date" },
    { key: "critical", label: "Critical", short: "0–7 days", color: "var(--st-critical)", range: "Ends within 7 days" },
    { key: "due", label: "Due", short: "8–30 days", color: "var(--st-due)", range: "Ends in 8–30 days" },
    { key: "upcoming", label: "Upcoming", short: "31–60 days", color: "var(--st-upcoming)", range: "Ends in 31–60 days" },
    { key: "active", label: "Active", short: "60+ days", color: "var(--st-active)", range: "More than 60 days left" },
  ];
  const ST = Object.fromEntries(STATUS.map((s) => [s.key, s]));
  const ALERT_ORDER = ["critical", "due", "upcoming", "expired"];
  const CAT = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)", "var(--s7)"];
  const OTHER = "var(--s-other)";

  const S = {
    asof: null, vehicles: [], byId: new Map(), meta: {},
    route: "overview", charts: [], colorOf: {},
    f: {
      vehicles: { q: "", status: "", insurer: "", city: "", oem: "", financier: "", sort: { k: "days", dir: 1 }, page: 0 },
      alerts: { tab: "open", q: "", insurer: "", city: "", sort: { k: "days", dir: 1 } },
      analytics: { insurer: "", city: "", oem: "" },
    },
  };

  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const day = (s) => (s ? new Date(s + "T00:00:00") : null);
  const dfmt = (s) => { if (!s) return "—"; const d = day(s); return `${String(d.getDate()).padStart(2, "0")} ${MON[d.getMonth()]} ${d.getFullYear()}`; };
  const bucket = (d) => (d == null ? "active" : d < 0 ? "expired" : d <= 7 ? "critical" : d <= 30 ? "due" : d <= 60 ? "upcoming" : "active");
  const daysText = (d) => {
    if (d == null) return "—";
    if (d < 0) return `${fmt(-d)} day${d === -1 ? "" : "s"} ago`;
    if (d === 0) return "Ends today";
    return `${fmt(d)} day${d === 1 ? "" : "s"} left`;
  };
  const daysCls = (d) => (d == null ? "" : d < 0 ? "neg" : d <= 30 ? "soon" : "");
  const pill = (b) => `<span class="pill" style="--c:${ST[b].color}">${ST[b].label}</span>`;
  const vname = (v) => v.registration_no || "Not registered";
  // which cover ends first decides the alert; third-party cover is the legally required one
  const endNote = (v) => (v.endBy === "tp" ? `<div class="cell-sub">Third-party cover</div>` : "");

  function enrich(v) {
    v.endBy = v.tp_end && v.od_end && v.tp_end < v.od_end ? "tp" : "od";
    v.end = v.endBy === "tp" ? v.tp_end : v.od_end;
    v.days = v.end ? Math.round((day(v.end) - S.asof) / 864e5) : null;
    v.bucket = bucket(v.days);
    v.brand = v.oem || v.make || "Unknown";
    v.cityName = v.city_clean || v.city || "Unknown";
    v.fin = v.financier || "No financier";
    v.search = [v.registration_no, v.chassis_no, v.policy_no, v.engine_no, v.insured_name, v.cityName, v.brand, v.model, v.insurer]
      .filter(Boolean).join(" ").toUpperCase();
    return v;
  }

  function alerts() {
    return S.vehicles.filter((v) => v.bucket !== "active").map((v) => ({ v }));
  }

  /* -------------------------------------------------------------- data I/O */
  async function api(path, body) {
    const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }

  async function load() {
    const d = await api("/api/vehicles");
    S.asof = day(d.asof);
    S.meta = d;
    S.vehicles = d.vehicles.map(enrich);
    S.byId = new Map(S.vehicles.map((v) => [v.id, v]));
    // colour follows the entity: slots assigned once from the full fleet, never re-ranked by filters
    for (const field of ["insurer", "cityName", "brand"]) {
      const ranked = countBy(S.vehicles, (v) => v[field]);
      S.colorOf[field] = Object.fromEntries(ranked.map(([k], i) => [k, i < CAT.length ? CAT[i] : OTHER]));
    }
  }

  const countBy = (arr, fn) => {
    const m = new Map();
    arr.forEach((x) => { const k = fn(x); m.set(k, (m.get(k) || 0) + 1); });
    return [...m.entries()].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])));
  };
  const uniq = (field) => [...new Set(S.vehicles.map((v) => v[field]).filter(Boolean))].sort();

  /* ------------------------------------------------------------ app shell */
  const ROUTES = {
    overview: { title: "Overview", icon: "overview", render: renderOverview },
    alerts: { title: "Expiry alerts", icon: "bell", render: renderAlerts },
    vehicles: { title: "Vehicle register", icon: "table", render: renderVehicles },
    analytics: { title: "Analytics", icon: "chart", render: renderAnalytics },
    import: { title: "Add policies", icon: "upload", render: renderImport, group: "Data" },
  };

  function renderShell() {
    const dueSoon = alerts().filter((a) => a.v.bucket === "critical" || a.v.bucket === "due").length;
    let lastGroup = "Workspace";
    $("#nav").innerHTML = `<div class="nav-label">Workspace</div>` + Object.entries(ROUTES).map(([k, r]) =>
      (r.group && r.group !== lastGroup ? `<div class="nav-label">${(lastGroup = r.group)}</div>` : "") +
      `<a href="#/${k}" class="${S.route === k ? "active" : ""}" data-route="${k}" title="${r.title}">${icon(r.icon, 17)}<span class="nav-text">${r.title}</span>${k === "alerts" && dueSoon ? `<span class="count" title="Policies ending within 30 days">${dueSoon}</span>` : ""}</a>`).join("");
    $("#asof").innerHTML = `${icon("calendar", 14)}<span>As of ${S.asof.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })}</span>`;
    renderBell();
  }

  function renderBell() {
    const soon = alerts().filter((a) => a.v.bucket === "critical" || a.v.bucket === "due").length;
    $("#bell-btn").innerHTML = icon("bell", 18) + (soon ? `<span class="badge" title="Policies ending within 30 days">${soon > 99 ? "99+" : soon}</span>` : "");
    if (!$("#notif-panel").hidden) renderNotifPanel();
  }

  function renderNotifPanel() {
    const all = alerts();
    let body = "";
    for (const b of ALERT_ORDER) {
      const items = all.filter((a) => a.v.bucket === b).sort((x, y) => (b === "expired" ? y.v.days - x.v.days : x.v.days - y.v.days));
      if (!items.length) continue;
      body += `<div class="np-group"><div class="np-group-h"><i class="sw" style="background:${ST[b].color};border-radius:50%"></i>${ST[b].label}${ST[b].short ? ` · ${ST[b].short}` : ""}<span class="muted">${items.length} total</span></div>`;
      body += items.slice(0, 4).map((a) => `
        <div class="np-item" data-open="${a.v.id}">
          <div class="np-text">
            <div class="np-title">${esc(vname(a.v))} ${a.v.days < 0 ? "expired" : "expires"} ${a.v.days < 0 ? daysText(a.v.days) : a.v.days === 0 ? "today" : `in ${fmt(a.v.days)} day${a.v.days === 1 ? "" : "s"}`}</div>
            <div class="np-meta">${esc(a.v.insurer)} · ${a.v.endBy === "tp" ? "third-party cover " : ""}ends ${dfmt(a.v.end)} · ${esc(a.v.cityName)}</div>
          </div>
        </div>`).join("");
      if (items.length > 4) body += `<a class="np-more" href="#/alerts" data-tab="${b}">View all ${items.length} ${ST[b].label.toLowerCase()} policies</a>`;
      body += `</div>`;
    }
    $("#notif-panel").innerHTML = `
      <div class="np-head"><h3>Expiry alerts</h3></div>
      <div class="np-body">${body || `<div class="np-empty">${icon("inbox", 28)}<div>No open expiry alerts</div></div>`}</div>
      <div class="np-foot"><span class="muted">${all.length} open</span><a href="#/alerts" data-tab="open">Open expiry alerts</a></div>`;
  }

  function navigate() {
    const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
    S.route = ROUTES[path] ? path : "overview";
    if (query) {
      const p = new URLSearchParams(query);
      const f = S.f[S.route];
      if (f) for (const [k, v] of p) if (k in f) f[k] = v;
      if (p.get("open")) setTimeout(() => openDrawer(p.get("open")), 0);
      if (S.route === "vehicles") S.f.vehicles.page = 0;
    }
    renderShell();
    $("#page-title").textContent = ROUTES[S.route].title;
    $("#page-sub").textContent = {
      overview: "Fleet insurance position and upcoming expiries",
      alerts: "Track and action policies approaching or past expiry",
      vehicles: "Every insured vehicle with its current policy",
      analytics: "Expiry patterns by date, city, brand and insurer",
      import: "Upload new or updated policy PDFs and add them to the register",
    }[S.route];
    S.charts = [];
    $("#view").innerHTML = ROUTES[S.route].render();
    afterRender();
    $("#sidebar").classList.remove("open");
  }

  function afterRender() {
    drawCharts();
    if (S.route === "vehicles") updateVehicles();
    if (S.route === "alerts") updateAlerts();
    if (S.route === "analytics") updateAnalytics();
    if (S.route === "import") updateImport();
  }

  function chart(id, fn) { S.charts.push({ id, fn }); return `<div class="chart" id="${id}"></div>`; }
  function drawCharts() {
    for (const c of S.charts) {
      const el = document.getElementById(c.id);
      if (el) el.innerHTML = c.fn(el.clientWidth);
    }
  }

  /* -------------------------------------------------------------- overview */
  function months(from, to) {
    const out = [];
    const d = new Date(from.getFullYear(), from.getMonth(), 1);
    while (d <= to) {
      out.push({ key: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`, label: MON[d.getMonth()], sub: (d.getMonth() === 0 || !out.length) ? String(d.getFullYear()) : "", date: new Date(d) });
      d.setMonth(d.getMonth() + 1);
    }
    return out;
  }

  function expiryTimeline(V, id, height = 270) {
    const ends = V.map((v) => day(v.end)).filter(Boolean);
    if (!ends.length) return `<div class="empty-state">No policies match these filters</div>`;
    const lo = new Date(Math.min(...ends, S.asof)), hi = new Date(Math.max(...ends, S.asof));
    const cats = months(lo, hi);
    const data = {};
    V.forEach((v) => { if (!v.end) return; const k = v.end.slice(0, 7); (data[k] ||= {})[v.bucket] = (data[k][v.bucket] || 0) + 1; });
    const ti = cats.findIndex((c) => c.date.getFullYear() === S.asof.getFullYear() && c.date.getMonth() === S.asof.getMonth());
    const dim = new Date(S.asof.getFullYear(), S.asof.getMonth() + 1, 0).getDate();
    const series = STATUS.map((s) => ({ key: s.key, label: s.label, color: s.color }));
    return chart(id, (w) => Charts.columns({
      width: w, height, cats, series, data,
      marker: ti >= 0 ? { index: ti, frac: (S.asof.getDate() - 0.5) / dim, label: "Today" } : null,
      tipFn: (c, total) => tip(`${c.date.toLocaleString("en-GB", { month: "long", year: "numeric" })}`,
        STATUS.filter((s) => data[c.key]?.[s.key]).map((s) => ({ color: s.color, label: s.label, value: fmt(data[c.key][s.key]) })),
        `${fmt(total)} polic${total === 1 ? "y" : "ies"} ending this month`),
    }));
  }

  function statusLegend() {
    return `<div class="legend">${STATUS.map((s) => `<span class="li"><i class="sw" style="background:${s.color}"></i>${s.label}${s.short ? ` <span class="v">${s.short}</span>` : ""}</span>`).join("")}</div>`;
  }

  function statusDonut(V, id, clickable) {
    const items = STATUS.map((s) => ({ key: s.key, label: s.label, value: V.filter((v) => v.bucket === s.key).length, color: s.color }));
    const attr = clickable ? (it) => `data-goto-status="${it.key}" style="cursor:pointer"` : null;
    return `<div class="donut-wrap"><div class="chart donut">${Charts.donut({ items, centerLabel: "Vehicles", onClickAttr: attr })}</div>${Charts.donutLegend(items)}</div>`;
  }

  function renderOverview() {
    const V = S.vehicles;
    const n = (b) => V.filter((v) => v.bucket === b).length;
    const soon = n("critical") + n("due");
    const fireYes = V.filter((v) => v.fire_covered === "Yes").length;
    const fireCond = V.filter((v) => (v.fire_covered || "").startsWith("Yes -")).length;
    const fireNo = V.length - fireYes - fireCond;
    const chYes = V.filter((v) => v.chassis_damage_covered === "Yes").length;
    const insurers = countBy(V, (v) => v.insurer);

    const next = V.filter((v) => v.days != null && v.days >= 0 && v.days <= 60).sort((a, b) => a.days - b.days).slice(0, 8);
    const kpi = (label, value, sub, ic, href, meter) => `
      <a class="card kpi" href="${href}" style="text-decoration:none;color:inherit">
        <div class="k-label">${icon(ic, 15)}${label}</div>
        <div class="k-value">${value}</div>
        ${meter || ""}
        <div class="k-sub">${sub}</div>
      </a>`;
    const meter = (parts) => `<div class="k-meter" style="display:flex;gap:2px">${parts.filter((p) => p.v > 0).map((p) => `<span style="width:${(p.v / V.length) * 100}%;background:${p.c}"></span>`).join("")}</div>`;

    const segbar = (parts) => `<div class="seg-bar">${parts.filter((p) => p.v > 0).map((p) => `<div class="${p.dark ? "dark-ink" : ""}" style="flex:${p.v};background:${p.c}" data-tip="${tip(p.l, [{ color: p.c, label: "Vehicles", value: fmt(p.v) }, { label: "Share", value: ((p.v / V.length) * 100).toFixed(1) + "%" }])}">${p.v / V.length > 0.08 ? `${((p.v / V.length) * 100).toFixed(0)}%` : ""}</div>`).join("")}</div>`;

    return `
      ${soon ? `<div class="attention">
        <span class="a-icon">${icon("alert", 20)}</span>
        <div class="a-text"><b>${soon} polic${soon === 1 ? "y ends" : "ies end"} within the next 30 days.</b> <span>${n("critical") ? `${n("critical")} of them end within 7 days.` : "None end within the next 7 days."} Arrange new policies before these dates to avoid a gap in cover.</span></div>
        <a class="btn sm" href="#/alerts?tab=${n("critical") ? "critical" : "due"}">View alerts ${icon("chevronRight", 14)}</a>
      </div>` : ""}

      <div class="grid g-kpi">
        ${kpi("Vehicles insured", fmt(V.length), `<span>${insurers.length} insurers</span><span>${fmt(S.meta.policies)} policies</span>`, "truck", "#/vehicles?status=",
          meter(STATUS.map((s) => ({ v: n(s.key), c: s.color }))))}
        ${kpi("Active cover", fmt(n("active")), `<span>More than 60 days remaining</span>`, "shieldCheck", "#/vehicles?status=active",
          meter([{ v: n("active"), c: "var(--st-active)" }]))}
        ${kpi("Ending within 60 days", fmt(soon + n("upcoming")), `<span><i class="sw" style="background:var(--st-critical)"></i> ${n("critical")} in 7 d</span><span><i class="sw" style="background:var(--st-due)"></i> ${n("due")} in 30 d</span><span><i class="sw" style="background:var(--st-upcoming)"></i> ${n("upcoming")} in 60 d</span>`, "clock", "#/alerts?tab=open",
          meter([{ v: n("critical"), c: "var(--st-critical)" }, { v: n("due"), c: "var(--st-due)" }, { v: n("upcoming"), c: "var(--st-upcoming)" }]))}
        ${kpi("Expired", fmt(n("expired")), `<span>No newer policy uploaded yet</span>`, "alertCircle", "#/alerts?tab=expired",
          meter([{ v: n("expired"), c: "var(--st-expired)" }]))}
        ${kpi("Full fire cover", `${Math.floor((fireYes / V.length) * 100)}%`, `<span>${fmt(fireYes)} of ${fmt(V.length)} vehicles</span>${fireCond ? `<span class="k-warn">${fmt(fireCond)} not covered while charging</span>` : ""}${fireNo ? `<span class="k-warn">${fmt(fireNo)} no fire cover</span>` : ""}`, "flame", "#/vehicles",
          meter([{ v: fireYes, c: "var(--st-active)" }, { v: fireCond, c: "var(--st-critical)" }]))}
      </div>

      <div class="grid g-3-1 mt">
        <div class="card">
          <div class="card-h"><div class="t"><h2>Policy expiry timeline</h2><p>Policies ending each month (own-damage or third-party, whichever ends first), by current status</p></div></div>
          <div class="card-b">${expiryTimeline(V, "ov-timeline")}<div style="margin-top:10px">${statusLegend()}</div></div>
        </div>
        <div class="card">
          <div class="card-h"><div class="t"><h2>Expiry status</h2><p>Days remaining until the first cover ends</p></div></div>
          <div class="card-b">${statusDonut(V, "ov-status", true)}</div>
        </div>
      </div>

      <div class="grid g-3-1 mt">
        <div class="card">
          <div class="card-h"><div class="t"><h2>Next expiries</h2><p>The soonest policies to end in the next 60 days</p></div><a class="btn sm ghost" href="#/alerts?tab=open">View all ${icon("chevronRight", 14)}</a></div>
          <div class="card-b flush"><div class="table-wrap">
          ${next.length ? `<table class="data"><thead><tr><th>Vehicle</th><th>Insurer</th><th>Ends on</th><th>Remaining</th><th>Status</th></tr></thead><tbody>
            ${next.map((v) => `<tr data-open="${v.id}">
              <td><div class="cell-main">${esc(vname(v))}</div><div class="cell-sub mono">${esc(v.chassis_no)}</div></td>
              <td><div>${esc(v.insurer)}</div><div class="cell-sub">${esc(v.cityName)}</div></td>
              <td class="num nowrap">${dfmt(v.end)}${endNote(v)}</td>
              <td><span class="days ${daysCls(v.days)}">${daysText(v.days)}</span></td>
              <td>${pill(v.bucket)}</td></tr>`).join("")}
          </tbody></table>` : `<div class="empty-state">${icon("checkCircle", 26)}<b>Nothing ends in the next 60 days</b></div>`}
          </div></div>
        </div>
        <div class="card">
          <div class="card-h"><div class="t"><h2>Insurers</h2><p>Current policy per vehicle</p></div></div>
          <div class="card-b"><div class="donut-wrap"><div class="chart donut">${Charts.donut({ items: insurers.map(([k, c]) => ({ key: k, label: k, value: c, color: S.colorOf.insurer[k] })), centerLabel: "Vehicles" })}</div>
            ${Charts.donutLegend(insurers.map(([k, c]) => ({ key: k, label: k, value: c, color: S.colorOf.insurer[k] })))}</div></div>
        </div>
      </div>

      <div class="card mt">
        <div class="card-h"><div class="t"><h2>Own-damage coverage</h2><p>Fire and chassis damage protection across the fleet</p></div></div>
        <div class="card-b"><div class="grid g-2" style="gap:28px">
            <div class="cov-row"><div class="cov-h"><b>Fire cover</b><span class="muted">${fmt(fireYes)} of ${fmt(V.length)} vehicles fully covered</span></div>
              ${segbar([{ l: "Covered", v: fireYes, c: "var(--st-active)" }, { l: "Not covered while charging", v: fireCond, c: "var(--st-critical)", dark: true }, { l: "Not covered", v: fireNo, c: "var(--st-expired)" }])}
              <div class="legend" style="margin-top:8px"><span class="li"><i class="sw" style="background:var(--st-active)"></i>Covered <span class="v">${fmt(fireYes)}</span></span><span class="li"><i class="sw" style="background:var(--st-critical)"></i>Not covered while charging <span class="v">${fmt(fireCond)}</span></span>${fireNo ? `<span class="li"><i class="sw" style="background:var(--st-expired)"></i>Not covered <span class="v">${fmt(fireNo)}</span></span>` : ""}</div></div>
            <div class="cov-row" style="margin-top:0"><div class="cov-h"><b>Chassis damage cover</b><span class="muted">${fmt(chYes)} of ${fmt(V.length)} vehicles</span></div>
              ${segbar([{ l: "Covered", v: chYes, c: "var(--st-active)" }, { l: "Not covered", v: V.length - chYes, c: "var(--st-expired)" }])}
              <div class="legend" style="margin-top:8px"><span class="li"><i class="sw" style="background:var(--st-active)"></i>Covered under Section I, 10 insured perils <span class="v">${fmt(chYes)}</span></span></div></div>
        </div></div>
      </div>
      </div>`;
  }

  /* ---------------------------------------------------------------- alerts */
  function renderAlerts() {
    const f = S.f.alerts;
    const opt = (list, val, all) => `<option value="">${all}</option>` + list.map((x) => `<option ${x === val ? "selected" : ""} value="${esc(x)}">${esc(x)}</option>`).join("");
    return `
      <div class="toolbar">
        <div class="input-icon">${icon("search", 15)}<input class="input" id="rn-q" type="search" placeholder="Filter by vehicle, chassis or policy" value="${esc(f.q)}"></div>
        <select class="select ${f.insurer ? "active-filter" : ""}" data-f="alerts.insurer">${opt(uniq("insurer"), f.insurer, "All insurers")}</select>
        <select class="select ${f.city ? "active-filter" : ""}" data-f="alerts.city">${opt(uniq("cityName"), f.city, "All cities")}</select>
      </div>
      <div id="rn-region"></div>`;
  }

  function alertRows() {
    const f = S.f.alerts;
    const q = f.q.trim().toUpperCase();
    const base = S.vehicles.filter((v) => (!f.insurer || v.insurer === f.insurer) && (!f.city || v.cityName === f.city)
      && (!q || v.search.includes(q)));
    const tabs = [
      { key: "open", label: "All open", test: (v) => v.bucket !== "active" },
      ...ALERT_ORDER.map((b) => ({ key: b, label: `${ST[b].label}`, sub: ST[b].short, test: (v) => v.bucket === b })),
    ];
    return { base, tabs };
  }

  function updateAlerts() {
    const f = S.f.alerts;
    const { base, tabs } = alertRows();
    const tab = tabs.find((t) => t.key === f.tab) || tabs[0];
    let rows = base.filter(tab.test);
    const sk = f.sort.k, dir = f.sort.dir;
    const urg = (v) => (v.days == null ? 1e9 : v.days >= 0 ? v.days : 1e6 - v.days); // soonest first, then most recently expired
    const val = (v) => ({ days: urg(v), vehicle: vname(v), insurer: v.insurer, end: v.end, city: v.cityName }[sk]);
    rows.sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * dir || a.id - b.id);
    const th = (k, label, cls = "") => `<th class="sortable ${cls}" data-sort="alerts:${k}">${label}${sk === k ? `<span class="sort">${icon(dir > 0 ? "arrowUp" : "arrowDown", 12)}</span>` : ""}</th>`;
    $("#rn-region").innerHTML = `
      <div class="segmented" style="margin-bottom:14px">${tabs.map((t) => `<button class="${t.key === tab.key ? "on" : ""}" data-rtab="${t.key}">${ST[t.key] ? `<i class="sw" style="background:${ST[t.key].color};border-radius:50%"></i>` : ""}${t.label}${t.sub ? ` <span class="muted">${t.sub}</span>` : ""}<span class="n">${base.filter(t.test).length}</span></button>`).join("")}</div>
      <div class="card">
        <div class="table-wrap" style="max-height:calc(100vh - 250px)">
        ${rows.length ? `<table class="data"><thead><tr>${th("vehicle", "Vehicle")}${th("insurer", "Insurer / policy")}${th("end", "Ends on")}${th("days", "Remaining")}<th>Status</th>${th("city", "City")}</tr></thead><tbody>
          ${rows.map((v) => {
            return `<tr data-open="${v.id}">
              <td><div class="cell-main">${esc(vname(v))}</div><div class="cell-sub mono">${esc(v.chassis_no)}</div></td>
              <td><div>${esc(v.insurer)}</div><div class="cell-sub mono">${esc(v.policy_no)}</div></td>
              <td class="num nowrap">${dfmt(v.end)}${endNote(v)}</td>
              <td><span class="days ${daysCls(v.days)}">${daysText(v.days)}</span></td>
              <td>${pill(v.bucket)}</td>
              <td>${esc(v.cityName)}</td>
            </tr>`;
          }).join("")}
        </tbody></table>` : `<div class="empty-state">${icon("checkCircle", 28)}<b>No policies in this view</b><span>Try another tab or clear the filters.</span></div>`}
        </div>
        <div class="table-foot"><span>${fmt(rows.length)} polic${rows.length === 1 ? "y" : "ies"}</span><span>An alert closes when a newer policy for the vehicle is added on the Add policies page</span></div>
      </div>`;
  }

  /* -------------------------------------------------------------- vehicles */
  const PAGE = 50;
  function renderVehicles() {
    const f = S.f.vehicles;
    const opt = (list, val, all) => `<option value="">${all}</option>` + list.map((x) => `<option ${x === val ? "selected" : ""} value="${esc(x)}">${esc(x)}</option>`).join("");
    return `
      <div class="toolbar">
        <div class="input-icon">${icon("search", 15)}<input class="input" id="vh-q" type="search" placeholder="Filter vehicles" value="${esc(f.q)}"></div>
        <select class="select ${f.status ? "active-filter" : ""}" data-f="vehicles.status"><option value="">All statuses</option>${STATUS.map((s) => `<option value="${s.key}" ${f.status === s.key ? "selected" : ""}>${s.label}${s.short ? ` (${s.short})` : ""}</option>`).join("")}</select>
        <select class="select ${f.insurer ? "active-filter" : ""}" data-f="vehicles.insurer">${opt(uniq("insurer"), f.insurer, "All insurers")}</select>
        <select class="select ${f.city ? "active-filter" : ""}" data-f="vehicles.city">${opt(uniq("cityName"), f.city, "All cities")}</select>
        <select class="select ${f.oem ? "active-filter" : ""}" data-f="vehicles.oem">${opt(uniq("brand"), f.oem, "All brands")}</select>
        <select class="select ${f.financier ? "active-filter" : ""}" data-f="vehicles.financier">${opt(uniq("fin"), f.financier, "All financiers")}</select>
        <button class="btn ghost sm" data-action="clear-vehicles">Clear</button>
        <span class="spacer"></span>
        <button class="btn sm" data-action="export">${icon("download", 14)}Export CSV</button>
      </div>
      <div id="vh-region"></div>`;
  }

  function vehicleRows() {
    const f = S.f.vehicles;
    const q = f.q.trim().toUpperCase();
    const rows = S.vehicles.filter((v) => (!f.status || v.bucket === f.status) && (!f.insurer || v.insurer === f.insurer)
      && (!f.city || v.cityName === f.city) && (!f.oem || v.brand === f.oem) && (!f.financier || v.fin === f.financier)
      && (!q || v.search.includes(q)));
    const { k, dir } = f.sort;
    const val = (v) => ({ days: v.days ?? 1e9, reg: vname(v), chassis: v.chassis_no, insurer: v.insurer, policy: v.policy_no, start: v.od_start, end: v.od_end, brand: v.brand, city: v.cityName }[k] ?? "");
    return rows.sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * dir || a.id - b.id);
  }

  function updateVehicles() {
    const f = S.f.vehicles;
    const rows = vehicleRows();
    const pages = Math.max(1, Math.ceil(rows.length / PAGE));
    f.page = Math.min(f.page, pages - 1);
    const shown = rows.slice(f.page * PAGE, f.page * PAGE + PAGE);
    const { k, dir } = f.sort;
    const th = (key, label, cls = "") => `<th class="sortable ${cls}" data-sort="vehicles:${key}">${label}${k === key ? `<span class="sort">${icon(dir > 0 ? "arrowUp" : "arrowDown", 12)}</span>` : ""}</th>`;
    const fire = (v) => v.fire_covered === "Yes" ? `<span class="yes">Yes</span>` : (v.fire_covered || "").startsWith("Yes") ? `<span class="cond" title="Excluded while charging">Conditional</span>` : `<span class="no">No</span>`;
    $("#vh-region").innerHTML = `
      <div class="card">
        <div class="table-wrap" style="max-height:calc(100vh - 210px)">
        ${rows.length ? `<table class="data"><thead><tr>
          ${th("reg", "Registration")}${th("chassis", "Chassis no.")}${th("insurer", "Insurer")}${th("policy", "Policy no.")}
          ${th("start", "Cover from")}${th("end", "Cover to")}${th("days", "Remaining")}<th>Status</th><th>Fire</th><th>Chassis damage</th>${th("brand", "Brand")}${th("city", "City")}
        </tr></thead><tbody>
        ${shown.map((v) => `<tr data-open="${v.id}">
          <td class="cell-main nowrap">${v.registration_no ? esc(v.registration_no) : `<span class="muted">Not registered</span>`}</td>
          <td class="mono nowrap">${esc(v.chassis_no)}</td>
          <td class="nowrap">${esc(v.insurer)}</td>
          <td class="mono nowrap">${esc(v.policy_no)}</td>
          <td class="num nowrap">${dfmt(v.od_start)}</td>
          <td class="num nowrap">${dfmt(v.od_end)}${v.endBy === "tp" ? `<div class="cell-sub">TP ends ${dfmt(v.tp_end)}</div>` : ""}</td>
          <td><span class="days ${daysCls(v.days)}">${daysText(v.days)}</span></td>
          <td>${pill(v.bucket)}</td>
          <td>${fire(v)}</td>
          <td>${v.chassis_damage_covered === "Yes" ? `<span class="yes">Yes</span>` : `<span class="no">No</span>`}</td>
          <td class="nowrap">${esc(v.brand)}</td>
          <td class="nowrap">${esc(v.cityName)}</td>
        </tr>`).join("")}
        </tbody></table>` : `<div class="empty-state">${icon("search", 26)}<b>No vehicles match these filters</b></div>`}
        </div>
        <div class="table-foot">
          <span>${rows.length ? `${fmt(f.page * PAGE + 1)}–${fmt(Math.min(rows.length, (f.page + 1) * PAGE))} of ${fmt(rows.length)} vehicles` : "0 vehicles"}</span>
          <div class="pager">
            <button class="btn sm ghost" data-page="-1" ${f.page === 0 ? "disabled" : ""} aria-label="Previous page">${icon("chevronLeft", 15)}</button>
            <span>Page ${f.page + 1} of ${pages}</span>
            <button class="btn sm ghost" data-page="1" ${f.page >= pages - 1 ? "disabled" : ""} aria-label="Next page">${icon("chevronRight", 15)}</button>
          </div>
        </div>
      </div>`;
  }

  function exportCsv() {
    const rows = vehicleRows();
    const cols = [
      ["Registration No", (v) => v.registration_no], ["Chassis No", (v) => v.chassis_no], ["Engine No", (v) => v.engine_no],
      ["Insurer", (v) => v.insurer], ["Policy No", (v) => v.policy_no], ["Policy Type", (v) => v.policy_type],
      ["OD Start", (v) => v.od_start], ["OD End", (v) => v.od_end], ["TP End", (v) => v.tp_end], ["Days Remaining", (v) => v.days], ["Expiry Status", (v) => ST[v.bucket].label],
      ["Fire Covered", (v) => v.fire_covered], ["Chassis Damage Covered", (v) => v.chassis_damage_covered],
      ["Brand", (v) => v.brand], ["Model", (v) => v.model], ["City", (v) => v.cityName], ["State", (v) => v.state],
      ["Financier", (v) => v.financier], ["Insured Name", (v) => v.insured_name],
    ];
    const q = (x) => { const s = x == null ? "" : String(x); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const csv = "﻿" + [cols.map((c) => c[0]).join(","), ...rows.map((v) => cols.map((c) => q(c[1](v))).join(","))].join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = `vehicle-insurance-register-${Charts.isoDay(S.asof)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast(`Exported ${fmt(rows.length)} vehicles`);
  }

  /* ------------------------------------------------------------- analytics */
  function renderAnalytics() {
    const f = S.f.analytics;
    const opt = (list, val, all) => `<option value="">${all}</option>` + list.map((x) => `<option ${x === val ? "selected" : ""} value="${esc(x)}">${esc(x)}</option>`).join("");
    return `
      <div class="toolbar">
        <span class="muted" style="display:inline-flex;align-items:center;gap:6px">${icon("filter", 14)}Filters</span>
        <select class="select ${f.insurer ? "active-filter" : ""}" data-f="analytics.insurer">${opt(uniq("insurer"), f.insurer, "All insurers")}</select>
        <select class="select ${f.city ? "active-filter" : ""}" data-f="analytics.city">${opt(uniq("cityName"), f.city, "All cities")}</select>
        <select class="select ${f.oem ? "active-filter" : ""}" data-f="analytics.oem">${opt(uniq("brand"), f.oem, "All brands")}</select>
        <button class="btn ghost sm" data-action="clear-analytics">Clear</button>
        <span class="spacer"></span><span class="result-count" id="an-count"></span>
      </div>
      <div id="an-region"></div>`;
  }

  function topWithOther(V, field, k = 7) {
    const ranked = countBy(V, (v) => v[field]);
    const named = ranked.filter(([key]) => S.colorOf[field][key] !== OTHER);
    const items = named.slice(0, k).map(([key, c]) => ({ key, label: key, value: c, color: S.colorOf[field][key] }));
    const rest = V.length - items.reduce((s, x) => s + x.value, 0);
    if (rest > 0) items.push({ key: "__other", label: "Other", value: rest, color: OTHER });
    return items;
  }

  function updateAnalytics() {
    const f = S.f.analytics;
    const V = S.vehicles.filter((v) => (!f.insurer || v.insurer === f.insurer) && (!f.city || v.cityName === f.city) && (!f.oem || v.brand === f.oem));
    $("#an-count").textContent = `${fmt(V.length)} of ${fmt(S.vehicles.length)} vehicles`;
    S.charts = [];
    if (!V.length) { $("#an-region").innerHTML = `<div class="card"><div class="empty-state">${icon("filter", 26)}<b>No vehicles match these filters</b></div></div>`; return; }

    // weekly workload: next 12 weeks from the Monday of this week
    const mon = new Date(S.asof); mon.setDate(mon.getDate() - ((mon.getDay() + 6) % 7));
    const weeks = Array.from({ length: 12 }, (_, i) => { const s = new Date(mon); s.setDate(s.getDate() + 7 * i); const e = new Date(s); e.setDate(e.getDate() + 6); return { key: String(i), s, e, label: s.toLocaleDateString("en-GB", { day: "numeric", month: "short" }), sub: i === 0 ? "This week" : "" }; });
    const wdata = {};
    V.forEach((v) => { const d = day(v.end); if (!d) return; const i = Math.floor((d - mon) / (7 * 864e5)); if (i >= 0 && i < 12) (wdata[i] ||= {})[v.bucket] = (wdata[i][v.bucket] || 0) + 1; });
    const series = STATUS.map((s) => ({ key: s.key, label: s.label, color: s.color }));

    // calendar
    const ends = V.map((v) => day(v.end)).filter(Boolean);
    const cs = new Date(Math.min(...ends, S.asof)); cs.setDate(1);
    const ce = new Date(Math.max(...ends)); ce.setMonth(ce.getMonth() + 1, 0);
    const byDay = new Map(), regsByDay = new Map();
    V.forEach((v) => { if (!v.end) return; byDay.set(v.end, (byDay.get(v.end) || 0) + 1); (regsByDay.get(v.end) || regsByDay.set(v.end, []).get(v.end)).push(vname(v)); });
    const busiest = [...byDay.entries()].sort((a, b) => b[1] - a[1])[0];

    const statusRows = (field, k = 10) => countBy(V, (v) => v[field]).slice(0, k).map(([key]) => ({ key, label: key, parts: Object.fromEntries(STATUS.map((s) => [s.key, V.filter((v) => v[field] === key && v.bucket === s.key).length])) }));
    const city = topWithOther(V, "cityName");
    const brand = topWithOther(V, "brand");
    const filterAttr = (field) => (it) => it.key === "__other" ? "" : `data-afilter="${field}" data-val="${esc(it.key)}" style="cursor:pointer"`;
    const legendClick = (items, field) => Charts.donutLegend(items).replace(/data-key="([^"]*)"/g, (m, k) => k === "__other" ? m : `${m} data-afilter="${field}" data-val="${k}" style="cursor:pointer"`);
    const n = (b) => V.filter((v) => v.bucket === b).length;
    const avgLeft = (() => { const a = V.filter((v) => v.days >= 0); return a.length ? Math.round(a.reduce((s, v) => s + v.days, 0) / a.length) : 0; })();
    const next90 = V.filter((v) => v.days >= 0 && v.days <= 90).length;

    $("#an-region").innerHTML = `
      <div class="grid g-kpi">
        <div class="card kpi" style="cursor:default"><div class="k-label">${icon("truck", 15)}Vehicles in view</div><div class="k-value">${fmt(V.length)}</div><div class="k-sub">${countBy(V, (v) => v.cityName).length} cities · ${countBy(V, (v) => v.brand).length} brands</div></div>
        <div class="card kpi" style="cursor:default"><div class="k-label">${icon("clock", 15)}Ending in next 90 days</div><div class="k-value">${fmt(next90)}</div><div class="k-sub">${((next90 / V.length) * 100).toFixed(1)}% of vehicles in view</div></div>
        <div class="card kpi" style="cursor:default"><div class="k-label">${icon("alertCircle", 15)}Expired</div><div class="k-value">${fmt(n("expired"))}</div><div class="k-sub">${((n("expired") / V.length) * 100).toFixed(1)}% of vehicles in view</div></div>
        <div class="card kpi" style="cursor:default"><div class="k-label">${icon("calendar", 15)}Busiest expiry date</div><div class="k-value" style="font-size:22px">${busiest ? dfmt(busiest[0]) : "—"}</div><div class="k-sub">${busiest ? `${fmt(busiest[1])} policies end on this day` : ""}</div></div>
        <div class="card kpi" style="cursor:default"><div class="k-label">${icon("shieldCheck", 15)}Average cover remaining</div><div class="k-value">${fmt(avgLeft)} <span style="font-size:15px;font-weight:500;color:var(--text-3)">days</span></div><div class="k-sub">Across policies still in force</div></div>
      </div>

      <div class="grid g-3-1 mt">
        <div class="card"><div class="card-h"><div class="t"><h2>Expiries by month</h2><p>End dates (whichever cover ends first), split by current status</p></div></div>
          <div class="card-b">${expiryTimeline(V, "an-months", 280)}<div style="margin-top:10px">${statusLegend()}</div></div></div>
        <div class="card"><div class="card-h"><div class="t"><h2>Expiry status</h2><p>Share of vehicles by days remaining</p></div></div>
          <div class="card-b">${statusDonut(V, "an-status", true)}</div></div>
      </div>

      <div class="card mt"><div class="card-h"><div class="t"><h2>Expiry calendar</h2><p>Number of policies ending on each day. The outlined cell is today.</p></div>
        <div class="legend" style="align-items:center"><span>Fewer</span>${["--seq-0", "--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5", "--seq-6"].map((c) => `<i class="sw" style="width:12px;height:12px;border-radius:3px;background:var(${c})"></i>`).join("")}<span>More</span></div></div>
        <div class="card-b cal">${chart("an-cal", (w) => Charts.calendar({ width: w, start: cs, end: ce, counts: byDay, today: S.asof,
          tipFn: (d, k) => { const key = Charts.isoDay(d); const regs = regsByDay.get(key) || []; return tip(d.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" }), [{ label: "Policies ending", value: fmt(k) }], regs.length ? regs.slice(0, 4).join(", ") + (regs.length > 4 ? ` and ${regs.length - 4} more` : "") : ""); } }))}</div></div>

      <div class="card mt"><div class="card-h"><div class="t"><h2>Policies ending, next 12 weeks</h2><p>Policies ending each week, starting ${weeks[0].label}</p></div></div>
          <div class="card-b">${chart("an-weeks", (w) => Charts.columns({ width: w, height: 250, cats: weeks, series, data: wdata,
            tipFn: (c, t) => tip(`Week of ${c.s.toLocaleDateString("en-GB", { day: "numeric", month: "short" })} – ${c.e.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}`,
              STATUS.filter((s) => wdata[c.key]?.[s.key]).map((s) => ({ color: s.color, label: s.label, value: fmt(wdata[c.key][s.key]) })), `${fmt(t)} ending`) }))}</div></div>

      <div class="grid g-2 mt">
        <div class="card"><div class="card-h"><div class="t"><h2>Vehicles by city</h2><p>Select a city to filter the page</p></div></div>
          <div class="card-b"><div class="donut-wrap"><div class="chart donut">${Charts.donut({ items: city, centerLabel: "Vehicles", onClickAttr: filterAttr("city") })}</div>${legendClick(city, "city")}</div></div></div>
        <div class="card"><div class="card-h"><div class="t"><h2>Vehicles by brand</h2><p>Select a brand to filter the page</p></div></div>
          <div class="card-b"><div class="donut-wrap"><div class="chart donut">${Charts.donut({ items: brand, centerLabel: "Vehicles", onClickAttr: filterAttr("oem") })}</div>${legendClick(brand, "oem")}</div></div></div>
      </div>

      <div class="grid g-2 mt">
        <div class="card"><div class="card-h"><div class="t"><h2>Expiry status by city</h2><p>Top cities by number of vehicles</p></div></div>
          <div class="card-b">${chart("an-city-st", (w) => Charts.hbars({ width: w, rows: statusRows("cityName"), series, labelW: 110 }))}<div style="margin-top:10px">${statusLegend()}</div></div></div>
        <div class="card"><div class="card-h"><div class="t"><h2>Expiry status by brand</h2><p>Top brands by number of vehicles</p></div></div>
          <div class="card-b">${chart("an-brand-st", (w) => Charts.hbars({ width: w, rows: statusRows("brand"), series, labelW: 140 }))}<div style="margin-top:10px">${statusLegend()}</div></div></div>
      </div>

      <div class="card mt"><div class="card-h"><div class="t"><h2>Expiry status by insurer</h2><p>Current policy per vehicle</p></div></div>
          <div class="card-b">${chart("an-ins-st", (w) => Charts.hbars({ width: w, rows: statusRows("insurer"), series, labelW: 120 }))}<div style="margin-top:10px">${statusLegend()}</div></div></div>`;
    drawCharts();
  }

  /* ---------------------------------------------------------------- import */
  const OUT_STYLE = {
    new: "var(--s1)", newer: "var(--st-active)", history: "var(--s-other)",
    duplicate: "var(--text-3)", same_policy: "var(--text-3)", batch_duplicate: "var(--text-3)", error: "var(--st-expired)",
  };
  const OUT_ORDER = ["new", "newer", "history", "error", "duplicate", "same_policy", "batch_duplicate"];
  S.imp = { batch: null, uploading: false, done: 0, total: 0, items: [], selected: new Set(), filter: "all", result: null, recent: null };

  function renderImport() {
    return `
      <div id="imp-result"></div>
      <div class="card">
        <div class="card-b">
          <div class="dropzone" id="dropzone">
            <div class="dz-icon">${icon("upload", 24)}</div>
            <h3>Drop policy PDFs or a whole folder here</h3>
            <p>Each policy is read and matched to the register by chassis number. Nothing is saved until you review the results and choose Import.</p>
            <div class="dz-actions">
              <button class="btn primary" data-action="imp-pick-files">${icon("filePlus", 15)}Select files</button>
              <button class="btn" data-action="imp-pick-folder">${icon("folder", 15)}Select folder</button>
            </div>
            <p style="margin-top:4px">PDF only, up to 30 MB each. Formats recognised: Royal Sundaram, ICICI Lombard, IFFCO-Tokio, Go Digit. Files stay on this computer.</p>
            <input type="file" id="imp-files" accept="application/pdf,.pdf" multiple hidden>
            <input type="file" id="imp-folder" webkitdirectory multiple hidden>
          </div>
        </div>
      </div>
      <div id="imp-region"></div>
      <div class="card mt">
        <div class="card-h"><div class="t"><h2>How matching works</h2><p>The chassis number decides whether a policy is new or belongs to a vehicle already in the register</p></div></div>
        <div class="card-b"><div class="how">
          <div class="step"><span class="n">1</span><div><b>New vehicle</b><span>The chassis number is not in the register yet, so the vehicle is added.</span></div></div>
          <div class="step"><span class="n">2</span><div><b>Newer policy</b><span>The vehicle exists and this policy ends later. It becomes the current policy, the old one moves to history, and its expiry alerts close.</span></div></div>
          <div class="step"><span class="n">3</span><div><b>Skipped</b><span>Files already imported, a policy number already on record, or a PDF that cannot be read are never imported.</span></div></div>
        </div></div>
      </div>
      <div class="card mt" id="imp-recent"></div>`;
  }

  function updateImport() {
    const im = S.imp;
    const res = $("#imp-result");
    if (res) {
      const r = im.result;
      res.innerHTML = r ? `<div class="success-panel"><span class="s-icon">${icon("checkCircle", 22)}</span>
        <div class="s-text"><b>${fmt(r.imported)} polic${r.imported === 1 ? "y" : "ies"} imported.</b>
        <span class="sec">${Object.entries(r.by_outcome).map(([k, n]) => `${fmt(n)} ${({ new: "new vehicle", newer: "newer policy", history: "older policy" })[k]}${n === 1 ? "" : "s"}`).join(", ")}${r.skipped ? `. ${fmt(r.skipped)} skipped because they were already in the system.` : "."}</span></div>
        <a class="btn sm" href="#/vehicles">Open vehicle register ${icon("chevronRight", 14)}</a></div>` : "";
    }
    const region = $("#imp-region");
    if (!region) return;
    if (im.uploading) {
      region.innerHTML = `<div class="card mt"><div class="card-b">
        <div class="progress-row"><span>Reading policies</span><span id="imp-count">${fmt(im.done)} of ${fmt(im.total)}</span></div>
        <div class="progress"><span id="imp-bar" style="width:${im.total ? (im.done / im.total) * 100 : 0}%"></span></div></div></div>`;
    } else if (im.items.length) {
      region.innerHTML = importReview();
    } else {
      region.innerHTML = "";
    }
    renderRecent();
  }

  function importReview() {
    const im = S.imp;
    const counts = Object.fromEntries(OUT_ORDER.map((o) => [o, im.items.filter((i) => i.outcome === o).length]));
    const label = (o) => im.items.find((i) => i.outcome === o)?.label || o;
    const rows = im.items.filter((i) => im.filter === "all" || i.outcome === im.filter)
      .sort((a, b) => OUT_ORDER.indexOf(a.outcome) - OUT_ORDER.indexOf(b.outcome) || a.name.localeCompare(b.name));
    const importable = im.items.filter((i) => i.importable);
    const sel = importable.filter((i) => im.selected.has(i.key)).length;
    const visImportable = rows.filter((i) => i.importable);
    const allOn = visImportable.length && visImportable.every((i) => im.selected.has(i.key));
    const detail = (i) => {
      const li = [];
      if (i.outcome === "newer" && i.current) li.push(`<li>Replaces current policy ${esc(i.current.policy_no)} ending ${dfmt(i.current.od_end)}</li>`);
      if (i.outcome === "history" && i.current) li.push(`<li>Vehicle's current policy ends ${dfmt(i.current.od_end)}; this one is kept as history</li>`);
      if (i.outcome === "duplicate") li.push(`<li>This exact file was imported before</li>`);
      if (i.outcome === "same_policy") li.push(`<li>Policy ${esc(i.fields?.policy_no)} is already stored from another file</li>`);
      if (i.outcome === "batch_duplicate") li.push(`<li>The same file appears twice in this upload</li>`);
      (i.changes || []).forEach((c) => li.push(`<li>${esc(c)}</li>`));
      (i.errors || []).forEach((e) => li.push(`<li class="err">${esc(e)}</li>`));
      (i.warnings || []).forEach((w) => li.push(`<li class="warn">${esc(w)}</li>`));
      return li.length ? `<ul class="detail-list">${li.join("")}</ul>` : `<span class="muted">—</span>`;
    };
    return `
      <div class="card mt">
        <div class="card-h"><div class="t"><h2>Review ${fmt(im.items.length)} file${im.items.length === 1 ? "" : "s"}</h2><p>Check the results, untick anything you do not want, then import</p></div></div>
        <div class="card-b" style="padding-bottom:12px">
          <div class="segmented"><button class="${im.filter === "all" ? "on" : ""}" data-imp-filter="all">All<span class="n">${im.items.length}</span></button>
            ${OUT_ORDER.filter((o) => counts[o]).map((o) => `<button class="${im.filter === o ? "on" : ""}" data-imp-filter="${o}"><i class="sw" style="background:${OUT_STYLE[o]};border-radius:50%"></i>${esc(label(o))}<span class="n">${counts[o]}</span></button>`).join("")}</div>
        </div>
        <div class="table-wrap" style="max-height:calc(100vh - 320px)">
          <table class="data"><thead><tr>
            <th style="width:34px"><input type="checkbox" class="chk" data-imp-all ${allOn ? "checked" : ""} ${visImportable.length ? "" : "disabled"} aria-label="Select all"></th>
            <th>File</th><th>Result</th><th>Vehicle</th><th>Insurer / policy</th><th>Cover period</th><th>Details</th></tr></thead><tbody>
          ${rows.map((i) => `<tr style="cursor:default">
            <td><input type="checkbox" class="chk" data-imp-key="${esc(i.key)}" ${i.importable ? "" : "disabled"} ${i.importable && im.selected.has(i.key) ? "checked" : ""} aria-label="Import ${esc(i.name)}"></td>
            <td style="max-width:240px"><div class="cell-main" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(i.name)}">${esc(i.name.split("/").pop())}</div>${i.name.includes("/") ? `<div class="cell-sub" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(i.name.split("/").slice(0, -1).join("/"))}</div>` : ""}</td>
            <td><span class="pill" style="--c:${OUT_STYLE[i.outcome]}">${esc(i.label)}</span></td>
            <td>${i.fields?.chassis_no ? `<div class="cell-main">${esc(i.fields.registration_no || "Not registered")}</div><div class="cell-sub mono">${esc(i.fields.chassis_no)}</div>` : `<span class="muted">—</span>`}</td>
            <td>${i.fields?.insurer ? `<div>${esc(i.fields.insurer)}</div><div class="cell-sub mono">${esc(i.fields.policy_no || "")}</div>` : `<span class="muted">—</span>`}</td>
            <td class="num nowrap">${i.fields?.od_end ? `${dfmt(i.fields.od_start)} –<br>${dfmt(i.fields.od_end)}` : `<span class="muted">—</span>`}</td>
            <td style="min-width:220px">${detail(i)}</td></tr>`).join("")}
          </tbody></table>
        </div>
        <div class="table-foot">
          <span>${fmt(sel)} of ${fmt(importable.length)} importable file${importable.length === 1 ? "" : "s"} selected</span>
          <div style="display:flex;gap:8px">
            <button class="btn sm ghost" data-action="imp-discard">Discard</button>
            <button class="btn sm primary" data-action="imp-commit" ${sel ? "" : "disabled"}>${icon("check", 14)}Import ${fmt(sel)} polic${sel === 1 ? "y" : "ies"}</button>
          </div>
        </div>
      </div>`;
  }

  async function renderRecent() {
    const el = $("#imp-recent");
    if (!el) return;
    if (S.imp.recent === null) {
      try { S.imp.recent = await api("/api/import/recent"); } catch (e) { S.imp.recent = []; }
    }
    const rows = S.imp.recent;
    const lbl = { new: "New vehicle", newer: "Newer policy", history: "Older policy" };
    el.innerHTML = `<div class="card-h"><div class="t"><h2>Recent imports</h2><p>Policies added through this page</p></div></div>
      <div class="card-b flush">${rows.length ? `<div class="table-wrap"><table class="data"><thead><tr><th>Imported</th><th>File</th><th>Result</th><th>Vehicle</th><th>Insurer</th><th>Cover to</th></tr></thead><tbody>
      ${rows.map((r) => `<tr ${r.policy_id ? `data-open="${r.policy_id}"` : 'style="cursor:default"'}>
        <td class="nowrap num">${new Date(r.imported_at).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}</td>
        <td>${esc(r.file_name.split("/").pop())}</td>
        <td><span class="pill" style="--c:${OUT_STYLE[r.outcome] || "var(--text-3)"}">${lbl[r.outcome] || esc(r.outcome)}</span></td>
        <td><div class="cell-main">${esc(r.registration_no || "Not registered")}</div><div class="cell-sub mono">${esc(r.chassis_no || "")}</div></td>
        <td>${esc(r.insurer || "")}</td><td class="num nowrap">${dfmt(r.od_end)}</td></tr>`).join("")}
      </tbody></table></div>` : `<div class="empty-state">${icon("inbox", 26)}<b>No policies imported yet</b><span>Policies you import here will be listed with their result.</span></div>`}</div>`;
  }

  async function filesFromDrop(dt) {
    const entries = [...(dt.items || [])].map((i) => i.webkitGetAsEntry?.()).filter(Boolean);
    if (!entries.length) return [...dt.files];
    const out = [];
    const walk = async (entry, path) => {
      if (entry.isFile) {
        const f = await new Promise((res, rej) => entry.file(res, rej));
        out.push({ file: f, path: path + f.name });
      } else if (entry.isDirectory) {
        const reader = entry.createReader();
        let batch;
        do {
          batch = await new Promise((res, rej) => reader.readEntries(res, rej));
          for (const e of batch) await walk(e, path + entry.name + "/");
        } while (batch.length);
      }
    };
    for (const e of entries) await walk(e, "");
    return out;
  }

  async function uploadFiles(list) {
    const files = list.map((x) => (x.file ? x : { file: x, path: x.webkitRelativePath || x.name }))
      .filter((x) => /\.pdf$/i.test(x.file.name));
    if (!files.length) { toast("No PDF files found in the selection"); return; }
    const im = S.imp;
    if (im.uploading) { toast("Please wait for the current upload to finish"); return; }
    if (!im.batch) im.batch = crypto.randomUUID ? crypto.randomUUID() : "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) => (c ^ (Math.random() * 16) >> c / 4).toString(16));
    Object.assign(im, { uploading: true, total: im.total + files.length, result: null, filter: "all" });
    updateImport();
    let next = 0;
    const worker = async () => {
      while (next < files.length) {
        const x = files[next++];
        try {
          await fetch(`/api/import/upload?batch=${im.batch}&name=${encodeURIComponent(x.path)}`, { method: "POST", headers: { "Content-Type": "application/pdf" }, body: x.file });
        } catch (e) { /* the file is reported as missing below */ }
        im.done++;
        const bar = $("#imp-bar"), cnt = $("#imp-count");
        if (bar) bar.style.width = `${(im.done / im.total) * 100}%`;
        if (cnt) cnt.textContent = `${fmt(im.done)} of ${fmt(im.total)}`;
      }
    };
    await Promise.all([worker(), worker(), worker()]);
    const prevSel = new Set(im.selected), prevKeys = new Set(im.items.map((i) => i.key));
    try { im.items = (await api(`/api/import/batch/${im.batch}`)).items; } catch (e) { toast("Could not read results: " + e.message); }
    im.selected = new Set(im.items.filter((i) => i.importable && (prevSel.has(i.key) || !prevKeys.has(i.key))).map((i) => i.key));
    im.uploading = false;
    updateImport();
  }

  async function commitImport() {
    const im = S.imp;
    const keys = [...im.selected];
    if (!keys.length) return;
    const btn = $('[data-action="imp-commit"]');
    if (btn) { btn.disabled = true; btn.textContent = "Importing…"; }
    try {
      im.result = await api("/api/import/commit", { batch: im.batch, keys });
    } catch (e) { toast("Import failed: " + e.message); if (btn) btn.disabled = false; return; }
    Object.assign(im, { batch: null, items: [], selected: new Set(), done: 0, total: 0, recent: null });
    await load();
    renderShell();
    updateImport();
    toast(`${fmt(im.result.imported)} polic${im.result.imported === 1 ? "y" : "ies"} imported`);
  }

  async function discardImport() {
    const im = S.imp;
    if (im.batch) { try { await api("/api/import/discard", { batch: im.batch }); } catch (e) { /* staged files are cleared on restart anyway */ } }
    Object.assign(im, { batch: null, items: [], selected: new Set(), done: 0, total: 0, result: null });
    updateImport();
  }

  /* ---------------------------------------------------------------- drawer */
  async function openDrawer(id) {
    const v = S.byId.get(Number(id));
    const dr = $("#drawer");
    dr.innerHTML = `<div class="dr-head"><div class="dr-top"><span class="crumb">Vehicle</span><button class="icon-btn" data-action="close-drawer" aria-label="Close">${icon("x", 18)}</button></div><div class="loading" style="padding:30px 0">Loading</div></div>`;
    $("#scrim").hidden = false;
    dr.classList.add("open");
    dr.setAttribute("aria-hidden", "false");
        let r;
    try { r = await api(`/api/vehicle/${id}`); } catch (e) { dr.querySelector(".loading").textContent = "Could not load: " + e.message; return; }
    const lv = v || enrich({ ...r });
    const total = r.od_start && r.od_end ? (day(r.od_end) - day(r.od_start)) / 864e5 + 1 : null;
    const elapsed = total ? Math.min(total, Math.max(0, (S.asof - day(r.od_start)) / 864e5 + 1)) : 0;
    const pct = total ? (elapsed / total) * 100 : 0;
    const odDays = r.od_end ? Math.round((day(r.od_end) - S.asof) / 864e5) : null; // the OD bar shows OD days; the status pill uses whichever cover ends first
    const fireCls = r.fire_covered === "Yes" ? "yes" : (r.fire_covered || "").startsWith("Yes") ? "cond" : "no";
    const fireTxt = r.fire_covered === "Yes" ? "Covered" : (r.fire_covered || "").startsWith("Yes") ? "Not while charging" : "Not covered";
    const causes = Array.isArray(r.chassis_damage_causes) ? r.chassis_damage_causes : [];
    const addons = Array.isArray(r.addons) ? r.addons : [];
    const kv = (k, val, cls = "") => `<div class="${cls}"><div class="k">${k}</div><div class="v">${val == null || val === "" ? `<span class="muted">—</span>` : val}</div></div>`;

    dr.innerHTML = `
      <div class="dr-head">
        <div class="dr-top">
          <span class="crumb">Vehicle · ${esc(r.insurer)}</span>
          ${r.has_pdf ? `<a class="btn sm" href="/api/pdf/${r.id}" target="_blank" rel="noopener">${icon("file", 14)}Open policy PDF</a>` : ""}
          <button class="icon-btn" data-action="close-drawer" aria-label="Close">${icon("x", 18)}</button>
        </div>
        <div class="dr-title"><h2>${esc(r.registration_no || "Not registered")}</h2>${pill(lv.bucket)}</div>
        <div class="dr-subtitle">${esc([lv.brand, r.model].filter(Boolean).join(" · "))}${lv.cityName ? ` · ${esc(lv.cityName)}` : ""}</div>
      </div>
      <div class="dr-body">
        <section class="dr-section">
          <h3>${icon("calendar", 15)}Own-damage policy period</h3>
          <div class="term">
            <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px">
              <b style="font-size:15px">${dfmt(r.od_start)} – ${dfmt(r.od_end)}</b>
              <span class="days ${daysCls(odDays)}">${daysText(odDays)}</span>
            </div>
            <div class="term-bar"><span style="width:${pct}%;background:${ST[bucket(odDays)].color}"></span></div>
            <div class="term-labels"><span>${total ? `${Math.round(elapsed)} of ${Math.round(total)} days elapsed` : ""}</span><span>${pct.toFixed(0)}%</span></div>
          </div>
          <div class="kv" style="margin-top:16px">
            ${kv("Insurance company", esc(r.insurer))}
            ${kv("Policy number", `<span class="mono">${esc(r.policy_no)}</span>`)}
            ${kv("Policy type", esc(r.policy_type))}
            ${kv("Issued on", r.issue_date ? dfmt(r.issue_date) : null)}
            ${kv("Third-party cover until", r.tp_end ? dfmt(r.tp_end) + (lv.endBy === "tp" ? ` <span class="days soon">ends first</span>` : "") : null)}
            ${kv("Insured declared value", r.idv ? "₹ " + fmt(Math.round(Number(r.idv))) : null)}
          </div>
        </section>

        <section class="dr-section">
          <h3>${icon("shield", 15)}Own-damage coverage</h3>
          <div class="cover-cards">
            <div class="cover-card"><div class="cc-h">${icon("flame", 15)}Fire</div><div class="cc-v ${fireCls}">${icon(fireCls === "yes" ? "checkCircle" : "alertCircle", 18)}${fireTxt}</div><div class="cc-n">${esc(r.fire_covered === "Yes" ? (r.fire_note || "Covered under Section I") : "Fire while charging is excluded")}</div></div>
            <div class="cover-card"><div class="cc-h">${icon("truck", 15)}Chassis damage</div><div class="cc-v ${r.chassis_damage_covered === "Yes" ? "yes" : "no"}">${icon(r.chassis_damage_covered === "Yes" ? "checkCircle" : "alertCircle", 18)}${r.chassis_damage_covered === "Yes" ? "Covered" : "Not covered"}</div><div class="cc-n">${causes.length} insured causes under Section I</div></div>
          </div>
          ${r.fire_exclusion_text ? `<div class="note-box"><b>Exclusion.</b> ${esc(r.fire_exclusion_text)}</div>` : ""}
          ${causes.length ? `<div class="k muted" style="margin-top:14px;font-size:12px">Causes of chassis damage that are covered</div><ul class="causes">${causes.map((c) => `<li>${icon("check", 14)}<span>${esc(c)}</span></li>`).join("")}</ul>` : ""}
          ${addons.length ? `<div class="k muted" style="margin-top:14px;font-size:12px;margin-bottom:6px">Add-on covers</div><div class="chips">${addons.map((a) => `<span class="tag">${esc(a)}</span>`).join("")}</div>` : ""}
        </section>

        <section class="dr-section">
          <h3>${icon("truck", 15)}Vehicle</h3>
          <div class="kv">
            ${kv("Registration number", r.registration_no ? esc(r.registration_no) : `<span class="muted">Not printed (new vehicle)</span>`)}
            ${kv("Chassis number", `<span class="mono">${esc(r.chassis_no)}</span>`)}
            ${kv("Engine / motor number", `<span class="mono">${esc(r.engine_no)}</span>`)}
            ${kv("Brand", esc(lv.brand))}
            ${kv("Model", esc(r.model))}
            ${kv("Vehicle class", esc(r.vehicle_class))}
            ${kv("Year of manufacture", esc(r.year_of_manufacture))}
            ${kv("Fuel", esc(r.fuel_type))}
            ${kv("City", esc(lv.cityName))}
            ${kv("State", esc(r.state))}
          </div>
        </section>

        <section class="dr-section">
          <h3>${icon("building", 15)}Ownership and finance</h3>
          <div class="kv">
            ${kv("Insured", esc(r.insured_name))}
            ${kv("Financier / hypothecation", esc(r.financier || r.hypothecation))}
            ${kv("Previous policy", r.previous_policy_no ? `<span class="mono">${esc(r.previous_policy_no)}</span>` : null)}
            ${kv("Previous insurer", esc(r.previous_insurer))}
          </div>
          ${r.history?.length ? `<div class="k muted" style="margin-top:14px;font-size:12px">Earlier policies on record</div>${r.history.map((h) => `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border)"><span class="mono">${esc(h.policy_no)}</span><span class="muted">${dfmt(h.od_start)} – ${dfmt(h.od_end)}</span></div>`).join("")}` : ""}
        </section>

        <div class="dr-foot">
          ${r.status === "verified" ? `<span class="pill" style="--c:var(--st-active)">Verified</span>` : `<span class="pill" style="--c:var(--st-critical)" title="${esc((r.issues || []).map((x) => x.message).join("; "))}">Needs review</span>`}
          <span class="muted">Source file: ${esc((r.file || "").split(/[\\/]/).pop())}</span>
        </div>
      </div>`;
  }

  function closeDrawer() {
    $("#drawer").classList.remove("open");
    $("#drawer").setAttribute("aria-hidden", "true");
    $("#scrim").hidden = true;
  }

  /* ---------------------------------------------------------------- search */
  function runSearch(q) {
    const box = $("#search-results");
    q = q.trim().toUpperCase();
    if (q.length < 2) { box.classList.remove("open"); return; }
    const hits = S.vehicles.filter((v) => v.search.includes(q)).slice(0, 8);
    const hl = (s) => { s = String(s ?? ""); const i = s.toUpperCase().indexOf(q); return i < 0 ? esc(s) : esc(s.slice(0, i)) + `<mark>${esc(s.slice(i, i + q.length))}</mark>` + esc(s.slice(i + q.length)); };
    box.innerHTML = hits.length ? hits.map((v, i) => `
      <div class="sr-item ${i === 0 ? "sel" : ""}" data-open="${v.id}" role="option">
        <div class="sr-main"><div class="sr-title">${hl(vname(v))}</div><div class="sr-meta"><span class="mono">${hl(v.chassis_no)}</span> · ${hl(v.policy_no)} · ${esc(v.insurer)}</div></div>
        ${pill(v.bucket)}
      </div>`).join("") : `<div class="sr-empty">No vehicle matches "${esc(q)}"</div>`;
    box.classList.add("open");
  }

  /* ----------------------------------------------------------------- misc */
  function toast(msg) {
    const t = document.createElement("div");
    t.className = "toast";
    t.innerHTML = `${icon("checkCircle", 16)}<span>${esc(msg)}</span>`;
    $("#toasts").appendChild(t);
    setTimeout(() => t.remove(), 3200);
  }

  function effectiveTheme() {
    const t = document.documentElement.dataset.theme;
    return t || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }
  function paintThemeBtn() { $("#theme-btn").innerHTML = icon(effectiveTheme() === "dark" ? "sun" : "moon", 18); }

  /* --------------------------------------------------------------- events */
  function bind() {
    $(".search-icon").innerHTML = icon("search", 16);
    $("#menu-btn").innerHTML = icon("panel", 18);
    paintThemeBtn();

    document.addEventListener("click", (e) => {
      const t = e.target;
      if (t.closest("select, textarea, input")) return;

      const tabLink = t.closest("[data-tab]");
      if (tabLink) { S.f.alerts.tab = tabLink.dataset.tab; $("#notif-panel").hidden = true; if (S.route === "alerts") { e.preventDefault(); updateAlerts(); } return; }

      const open = t.closest("[data-open]");
      if (open) {
        $("#notif-panel").hidden = true;
        $("#search-results").classList.remove("open");
        openDrawer(open.dataset.open);
        return;
      }
      const gs = t.closest("[data-goto-status]");
      if (gs) { location.hash = `#/vehicles?status=${gs.dataset.gotoStatus}`; return; }

      const af = t.closest("[data-afilter]");
      if (af) { S.f.analytics[af.dataset.afilter] = af.dataset.val; S.route === "analytics" ? navigateKeep() : null; return; }

      const rt = t.closest("[data-rtab]");
      if (rt) { S.f.alerts.tab = rt.dataset.rtab; updateAlerts(); return; }

      const sort = t.closest("[data-sort]");
      if (sort) {
        const [page, k] = sort.dataset.sort.split(":");
        const s = S.f[page].sort;
        s.dir = s.k === k ? -s.dir : 1; s.k = k;
        page === "vehicles" ? updateVehicles() : updateAlerts();
        return;
      }
      const pg = t.closest("[data-page]");
      if (pg && !pg.disabled) { S.f.vehicles.page += Number(pg.dataset.page); updateVehicles(); $("#vh-region .table-wrap").scrollTop = 0; return; }

      const impf = t.closest("[data-imp-filter]");
      if (impf) { S.imp.filter = impf.dataset.impFilter; updateImport(); return; }

      const act = t.closest("[data-action]")?.dataset.action;
      if (act === "imp-pick-files") return $("#imp-files").click();
      if (act === "imp-pick-folder") return $("#imp-folder").click();
      if (act === "imp-commit") return commitImport();
      if (act === "imp-discard") return discardImport();
      if (act === "close-drawer") return closeDrawer();
      if (act === "export") return exportCsv();
      if (act === "clear-vehicles") { Object.assign(S.f.vehicles, { q: "", status: "", insurer: "", city: "", oem: "", financier: "", page: 0 }); navigateKeep(); return; }
      if (act === "clear-analytics") { Object.assign(S.f.analytics, { insurer: "", city: "", oem: "" }); navigateKeep(); return; }

      if (t.closest("#bell-btn")) {
        const p = $("#notif-panel");
        p.hidden = !p.hidden;
        if (!p.hidden) renderNotifPanel();
        return;
      }
      if (!t.closest("#notif-panel")) $("#notif-panel").hidden = true;
      if (!t.closest("#search")) $("#search-results").classList.remove("open");
      if (t.closest("#theme-btn")) {
        const next = effectiveTheme() === "dark" ? "light" : "dark";
        document.documentElement.dataset.theme = next;
        try { localStorage.setItem("pt-theme", next); } catch (err) { /* storage unavailable */ }
        paintThemeBtn();
        return;
      }
      if (t.closest("#menu-btn")) {
        if (matchMedia("(max-width: 820px)").matches) { $("#sidebar").classList.toggle("open"); return; }
        const c = document.documentElement.classList.toggle("nav-collapsed");
        try { localStorage.setItem("pt-nav", c ? "collapsed" : "open"); } catch (err) { /* storage unavailable */ }
        setTimeout(drawCharts, 220); // charts re-fit the wider content area
        return;
      }
      if (t.closest("#scrim")) closeDrawer();
      if (!t.closest("#sidebar") && !t.closest("#menu-btn")) $("#sidebar").classList.remove("open");
    });

    document.addEventListener("change", (e) => {
      const t = e.target;
      if (t.dataset.f) {
        const [page, field] = t.dataset.f.split(".");
        S.f[page][field] = t.value;
        t.classList.toggle("active-filter", !!t.value);
        if (page === "vehicles") { S.f.vehicles.page = 0; updateVehicles(); }
        if (page === "alerts") updateAlerts();
        if (page === "analytics") updateAnalytics();
      }
      if (t.id === "imp-files" || t.id === "imp-folder") { uploadFiles([...t.files]); t.value = ""; return; }
      if (t.dataset.impKey !== undefined) {
        t.checked ? S.imp.selected.add(t.dataset.impKey) : S.imp.selected.delete(t.dataset.impKey);
        updateImport(); return;
      }
      if (t.dataset.impAll !== undefined) {
        const vis = S.imp.items.filter((i) => i.importable && (S.imp.filter === "all" || i.outcome === S.imp.filter));
        vis.forEach((i) => (t.checked ? S.imp.selected.add(i.key) : S.imp.selected.delete(i.key)));
        updateImport(); return;
      }
    });

    document.addEventListener("input", (e) => {
      const t = e.target;
      if (t.id === "vh-q") { S.f.vehicles.q = t.value; S.f.vehicles.page = 0; updateVehicles(); }
      if (t.id === "rn-q") { S.f.alerts.q = t.value; updateAlerts(); }
      if (t.id === "search-input") runSearch(t.value);
    });

    $("#search-input").addEventListener("keydown", (e) => {
      const items = $$("#search-results .sr-item");
      const i = items.findIndex((x) => x.classList.contains("sel"));
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (!items.length) return;
        const j = (i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items.forEach((x, k) => x.classList.toggle("sel", k === j));
      } else if (e.key === "Enter" && items[i]) {
        openDrawer(items[i].dataset.open);
        $("#search-results").classList.remove("open");
        e.target.blur();
      } else if (e.key === "Escape") { $("#search-results").classList.remove("open"); e.target.blur(); }
    });

    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#search-input").focus(); $("#search-input").select(); }
      if (e.key === "Escape") { closeDrawer(); $("#notif-panel").hidden = true; }
    });

    // drag and drop (files or folders) onto the import drop zone; never let the browser open a dropped PDF
    document.addEventListener("dragover", (e) => {
      e.preventDefault();
      $("#dropzone")?.classList.toggle("over", !!e.target.closest?.("#dropzone"));
    });
    document.addEventListener("dragleave", (e) => { if (!e.relatedTarget) $("#dropzone")?.classList.remove("over"); });
    document.addEventListener("drop", async (e) => {
      e.preventDefault();
      $("#dropzone")?.classList.remove("over");
      if (!e.target.closest?.("#dropzone")) { if (S.route !== "import" && e.dataTransfer?.files?.length) toast("Open Add policies to upload PDFs"); return; }
      uploadFiles(await filesFromDrop(e.dataTransfer));
    });

    window.addEventListener("hashchange", navigate);
    let rt;
    window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(drawCharts, 120); });
    matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", paintThemeBtn);
    Charts.installTooltips();
  }

  function navigateKeep() {
    S.charts = [];
    $("#view").innerHTML = ROUTES[S.route].render();
    afterRender();
  }

  async function start() {
    bind();
    try { await load(); } catch (e) {
      $("#view").innerHTML = `<div class="card"><div class="empty-state">${icon("alertCircle", 28)}<b>Could not load policy data</b><span>${esc(e.message)}</span></div></div>`;
      return;
    }
    navigate();
    const crit = alerts().filter((a) => a.v.bucket === "critical").length;
    if (crit) toast(`${crit} polic${crit === 1 ? "y ends" : "ies end"} within 7 days`);
  }
  start();
})();
