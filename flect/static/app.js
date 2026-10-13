/* Flect console. Vanilla JS, no dependencies, read-only (state changes go through the `flect` CLI). */
"use strict";

// ── icons (Feather-style paths) ───────────────────────────────────────────
const ICONS = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  shieldCheck: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/>',
  alert: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  down: '<polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
  pr: '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" y1="9" x2="6" y2="21"/>',
  activity: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  ban: '<circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>',
  buoy: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/><line x1="4.93" y1="4.93" x2="9.17" y2="9.17"/><line x1="14.83" y1="14.83" x2="19.07" y2="19.07"/><line x1="14.83" y1="9.17" x2="19.07" y2="4.93"/><line x1="4.93" y1="19.07" x2="9.17" y2="14.83"/>',
  search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  key: '<path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>',
  branch: '<line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
  commit: '<circle cx="12" cy="12" r="4"/><line x1="1.05" y1="12" x2="7" y2="12"/><line x1="17.01" y1="12" x2="22.96" y2="12"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
  list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
  sliders: '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  checkCircle: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
  ext: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
  sun: '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>',
  moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
  pause: '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  server: '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>',
};
const ic = (name, cls = "") => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ""}</svg>`;

// ── formatting ────────────────────────────────────────────────────────────
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const toMs = (v) => (v == null ? null : typeof v === "number" ? (v < 1e12 ? v * 1000 : v) : Date.parse(v));
function ago(v) {
  const t = toMs(v); if (!t) return "—";
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 0) return "in " + dur(-s);
  if (s < 45) return "just now";
  return dur(s) + " ago";
}
function dur(s) {
  s = Math.max(0, Math.round(s));
  if (s < 60) return s + "s";
  const m = Math.floor(s / 60); if (m < 60) return m + "m";
  const h = Math.floor(m / 60); if (h < 48) return h + "h " + (m % 60) + "m";
  const d = Math.floor(h / 24); return d + "d " + (h % 24) + "h";
}
function when(v) {
  const t = toMs(v); if (!t) return "—";
  const d = new Date(t), opt = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" };
  if (d.getFullYear() !== new Date().getFullYear()) opt.year = "numeric";
  return d.toLocaleString(undefined, opt);
}
const timeTag = (v) => `<span title="${esc(v ? new Date(toMs(v)).toLocaleString() : "")}">${esc(ago(v))}</span>`;
const num = (v, d = 0) => (v == null || isNaN(v) ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
const short = (sha) => (sha ? String(sha).slice(0, 7) : "");
const cap = (s) => String(s || "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

// ── semantic chips ────────────────────────────────────────────────────────
const SEV_TONE = { critical: "t-crit", high: "t-high", medium: "t-warn", low: "t-info", info: "t-mute" };
const sevPill = (s) => `<span class="pill ${SEV_TONE[s] || "t-mute"}">${esc(cap(s))}</span>`;
const STATE_TONE = {
  open: "t-crit", mitigating: "t-warn", mitigated: "t-info", needs_human: "t-warn", resolved: "t-ok",
  passed: "t-ok", merged: "t-violet", approved: "t-ok", blocked: "t-crit", scanning: "t-info", testing: "t-info", error: "t-crit",
  healthy: "t-ok", lkg: "t-ok", failed: "t-crit", deploying: "t-info", verifying: "t-info", rolled_back: "t-warn",
  ok: "t-ok", failing: "t-crit", expired: "t-crit", "T-1d": "t-crit", "T-3d": "t-warn", "T-7d": "t-warn", "T-30d": "t-warn",
};
const statePill = (s, label) => `<span class="pill ${STATE_TONE[s] || "t-mute"}">${esc(label || cap(s))}</span>`;
function modePill(m) {
  if (m === "enforce") return `<span class="pill t-ok">${ic("shieldCheck")}Enforcing</span>`;
  if (m === "observe") return `<span class="pill t-warn">${ic("eye")}Observing</span>`;
  return `<span class="pill t-mute">Off</span>`;
}
const okDot = (good, label) => `<span class="dl"><i class="dot ${good ? "ok" : "crit"}"></i>${esc(label)}</span>`;

// ── data ──────────────────────────────────────────────────────────────────
const S = { meta: null, status: null, overview: null, history: null, lastOk: 0 };
async function api(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return (r.headers.get("content-type") || "").includes("json") ? r.json() : r.text();
}
const ghLink = (kind, n) => (S.meta ? `${S.meta.repo_url}/${kind}/${n}` : "#");
const issueLink = (n) => (n ? `<a href="${ghLink("issues", n)}" target="_blank" rel="noopener">#${n}</a>` : "");
const commitLink = (sha) => (sha ? `<a class="sha" href="${ghLink("commit", sha)}" target="_blank" rel="noopener">${esc(short(sha))}</a>` : "—");

// ── theme ─────────────────────────────────────────────────────────────────
function currentTheme() {
  const set = document.documentElement.dataset.theme;
  if (set) return set;
  return matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}
function renderThemeBtn() {
  const t = currentTheme();
  document.getElementById("theme-btn").innerHTML = t === "dark" ? `${ic("sun")} Light` : `${ic("moon")} Dark`;
}
document.getElementById("theme-btn").addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("flect-theme", next); } catch (e) {}
  renderThemeBtn(); render();
});

// ── drawer ────────────────────────────────────────────────────────────────
const drawer = document.getElementById("drawer"), scrim = document.getElementById("scrim");
function openDrawer(title, html) {
  document.getElementById("drawer-title").innerHTML = title;
  document.getElementById("drawer-body").innerHTML = html;
  drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); scrim.style.display = "block";
}
function closeDrawer() {
  const wasOpen = drawer.classList.contains("open");
  drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true"); scrim.style.display = "none";
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  if (wasOpen && parts[1]) history.replaceState(null, "", `#/${parts[0]}`);
}
scrim.addEventListener("click", closeDrawer);
document.getElementById("drawer-close").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

// ── charts (SVG, responsive, hover crosshair) ─────────────────────────────
const CSSV = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
function lineChart(el, { series, height = 180, yFmt = (v) => num(v, 1), yMin = 0, tip }) {
  const pts = series.flatMap((s) => s.data);
  if (!pts.length) { el.innerHTML = `<div class="empty small">Collecting data — the chart fills in as Flect samples (every 5 s).</div>`; return; }
  const W = Math.max(220, el.clientWidth || 600), H = height, P = { l: 44, r: 12, t: 10, b: 22 };
  const xs = pts.map((p) => p[0]), x0 = Math.min(...xs), x1 = Math.max(...xs) || x0 + 1;
  const ys = pts.map((p) => p[1]).filter((v) => v != null);
  let y1 = Math.max(...ys, yMin + 1e-9); y1 = y1 <= 0 ? 1 : y1 * 1.15;
  const X = (t) => P.l + ((t - x0) / Math.max(1, x1 - x0)) * (W - P.l - P.r);
  const Y = (v) => H - P.b - ((v - yMin) / Math.max(1e-9, y1 - yMin)) * (H - P.t - P.b);
  let svg = "";
  for (let i = 0; i <= 3; i++) {                                   // gridlines + y labels
    const v = yMin + ((y1 - yMin) * i) / 3, y = Y(v);
    svg += `<line class="grid-l" x1="${P.l}" x2="${W - P.r}" y1="${y}" y2="${y}"/><text class="axis" x="${P.l - 8}" y="${y + 3}" text-anchor="end">${esc(yFmt(v))}</text>`;
  }
  const span = x1 - x0, fmtOpt = span < 600 ? { hour: "2-digit", minute: "2-digit", second: "2-digit" } : { hour: "2-digit", minute: "2-digit" };
  let prevLbl = "";                                                 // x labels (deduplicated)
  const nLbl = Math.max(1, Math.min(4, Math.floor((W - P.l) / (span < 600 ? 110 : 80))));
  for (let i = 0; i <= nLbl; i++) {
    const t = x0 + (span * i) / nLbl;
    const lbl = new Date(t * 1000).toLocaleTimeString(undefined, fmtOpt);
    if (lbl === prevLbl) continue; prevLbl = lbl;
    svg += `<text class="axis" x="${X(t)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === nLbl ? "end" : "middle"}">${esc(lbl)}</text>`;
  }
  for (const s of series) {
    const d = s.data.filter((p) => p[1] != null);
    if (!d.length) continue;
    const color = CSSV(s.color || "--accent");
    const path = d.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    if (s.area) {
      const id = "g" + Math.random().toString(36).slice(2, 8);
      svg += `<defs><linearGradient id="${id}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".28"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>`;
      svg += `<path d="${path}L${X(d[d.length - 1][0])},${H - P.b}L${X(d[0][0])},${H - P.b}Z" fill="url(#${id})"/>`;
    }
    svg += `<path d="${path}" fill="none" stroke="${color}" stroke-width="${s.width || 2}" ${s.dash ? 'stroke-dasharray="5 4"' : ""} stroke-linejoin="round" stroke-linecap="round"/>`;
  }
  svg += `<line class="cross" x1="0" x2="0" y1="${P.t}" y2="${H - P.b}" style="display:none"/>`;
  el.innerHTML = `<div class="chart" style="height:${H}px"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${svg}</svg><div class="tip"></div></div>`;
  const box = el.querySelector(".chart"), cross = el.querySelector(".cross"), tipEl = el.querySelector(".tip");
  const base = series[0].data;
  box.addEventListener("mousemove", (e) => {
    const r = box.getBoundingClientRect(), mx = ((e.clientX - r.left) / r.width) * W;
    let best = base[0];
    for (const p of base) if (Math.abs(X(p[0]) - mx) < Math.abs(X(best[0]) - mx)) best = p;
    const px = X(best[0]);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.style.display = "";
    tipEl.style.display = "block"; tipEl.style.left = (px / W) * 100 + "%"; tipEl.style.top = "0px";
    tipEl.innerHTML = tip ? tip(best) : esc(yFmt(best[1]));
  });
  box.addEventListener("mouseleave", () => { cross.style.display = "none"; tipEl.style.display = "none"; });
}
function availabilityStrip(hist, buckets = 60) {
  if (!hist.length) return `<div class="strip">${'<span class="none"></span>'.repeat(buckets)}</div>`;
  const n = Math.min(buckets, hist.length), size = hist.length / n, cells = [];
  for (let i = 0; i < n; i++) {
    const chunk = hist.slice(Math.floor(i * size), Math.max(Math.floor((i + 1) * size), Math.floor(i * size) + 1));
    const bad = chunk.filter((h) => !h[1]).length;
    const title = `${new Date(chunk[0][0] * 1000).toLocaleTimeString()} — ${chunk.length - bad}/${chunk.length} healthy`;
    cells.push(`<span class="${bad ? "bad" : ""}" title="${esc(title)}"></span>`);
  }
  return `<div class="strip">${cells.join("")}</div>`;
}

// ── markdown (reports are produced by Flect; still escaped first) ─────────
function md(src) {
  const lines = esc(src).split("\n"), out = [];
  const fmt = (t) => t.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[\s(])_([^_]+)_(?=[\s).,;:!?]|$)/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  // Code spans are left untouched; emphasis only applies outside them (e.g. snake_case file names).
  const inline = (t) => t.split(/(`[^`]+`)/g).map((part) => (/^`[^`]+`$/.test(part) ? `<code>${part.slice(1, -1)}</code>` : fmt(part))).join("");
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (l.startsWith("```")) { const buf = []; i++; while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]); out.push(`<pre><code>${buf.join("\n")}</code></pre>`); continue; }
    const h = l.match(/^(#{1,4})\s+(.*)$/); if (h) { const n = Math.min(4, h[1].length + 1); out.push(`<h${n}>${inline(h[2])}</h${n}>`); continue; }
    if (l.trim().startsWith("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1])) {
      const row = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
      const head = row(l); i += 2; const body = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) body.push(row(lines[i++]));
      i--; out.push(`<div class="md-table"><table><tr>${head.map((c) => `<th>${c}</th>`).join("")}</tr>${body.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</table></div>`); continue;
    }
    if (/^\s*[-*]\s+/.test(l)) { const items = []; while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) items.push(`<li>${inline(lines[i++].replace(/^\s*[-*]\s+/, ""))}</li>`); i--; out.push(`<ul>${items.join("")}</ul>`); continue; }
    if (!l.trim()) continue;
    out.push(`<p>${inline(l)}</p>`);
  }
  return `<div class="md">${out.join("")}</div>`;
}

// ── navigation / router ───────────────────────────────────────────────────
const VIEWS = [
  { id: "overview", label: "Overview", icon: "grid" },
  { id: "incidents", label: "Incidents", icon: "alert" },
  { id: "prs", label: "Pull requests", icon: "pr" },
  { id: "traffic", label: "Traffic & blocks", icon: "activity" },
  { id: "deploys", label: "Deployments", icon: "commit" },
  { id: "keys", label: "Keys & services", icon: "key" },
  { id: "reports", label: "Reports", icon: "file" },
  { id: "audit", label: "Audit log", icon: "list" },
  { id: "settings", label: "Settings", icon: "sliders" },
];
const UI = { incTab: "open", auditFilter: "all", repKind: "all" };
const route = () => (location.hash.replace(/^#\/?/, "") || "overview").split("/")[0];
function renderNav() {
  const o = S.overview || {}, cur = route();
  const counts = { incidents: [o.open_incident_total, ""], traffic: [o.active_blocks, ""], keys: [(o.keys || {}).failing + ((o.keys || {}).expired || 0), "warn"] };
  document.getElementById("nav").innerHTML = VIEWS.map((v) => {
    const [n, tone] = counts[v.id] || [];
    return `<a href="#/${v.id}" class="${v.id === cur ? "active" : ""}">${ic(v.icon)}<span class="lbl">${v.label}</span>${n ? `<span class="count ${tone}">${n}</span>` : ""}</a>`;
  }).join("");
}
const routeArg = () => (location.hash.replace(/^#\/?/, "").split("/")[1] || "");
let lastView = route();
window.addEventListener("hashchange", async () => {
  const v = route(), arg = routeArg();
  if (v !== lastView) { window.scrollTo(0, 0); lastView = v; }
  if (!arg) closeDrawer();
  await render(); openDeepLink();
});
function openDeepLink() {
  const v = route(), arg = routeArg();
  if (!arg) return;
  if (v === "incidents") showIncident(arg); else if (v === "reports") showReport(arg);
}

// ── overview ──────────────────────────────────────────────────────────────
const CAPS = [
  { id: "prguard", name: "PR Guard", icon: "pr", deps: ["sandbox", "llm"] },
  { id: "dos", name: "Traffic Shield", icon: "shield", deps: ["nft"] },
  { id: "crash", name: "Crash Recovery", icon: "buoy", deps: ["sandbox", "llm"] },
  { id: "vapt", name: "Release VAPT", icon: "search", deps: ["uat", "llm"] },
  { id: "cicd", name: "CI / CD", icon: "branch", deps: ["github_poll"] },
  { id: "keys", name: "Keys & services", icon: "key", deps: ["github"] },
];
const DEP_LABEL = { sandbox: "Sandbox", llm: "DeepSeek", nft: "Firewall", uat: "UAT", github_poll: "GitHub", github: "GitHub token" };
function depOk(dep) {
  const c = (S.status || {}).capabilities || {};
  if (dep === "github") return !(S.status || {}).writes_paused;
  const v = c[dep]; return v === "ok" || v === "configured";
}
function capMetric(id) {
  const o = S.overview || {}, st = S.status || {}, d = st.dos || {}, prs = o.prs || {};
  const total = Object.values(prs).reduce((a, b) => a + b, 0);
  switch (id) {
    case "prguard": return `<b>${total}</b> reviewed · <b>${prs.blocked || 0}</b> blocked · <b>${prs.needs_human || 0}</b> need a human`;
    case "dos": return `<b>${o.active_blocks || 0}</b> active blocks · <b>${num(d.global_rps, 1)}</b> req/s${d.flooding ? " · <b style='color:var(--crit)'>flood mode</b>" : ""}`;
    case "crash": return `Rollback target ${st.lkg ? commitLink(st.lkg.sha) : "<b>pending</b>"} · <b>${o.rollbacks_24h || 0}</b> rollbacks · 24h`;
    case "vapt": return `UAT <b>on demand</b> · <b>${(o.reports_by_kind || {}).vapt || 0}</b> VAPT reports`;
    case "cicd": { const l = o.last_deploy; return l ? `Last deploy ${esc(l.env)} ${commitLink(l.sha)} · ${timeTag(l.started_ts)}` : "No deployments yet"; }
    case "keys": { const k = o.keys || {}, bad = (k.failing || 0) + (k.expired || 0); return `<b>${k.ok || 0}</b> ok${bad ? ` · <b style="color:var(--crit)">${bad}</b> failing` : ""}${o.next_expiry ? ` · next expiry <b>${dur(o.next_expiry.days_left * 86400)}</b>` : ""}`; }
  }
  return "";
}
function posture() {
  const st = S.status || {}, o = S.overview || {}, h = st.health || {};
  const open = o.open_incident_total || 0, sev = o.open_incidents || {};
  const since = o.had_failure_1h && o.healthy_since ? `healthy for ${dur(Date.now() / 1000 - o.healthy_since)} (since its last failed check)`
    : h.uptime_s != null ? `up ${dur(h.uptime_s)}` : "healthy";
  const facts = [`${esc((S.meta || {}).target || "VIGIL").toUpperCase()} ${h.http_ok ? since : "not responding"}`];
  if (o.availability_1h != null) facts.push(`${num(o.availability_1h, o.availability_1h === 100 ? 0 : 2)}% available (1h)`);
  if (o.latency_ms_avg != null) facts.push(`${num(o.latency_ms_avg, 0)} ms avg response`);
  if (!h.http_ok) return { tone: "crit", icon: "down", title: "Production is not responding", sub: esc(h.error || "health check failing") + " · Flect is handling it" };
  if ((sev.critical || 0) + (sev.high || 0) > 0 || open > 0)
    return { tone: "warn", icon: "alert", title: `Production is up · ${open} open issue${open === 1 ? "" : "s"} need${open === 1 ? "s" : ""} attention`, sub: facts.join(" · ") };
  return { tone: "ok", icon: "shieldCheck", title: "Production is protected", sub: facts.join(" · ") };
}
function decisionText(a) {
  const d = a.decision || "", map = {
    block_ip: "Blocked IP", unblock_ip: "Unblocked IP", merge_to_uat: "Merged into UAT", merge_hotfix: "Merged hotfix",
    comment_pr: "Commented on PR", close_pr: "Closed PR", label_pr: "Labelled PR", restart_prod: "Restarted production",
    open_hotfix_pr: "Opened hotfix PR", push_hotfix_branch: "Pushed hotfix branch", set_mode: "Changed mode",
    hotfix_attempt: "Started fix-forward", flood_mode_on: "Flood mode on", flood_mode_off: "Flood mode off",
    resolve_false_positives: "Closed false positives", comment_vapt: "Posted VAPT report", open_backmerge_pr: "Opened back-merge PR",
  };
  if (d.startsWith("deploy_prod:")) return "Deploy to prod (" + d.split(":")[1].replace("_", " ") + ")";
  if (d.startsWith("status:")) return "Set check " + d.slice(7);
  return map[d] || cap(d);
}
function actionRow(a) {
  const tone = a.mode === "observe" ? "observe" : a.ok === 0 ? "fail" : "";
  const tag = a.mode === "observe" ? `<span class="pill t-warn">would do</span>` : a.ok === 0 ? `<span class="pill t-crit">failed</span>` : "";
  return `<li class="${tone}"><div class="row"><b class="trunc">${esc(decisionText(a))}</b>${tag}<span class="spacer"></span><span class="faint small">${timeTag(a.ts)}</span></div>
    <div class="muted small trunc"><code>${esc(a.target)}</code>${a.result && a.result !== "ok" ? " · " + esc(String(a.result).slice(0, 120)) : ""}</div></li>`;
}
const INC_KIND = { expiry: "Keys & services", crash: "Production crash", dos: "Abusive traffic", anomaly: "Log anomaly",
  poison_pr: "PR guard", vapt: "VAPT", deploy_fail: "Deployment" };
const incKind = (k) => INC_KIND[k] || cap(k);
function incidentItem(i) {
  return `<div class="item click" data-inc="${i.id}"><span class="sev ${esc(i.severity)}"></span>
    <div class="grow"><div class="title trunc">${esc(i.title)}</div>
    <div class="meta"><span>${esc(incKind(i.kind))}</span><span>opened ${timeTag(i.opened_ts)}</span>${i.github_issue ? `<span>GitHub ${issueLink(i.github_issue)}</span>` : ""}</div></div>
    ${statePill(i.state)}</div>`;
}
async function viewOverview() {
  const [inc, acts] = await Promise.all([api("/api/incidents?limit=100"), api("/api/actions?limit=12")]);
  const open = inc.filter((i) => i.state !== "resolved"), resolved = inc.filter((i) => i.state === "resolved").slice(0, 5);
  const st = S.status || {}, c = st.capabilities || {}, o = S.overview || {}, p = posture(), q = c.llm_queue || {}, l = o.llm_24h || {};
  const paused = st.writes_paused ? `<div class="banner">${ic("pause")} GitHub actions paused: ${esc(st.writes_paused)}. Detection and IP blocking continue.</div>` : "";
  return `<div class="stack">${paused}
    <section class="hero ${p.tone}"><div class="hero-icon">${ic(p.icon)}</div>
      <div><h2>${esc(p.title)}</h2><p>${p.sub}</p></div>
      <div class="stats">
        <div class="stat"><div class="v">${o.open_incident_total || 0}</div><div class="l">open incidents</div></div>
        <div class="stat"><div class="v">${o.active_blocks || 0}</div><div class="l">IPs blocked</div></div>
        <div class="stat"><div class="v">${o.deploys_24h || 0}</div><div class="l">deploys · 24h</div></div>
        <div class="stat"><div class="v">${o.actions_24h || 0}</div><div class="l">actions · 24h</div></div>
      </div></section>
    <div class="grid g-3">${CAPS.map((k) => `<section class="card cap">
      <div class="cap-h"><div class="cap-ic">${ic(k.icon)}</div><div class="cap-title">${k.name}</div><span class="spacer" style="flex:1"></span>${modePill((st.modes || {})[k.id])}</div>
      <div class="cap-metric">${capMetric(k.id)}</div>
      <div class="cap-deps">${k.deps.map((d) => okDot(depOk(d), DEP_LABEL[d])).join("")}</div></section>`).join("")}</div>
    <div class="grid g-2">
      <section class="card"><div class="card-h"><h2>Production response time · last hour</h2><span class="spacer"></span>
        <div class="legend"><span><i style="background:var(--accent)"></i>latency</span></div></div>
        <div class="card-b"><div id="ch-latency"></div><div style="margin-top:10px">${availabilityStrip((S.history || {}).health || [])}</div>
        <div class="row small faint" style="margin-top:6px"><span>availability</span><span class="spacer" style="flex:1"></span><span>${o.availability_1h != null ? num(o.availability_1h, 2) + "%" : "—"}</span></div></div></section>
      <section class="card"><div class="card-h"><h2>Traffic · last hour</h2><span class="spacer"></span>
        <div class="legend"><span><i style="background:var(--violet)"></i>req/s</span><span><i style="background:var(--faint)"></i>baseline</span></div></div>
        <div class="card-b"><div id="ch-traffic"></div></div></section>
    </div>
    <div class="grid g-21">
      <section class="card"><div class="card-h"><h2>Open incidents</h2><span class="spacer"></span><a class="small" href="#/incidents">All incidents →</a></div>
        <div class="card-b flush"><div class="list">${open.length ? open.map(incidentItem).join("") : `<div class="empty">${ic("checkCircle")}No open incidents</div>`}</div>
        ${resolved.length ? `<div class="card-h" style="padding-top:6px"><h2>Recently resolved</h2></div><div class="list resolved" style="margin-top:6px">${resolved.map(incidentItem).join("")}</div>` : ""}</div></section>
      <div class="stack">
        <section class="card"><div class="card-h"><div class="cap-ic" style="width:26px;height:26px">${ic("cpu")}</div><h2>DeepSeek (local model)</h2><span class="spacer"></span>${statePill(c.llm === "ok" ? "ok" : "failing", c.llm === "ok" ? "Online" : "Offline")}</div>
          <div class="card-b"><dl class="kv"><dt>Queue</dt><dd>${q.queued || 0} waiting · ${q.in_flight || 0} running</dd>
          <dt>Calls · 24h</dt><dd class="num">${l.calls || 0}${l.calls ? ` (${l.ok || 0} ok)` : ""}</dd>
          <dt>Avg call</dt><dd class="num">${l.avg_s ? num(l.avg_s, 1) + " s" : "—"}</dd>
          <dt>Tokens out · 24h</dt><dd class="num">${num(l.out_tokens || 0)}</dd></dl></div></section>
        <section class="card"><div class="card-h"><h2>Recent activity</h2><span class="spacer"></span><a class="small" href="#/audit">Audit log →</a></div>
          <div class="card-b">${acts.length ? `<ul class="timeline">${acts.slice(0, 7).map(actionRow).join("")}</ul>` : `<div class="empty small">No actions yet</div>`}</div></section>
      </div>
    </div></div>`;
}
function afterOverview() {
  const h = (S.history || {}).health || [], t = (S.history || {}).traffic || [];
  lineChart(document.getElementById("ch-latency"), {
    series: [{ data: h.map((p) => [p[0], p[2]]), color: "--accent", area: true }], yFmt: (v) => num(v, 0) + " ms",
    tip: (p) => `${new Date(p[0] * 1000).toLocaleTimeString()} · <b>${p[1] == null ? "down" : num(p[1], 0) + " ms"}</b>`,
  });
  lineChart(document.getElementById("ch-traffic"), {
    series: [{ data: t.map((p) => [p[0], p[1]]), color: "--violet", area: true }, { data: t.map((p) => [p[0], p[2]]), color: "--faint", dash: true, width: 1.5 }],
    yFmt: (v) => num(v, 1), tip: (p) => { const r = t.find((x) => x[0] === p[0]) || []; return `${new Date(p[0] * 1000).toLocaleTimeString()} · <b>${num(r[1], 2)}</b> req/s · baseline ${num(r[2], 2)}`; },
  });
}

// ── incidents ─────────────────────────────────────────────────────────────
async function viewIncidents() {
  const rows = await api("/api/incidents?limit=300");
  const filt = { open: (i) => i.state !== "resolved", resolved: (i) => i.state === "resolved", all: () => true }[UI.incTab];
  const shown = rows.filter(filt), nOpen = rows.filter((i) => i.state !== "resolved").length;
  const tabs = [["open", `Open (${nOpen})`], ["resolved", `Resolved (${rows.length - nOpen})`], ["all", "All"]];
  return `<section class="card"><div class="card-h"><div class="tabs">${tabs.map(([k, l]) => `<button data-tab="${k}" class="${UI.incTab === k ? "on" : ""}">${l}</button>`).join("")}</div>
    <span class="spacer"></span><span class="faint small hide-sm">Click an incident for details, evidence and actions</span></div>
    <div class="card-b flush" style="margin-top:8px"><div class="list">${shown.length ? shown.map((i) => `
      <div class="item click" data-inc="${i.id}"><span class="sev ${esc(i.severity)}"></span>
        <div class="grow"><div class="row"><span class="title trunc">${esc(i.title)}</span></div>
          <div class="meta"><span>#${i.id}</span><span>${esc(incKind(i.kind))}</span><span>opened ${timeTag(i.opened_ts)}</span>
          ${i.closed_ts ? `<span>resolved ${timeTag(i.closed_ts)}</span>` : ""}${i.github_issue ? `<span>GitHub ${issueLink(i.github_issue)}</span>` : ""}</div>
          ${i.summary ? `<div class="muted small" style="margin-top:4px">${esc(i.summary)}</div>` : ""}</div>
        <div class="row" style="flex:none">${sevPill(i.severity)}${statePill(i.state)}</div></div>`).join("")
      : `<div class="empty">${ic("checkCircle")}${UI.incTab === "open" ? "Nothing needs attention" : "No incidents"}</div>`}</div></div></section>`;
}
async function showIncident(id) {
  openDrawer(`Incident #${id}`, `<div class="empty small">Loading…</div>`);
  const i = await api(`/api/incidents/${id}`), d = i.details || {};
  let llm = null; try { llm = i.llm_summary ? JSON.parse(i.llm_summary) : null; } catch (e) {}
  const facts = [];
  const add = (k, v) => { if (v != null && v !== "") facts.push(`<dt>${esc(k)}</dt><dd>${v}</dd>`); };
  add("Kind", esc(incKind(i.kind))); add("Opened", esc(new Date(toMs(i.opened_ts)).toLocaleString()));
  if (i.closed_ts) add("Resolved", esc(new Date(toMs(i.closed_ts)).toLocaleString()));
  add("GitHub issue", issueLink(i.github_issue));
  add("Reason", esc(d.reason)); add("Classification", esc(d.classification)); add("Commit", d.crashed_sha ? commitLink(d.crashed_sha) : null);
  add("Exception", d.exception ? `<code>${esc(d.exception)}</code>` : null); add("IP", d.ip ? `<code>${esc(d.ip)}</code>` : null);
  add("Rule", d.rule ? `<code>${esc(d.rule)}</code>` : null); add("Location", d.location ? `<code>${esc(d.location)}</code>` : null);
  add("Expires", d.expires ? esc(new Date(toMs(d.expires)).toLocaleString()) : null); add("Details", esc(d.details));
  const rest = Object.fromEntries(Object.entries(d).filter(([k]) => !["traceback", "reason", "classification", "crashed_sha", "exception", "ip", "rule", "location", "expires", "details"].includes(k)));
  const html = `<div class="row wrap" style="margin-bottom:12px">${sevPill(i.severity)}${statePill(i.state)}</div>
    <h3 style="margin:0 0 6px;font-size:17px">${esc(i.title)}</h3>
    ${i.summary ? `<p class="muted" style="margin:0 0 16px">${esc(i.summary)}</p>` : ""}
    ${llm ? `<section class="card" style="margin-bottom:16px"><div class="card-h"><h2>${ic("cpu")} DeepSeek's read</h2></div><div class="card-b">
      <p style="margin:0 0 8px">${esc(llm.summary || "")}</p>${llm.likely_cause ? `<p class="muted small" style="margin:0 0 8px"><b>Likely cause:</b> ${esc(llm.likely_cause)}</p>` : ""}
      ${(llm.recommended_followups || []).length ? `<ul class="small">${llm.recommended_followups.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>` : ""}</div></section>` : ""}
    <dl class="kv" style="margin-bottom:18px">${facts.join("")}</dl>
    ${d.traceback ? `<h4 class="muted" style="margin:0 0 8px">Traceback</h4><pre class="code">${esc(d.traceback)}</pre>` : ""}
    ${Object.keys(rest).length ? `<h4 class="muted" style="margin:18px 0 8px">Evidence</h4><pre class="code">${esc(JSON.stringify(rest, null, 2))}</pre>` : ""}
    <h4 class="muted" style="margin:18px 0 10px">What Flect did</h4>
    ${(i.actions || []).length ? `<ul class="timeline">${i.actions.map(actionRow).join("")}</ul>` : `<div class="faint small">No actions were needed.</div>`}`;
  openDrawer(`Incident #${id}`, html);
}

// ── pull requests ─────────────────────────────────────────────────────────
async function viewPRs() {
  const [prs, reports] = await Promise.all([api("/api/prs"), api("/api/reports")]);
  const rep = {}; for (const r of reports) if (r.pr_number && !rep[r.pr_number + r.kind]) rep[r.pr_number + r.kind] = r;
  const m = S.meta || {};
  const intro = `<section class="card"><div class="card-b row wrap small muted" style="gap:14px">${ic("pr")}
    <span>Feature PRs into <code>${esc(m.feature_base)}</code> merge automatically when every check is green. Releases into <code>${esc(m.prod_branch)}</code> get a VAPT report and are merged by a human.
    A <b>needs-human</b> verdict can be overridden by commenting <code>/flect approve</code> on the PR.</span></div></section>`;
  if (!prs.length) return `<div class="stack">${intro}<section class="card"><div class="empty">${ic("pr", "")}No pull requests reviewed yet. Flect checks GitHub every 30 seconds.</div></section></div>`;
  return `<div class="stack">${intro}<section class="card"><div class="table-wrap"><table class="t">
    <tr><th>PR</th><th>Title</th><th class="hide-sm">Kind</th><th>Verdict</th><th>Risk</th><th class="hide-sm">Tests</th><th class="hide-sm">Reports</th><th>Updated</th></tr>
    ${prs.map((p) => { let s = {}; try { s = JSON.parse(p.statuses || "{}"); } catch (e) {}
      const g = rep[p.number + "prguard"], v = rep[p.number + "vapt"];
      return `<tr><td><a href="${ghLink("pull", p.number)}" target="_blank" rel="noopener">#${p.number}</a></td>
        <td><div class="trunc" style="max-width:360px" title="${esc(p.title)}">${esc(p.title || "")}</div><div class="faint small">${commitLink(p.head_sha)} → <code>${esc(p.base)}</code></div></td>
        <td class="hide-sm">${esc(cap(p.kind))}</td><td>${statePill(p.state)}</td><td>${p.risk ? sevPill(p.risk) : "—"}</td>
        <td class="hide-sm">${s.tests ? statePill(s.tests === "passed" ? "passed" : s.tests === "failed" ? "failed" : "mute", cap(s.tests)) : "—"}</td>
        <td class="hide-sm">${g ? `<a href="#" data-report="${g.id}">guard</a>` : ""}${v ? ` · <a href="#" data-report="${v.id}">VAPT</a>` : ""}</td>
        <td class="faint small">${timeTag(p.updated_ts)}</td></tr>`; }).join("")}
  </table></div></section></div>`;
}

// ── traffic & blocks ──────────────────────────────────────────────────────
async function viewTraffic() {
  const blocks = await api("/api/blocks");
  const d = (S.status || {}).dos || {}, m = S.meta || {}, now = Date.now();
  const active = blocks.filter((b) => b.active && toMs(b.expires_ts) > now);
  return `<div class="stack">
    <div class="grid g-3">
      <section class="card cap"><div class="cap-metric">Requests / second</div><div class="stat"><div class="v">${num(d.global_rps, 2)}</div><div class="l">baseline ${num(d.baseline_rps, 2)}</div></div></section>
      <section class="card cap"><div class="cap-metric">Flood mode</div><div class="row">${d.flooding ? statePill("failing", "Active — rate limiting on") : statePill("ok", "Off")}</div><div class="l faint small">Per-IP limits drop 4× during a distributed flood</div></section>
      <section class="card cap"><div class="cap-metric">IPs blocked now</div><div class="stat"><div class="v">${active.length}</div><div class="l">${blocks.length} blocks in history</div></div></section>
    </div>
    <section class="card"><div class="card-h"><h2>Requests per second · last hour</h2><span class="spacer"></span>
      <div class="legend"><span><i style="background:var(--violet)"></i>req/s</span><span><i style="background:var(--faint)"></i>baseline</span></div></div>
      <div class="card-b"><div id="ch-traffic-big"></div></div></section>
    <div class="grid g-2">
      <section class="card"><div class="card-h"><h2>Top talkers · last 60 s</h2></div><div class="card-b flush">
        ${(d.top_talkers_60s || []).length ? `<table class="t"><tr><th>IP</th><th>Requests</th></tr>${d.top_talkers_60s.map(([ip, n]) => `<tr><td><code>${esc(ip)}</code></td><td class="num">${n}</td></tr>`).join("")}</table>`
          : `<div class="empty small">No external traffic in the last minute (allowlisted sources are not shown).</div>`}</div></section>
      <section class="card"><div class="card-h"><h2>Never blocked (allowlist)</h2></div><div class="card-b"><div class="row wrap">${(m.allowlist || []).map((c) => `<span class="pill t-mute"><code>${esc(c)}</code></span>`).join("")}</div>
        <p class="faint small" style="margin:12px 0 0">Enforced twice: by Flect and again by the root-owned firewall helper.</p></div></section>
    </div>
    <section class="card"><div class="card-h"><h2>Blocks</h2><span class="spacer"></span><span class="faint small hide-sm">Unblock: <code>flect unblock &lt;ip&gt;</code></span></div>
      <div class="card-b flush">${blocks.length ? `<div class="table-wrap"><table class="t"><tr><th>IP</th><th>Rule</th><th class="hide-sm">Reason</th><th>TTL</th><th>Status</th><th>When</th></tr>
      ${blocks.map((b) => { const live = b.active && toMs(b.expires_ts) > now;
        return `<tr><td><code>${esc(b.ip)}</code></td><td><code>${esc(b.rule_id)}</code></td><td class="hide-sm muted">${esc(b.reason)}</td><td>${esc(b.ttl)}</td>
          <td>${live ? statePill("open", "Blocked · " + dur((toMs(b.expires_ts) - now) / 1000) + " left") : b.mode === "observe" ? statePill("needs_human", "Would block") : statePill("resolved", b.unblocked_by ? "Unblocked" : "Expired")}</td>
          <td class="faint small">${timeTag(b.created_ts)}</td></tr>`; }).join("")}</table></div>` : `<div class="empty">${ic("checkCircle")}No IP has ever been blocked</div>`}</div></section>
  </div>`;
}
function afterTraffic() {
  const t = (S.history || {}).traffic || [];
  lineChart(document.getElementById("ch-traffic-big"), {
    height: 240, series: [{ data: t.map((p) => [p[0], p[1]]), color: "--violet", area: true }, { data: t.map((p) => [p[0], p[2]]), color: "--faint", dash: true, width: 1.5 }],
    tip: (p) => { const r = t.find((x) => x[0] === p[0]) || []; return `${new Date(p[0] * 1000).toLocaleTimeString()} · <b>${num(r[1], 2)}</b> req/s · baseline ${num(r[2], 2)}${r[3] ? " · flood" : ""}`; },
  });
}

// ── deployments ───────────────────────────────────────────────────────────
const TRIGGER = { bootstrap: "First seen", manual: "Changed outside Flect", human_merge: "Release (human merge)", hotfix: "Crash hotfix", rollback: "Automatic rollback", restart: "Restart", uat_merge: "Merged into UAT" };
async function viewDeploys() {
  const rows = await api("/api/deployments"), lkg = rows.find((r) => r.env === "prod" && r.state === "lkg");
  return `<div class="stack"><div class="grid g-3">
      <section class="card cap"><div class="cap-metric">Production is running</div><div class="row">${rows.find((r) => r.env === "prod") ? commitLink(rows.find((r) => r.env === "prod").sha) : "—"}</div></section>
      <section class="card cap"><div class="cap-metric">Last-known-good (rollback target)</div><div class="row">${lkg ? commitLink(lkg.sha) + `<span class="faint small">since ${when(lkg.started_ts)}</span>` : "<span class='muted'>pending: needs 10 healthy minutes</span>"}</div></section>
      <section class="card cap"><div class="cap-metric">Deploys · 24h</div><div class="stat"><div class="v">${(S.overview || {}).deploys_24h || 0}</div></div></section></div>
    <section class="card"><div class="card-h"><h2>History</h2></div><div class="card-b flush">${rows.length ? `<div class="table-wrap"><table class="t">
      <tr><th>Env</th><th>Commit</th><th>Trigger</th><th>Result</th><th class="hide-sm">Notes</th><th>When</th></tr>
      ${rows.map((r) => `<tr><td><span class="pill ${r.env === "prod" ? "t-violet" : "t-info"}">${r.env.toUpperCase()}</span></td><td>${commitLink(r.sha)}${r.previous_sha ? `<span class="faint small"> from ${esc(short(r.previous_sha))}</span>` : ""}</td>
        <td>${esc(TRIGGER[r.trigger] || cap(r.trigger))}</td><td>${statePill(r.state, r.state === "lkg" ? "Last-known-good" : cap(r.state))}</td>
        <td class="hide-sm muted small"><div class="trunc" style="max-width:320px" title="${esc(r.notes || "")}">${esc(r.notes || "")}</div></td><td class="faint small">${timeTag(r.started_ts)}</td></tr>`).join("")}
    </table></div>` : `<div class="empty">No deployments recorded yet.</div>`}</div></section></div>`;
}

// ── keys & services ───────────────────────────────────────────────────────
const KIND = { github_pat: "GitHub token", tls_cert: "TLS certificate", jwt: "JWT", service: "Service", api_key: "API key" };
async function viewKeys() {
  const rows = await api("/api/keys");
  const exp = rows.filter((r) => r.days_left != null), svc = rows.filter((r) => r.days_left == null);
  const bar = (d) => { const pct = Math.max(2, Math.min(100, (d / 365) * 100)); return `<div class="bar" title="${num(d, 1)} days left"><span class="${d <= 3 ? "crit" : d <= 30 ? "warn" : ""}" style="width:${pct}%"></span></div>`; };
  return `<div class="stack">
    <section class="card"><div class="card-h"><h2>Expiring credentials & certificates</h2><span class="spacer"></span><span class="faint small">Alerts at 7, 3 and 1 days (30 for certificates)</span></div>
      <div class="card-b flush">${exp.length ? `<div class="table-wrap"><table class="t"><tr><th>Name</th><th class="hide-sm">Kind</th><th>Expires</th><th style="width:28%">Time left</th><th>Status</th></tr>
      ${exp.map((r) => `<tr><td><b>${esc(r.name)}</b><div class="faint small trunc" style="max-width:280px">${esc(r.location)}</div></td><td class="hide-sm">${esc(KIND[r.kind] || r.kind)}</td>
        <td>${esc(when(r.expires_ts))}</td><td><div class="row">${bar(r.days_left)}<span class="small muted num" style="white-space:nowrap">${dur(r.days_left * 86400)}</span></div></td><td>${statePill(r.alert_level, r.alert_level === "ok" ? "OK" : r.alert_level)}</td></tr>`).join("")}</table></div>`
      : `<div class="empty small">Nothing with an expiry date yet.</div>`}</div></section>
    <section class="card"><div class="card-h"><h2>Tokens & dependent services</h2><span class="spacer"></span><span class="faint small">Checked hourly · failures re-checked after 2 minutes</span></div>
      <div class="card-b flush"><div class="list">${svc.map((r) => `<div class="item"><i class="dot ${r.alert_level === "ok" ? "ok" : "crit"}"></i>
        <div class="grow"><div class="title">${esc(r.name)} <span class="faint small">· ${esc(KIND[r.kind] || r.kind)}</span></div><div class="meta"><span class="trunc">${esc(r.details || r.location)}</span><span>checked ${timeTag(r.last_probe_ts)}</span></div></div>
        ${statePill(r.alert_level, r.alert_level === "ok" ? "Healthy" : cap(r.alert_level))}</div>`).join("") || `<div class="empty small">No checks yet.</div>`}</div></div></section></div>`;
}

// ── reports ───────────────────────────────────────────────────────────────
const REPORT_KIND = { vapt: ["VAPT", "t-violet"], prguard: ["PR guard", "t-info"], incident: ["Incident", "t-warn"] };
async function viewReports() {
  const rows = await api("/api/reports");
  if (!rows.length) return `<section class="card"><div class="empty">No reports yet.</div></section>`;
  const kinds = [["all", "All"], ["vapt", "VAPT"], ["prguard", "PR guard"], ["incident", "Incidents"]];
  const shown = rows.filter((r) => UI.repKind === "all" || r.kind === UI.repKind);
  return `<section class="card"><div class="card-h"><div class="tabs">${kinds.map(([k, l]) => `<button data-repkind="${k}" class="${UI.repKind === k ? "on" : ""}">${l} (${k === "all" ? rows.length : rows.filter((r) => r.kind === k).length})</button>`).join("")}</div></div>
    <div class="card-b flush" style="margin-top:8px">${shown.length ? `<div class="table-wrap"><table class="t"><tr><th>Report</th><th>Title</th><th class="hide-sm">Subject</th><th>Max severity</th><th>Created</th></tr>
    ${shown.map((r) => { const [k, tone] = REPORT_KIND[r.kind] || [cap(r.kind), "t-mute"];
      return `<tr class="click" data-report="${r.id}"><td><span class="pill ${tone}">${k}</span></td>
        <td><div class="trunc" style="max-width:420px">${esc(r.title || "")}</div></td>
        <td class="hide-sm">${r.pr_number ? `PR #${r.pr_number} ` : ""}${r.ref_sha ? commitLink(r.ref_sha) : ""}</td>
        <td>${r.max_severity ? sevPill(r.max_severity) : "—"}</td><td class="faint small">${timeTag(r.created_ts)}</td></tr>`; }).join("")}</table></div>`
      : `<div class="empty small">No ${esc(kinds.find((k) => k[0] === UI.repKind)[1])} reports.</div>`}</div></section>`;
}
async function showReport(id) {
  openDrawer("Report", `<div class="empty small">Loading…</div>`);
  try { openDrawer(`Report #${id}`, md(await api(`/api/reports/${id}`))); }
  catch (e) { openDrawer(`Report #${id}`, `<div class="empty">Could not load the report: ${esc(e.message)}</div>`); }
}

// ── audit log ─────────────────────────────────────────────────────────────
async function viewAudit() {
  const [rows, chain] = await Promise.all([api("/api/actions?limit=500"), api("/api/audit/verify")]);
  const f = { all: () => true, enforce: (a) => a.mode === "enforce" && a.ok !== 0, observe: (a) => a.mode === "observe", failed: (a) => a.ok === 0 }[UI.auditFilter];
  const shown = rows.filter(f);
  return `<section class="card"><div class="card-h">
      <div class="tabs">${[["all", "All"], ["enforce", "Done"], ["observe", "Would do"], ["failed", "Failed"]].map(([k, l]) => `<button data-audit="${k}" class="${UI.auditFilter === k ? "on" : ""}">${l}</button>`).join("")}</div>
      <span class="spacer"></span>${chain.chain_ok ? `<span class="pill t-ok">${ic("check")}Tamper check passed</span>` : `<span class="pill t-crit">${ic("x")}Audit chain broken</span>`}</div>
    <div class="card-b flush" style="margin-top:8px">${shown.length ? `<div class="table-wrap"><table class="t"><tr><th>When</th><th>Action</th><th>Target</th><th>Outcome</th><th class="hide-sm">Detail</th></tr>
      ${shown.map((a) => `<tr><td class="faint small" style="white-space:nowrap">${timeTag(a.ts)}</td><td><b>${esc(decisionText(a))}</b></td><td><code>${esc(a.target)}</code></td>
        <td>${a.mode === "observe" ? statePill("needs_human", "Would do") : a.ok === 0 ? statePill("failed", "Failed") : statePill("ok", "Done")}</td>
        <td class="hide-sm muted small"><div class="trunc" style="max-width:380px" title="${esc(a.result || "")}">${esc(a.result || "")}</div></td></tr>`).join("")}</table></div>`
      : `<div class="empty small">Nothing here.</div>`}</div></section>`;
}

// ── settings ──────────────────────────────────────────────────────────────
async function viewSettings() {
  const st = S.status || {}, m = S.meta || {}, c = st.capabilities || {};
  return `<div class="stack"><div class="grid g-2">
    <section class="card"><div class="card-h"><h2>Capability modes</h2></div><div class="card-b flush"><table class="t">
      ${CAPS.map((k) => `<tr><td><div class="row">${ic(k.icon)}<b>${k.name}</b></div></td><td>${modePill((st.modes || {})[k.id])}</td></tr>`).join("")}</table>
      <div class="card-b"><p class="muted small" style="margin:0 0 8px">The dashboard is read-only. Change modes from the Spark:</p>
      <div class="cli">flect mode crash observe</div><div class="cli" style="margin-top:6px">flect pause "maintenance"</div><div class="cli" style="margin-top:6px">flect resume</div></div></div></section>
    <section class="card"><div class="card-h"><h2>Environment</h2></div><div class="card-b"><dl class="kv">
      <dt>Protecting</dt><dd><b>${esc((m.target || "").toUpperCase())}</b> · <a href="${esc(m.repo_url)}" target="_blank" rel="noopener">${esc(m.repo)}</a></dd>
      <dt>Production</dt><dd><code>${esc(m.prod_url)}</code></dd><dt>UAT</dt><dd><code>${esc(m.uat_url)}</code> · ${esc(c.uat || "")}</dd>
      <dt>Branches</dt><dd>features → <code>${esc(m.feature_base)}</code> → release → <code>${esc(m.prod_branch)}</code></dd>
      <dt>Sandbox</dt><dd>${okDot(depOk("sandbox"), c.sandbox || "—")}</dd><dt>Firewall</dt><dd>${okDot(depOk("nft"), c.nft || "—")}</dd>
      <dt>DeepSeek</dt><dd>${okDot(depOk("llm"), c.llm || "—")}</dd><dt>GitHub</dt><dd>${okDot(depOk("github"), st.writes_paused ? "paused: " + st.writes_paused : "writes enabled")}</dd>
      <dt>Log lines read</dt><dd class="num">${num(c.log_lines)}${c.stale_lines_skipped ? ` · ${num(c.stale_lines_skipped)} stale skipped` : ""}</dd>
      <dt>Flect</dt><dd>v${esc(m.version)} · up ${m.started ? dur(Date.now() / 1000 - m.started) : "—"}</dd></dl></div></section></div></div>`;
}

// ── render loop ───────────────────────────────────────────────────────────
const VIEW_FN = { overview: [viewOverview, afterOverview], incidents: [viewIncidents], prs: [viewPRs], traffic: [viewTraffic, afterTraffic],
  deploys: [viewDeploys], keys: [viewKeys], reports: [viewReports], audit: [viewAudit], settings: [viewSettings] };
let rendering = false;
async function render() {
  if (rendering) return; rendering = true;
  try {
    const id = VIEW_FN[route()] ? route() : "overview", v = VIEWS.find((x) => x.id === id);
    document.getElementById("page-title").textContent = v.label;
    document.title = `${v.label} · Flect`;
    renderNav(); renderThemeBtn();
    const [fn, after] = VIEW_FN[id];
    document.getElementById("view").innerHTML = await fn();
    if (after) after();
  } catch (e) {
    document.getElementById("view").innerHTML = `<section class="card"><div class="empty">${ic("alert")}Could not load this view: ${esc(e.message)}</div></section>`;
  } finally { rendering = false; }
}
async function refresh() {
  try {
    const [status, overview, history] = await Promise.all([api("/api/status"), api("/api/overview"), api("/api/history")]);
    if (!S.meta) S.meta = await api("/api/meta");
    Object.assign(S, { status, overview, history, lastOk: Date.now() });
    document.getElementById("foot-meta").innerHTML = `<div>${esc(S.meta.repo)}</div><div>Flect v${esc(S.meta.version)}</div>`;
  } catch (e) { /* keep the last good data; the live indicator turns red */ }
}
function tickLive() {
  const el = document.getElementById("live"), age = (Date.now() - S.lastOk) / 1000;
  el.classList.toggle("stale", !S.lastOk || age > 20);
  document.getElementById("live-text").textContent = !S.lastOk ? "connecting…" : age > 20 ? `offline · last update ${dur(age)} ago` : "Live";
}
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-inc],[data-tab],[data-report],[data-audit],[data-repkind]");
  if (!t || e.target.closest("a[href^='http']")) return;
  if (t.dataset.inc) { location.hash = `#/incidents/${t.dataset.inc}`; return; }
  else if (t.dataset.tab) { UI.incTab = t.dataset.tab; render(); }
  else if (t.dataset.report) { e.preventDefault(); location.hash = `#/reports/${t.dataset.report}`; }
  else if (t.dataset.audit) { UI.auditFilter = t.dataset.audit; render(); }
  else if (t.dataset.repkind) { UI.repKind = t.dataset.repkind; render(); }
});
let resizeT; window.addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(render, 200); });
(async function boot() {
  renderThemeBtn();
  await refresh(); tickLive(); await render(); openDeepLink();
  setInterval(tickLive, 1000);
  setInterval(async () => { await refresh(); await render(); }, 5000);
})();
