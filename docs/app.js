// Renders docs/data.json (written daily by scripts/fetch_data.py) into the dashboard.

const STATUS_LABEL = { green: "OK", yellow: "Caution", red: "Warning" };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function daysUntil(iso) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  return Math.round((new Date(iso + "T00:00:00") - today) / 86400000);
}

function fmtValue(ind) {
  if (ind.value == null) return "—";
  const v = ind.value;
  const digits = Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2;
  const signed = ["change_1y", "yoy_gap", "yoy_pct", "avg_change_3"].includes(ind.metric) && v > 0;
  return (signed ? "+" : "") + v.toFixed(digits);
}

function sparkline(history) {
  if (!history || history.length < 2) return "";
  const w = 300, h = 48, pad = 3;
  const vals = history.map((p) => p[1]);
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const d = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * w;
    const y = h - pad - ((v - min) / span) * (h - pad * 2);
    return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join("");
  const label = `Trend from ${history[0][0]} to ${history[history.length - 1][0]}`;
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="${esc(label)}"><path d="${d}"/></svg>`;
}

function card(ind) {
  const status = ind.status || "none";
  if (ind.error) {
    return `<article class="card"><h3>${esc(ind.name)}</h3>
      <p class="error">Couldn't load this indicator on the last run.</p>
      <p class="why">${esc(ind.why)}</p>
      <div class="meta"><a href="${esc(ind.source_url)}">View on FRED</a></div></article>`;
  }
  const next = ind.next_release
    ? `Next release: <strong>${fmtDate(ind.next_release)}</strong>`
    : "Next release: not yet scheduled";
  return `<article class="card ${status}">
    <span class="label ${status}">${STATUS_LABEL[ind.status] || "No data"}</span>
    <h3>${esc(ind.name)}</h3>
    <div class="value">${fmtValue(ind)}<span class="unit">${esc(ind.unit)}</span></div>
    ${sparkline(ind.history)}
    <p class="why">${esc(ind.why)}</p>
    ${ind.stale ? `<p class="warn">⚠ Data is older than usual for this series. It may be paused or delayed.</p>` : ""}
    <div class="meta">
      <span>Data as of ${fmtDate(ind.as_of)}</span>
      <span>${next}</span>
    </div>
    <details><summary>Details</summary>
      <div class="meta">
        <span>${esc(ind.thresholds)}</span>
        <span>Series: <a href="${esc(ind.source_url)}">${esc(ind.series)}</a>, ${esc(ind.series_title)} (${esc(ind.frequency)})</span>
        <span>Latest reading: ${esc(ind.latest_level)} ${esc(ind.units)}</span>
        <span>Source release: ${esc(ind.release_name)}</span>
      </div>
    </details>
  </article>`;
}

function renderVerdict(data) {
  const v = data.verdict;
  const el = document.getElementById("verdict");
  el.className = `verdict ${v.status}`;
  const chips = data.categories.map((c) =>
    `<span class="chip"><span class="dot ${c.status || ""}"></span>${esc(c.title)}</span>`).join("");
  el.innerHTML = `<h2>${esc(v.title)}</h2>
    <p>${esc(v.text)}</p>
    <p class="small">${v.red_categories} of ${v.total_categories} areas red, ${v.yellow_categories} yellow.</p>
    <div class="tally">${chips}</div>`;
}

function renderCategories(data) {
  document.getElementById("categories").innerHTML = data.categories.map((c) => `
    <section class="category" id="${esc(c.id)}">
      <div class="category-head">
        <span class="dot ${c.status || ""}"></span>
        <h2>${esc(c.title)}</h2>
        <span class="question">${esc(c.question)}</span>
      </div>
      <div class="cards">${c.indicators.map(card).join("")}</div>
    </section>`).join("");
}

function renderCalendar(data) {
  const el = document.getElementById("calendar");
  if (!data.calendar.length) {
    el.innerHTML = `<li><span class="muted">No scheduled releases found in the next 45 days.</span></li>`;
    return;
  }
  el.innerHTML = data.calendar.map((e) => {
    const n = daysUntil(e.date);
    const soon = n === 0 ? "Today" : n === 1 ? "Tomorrow" : n > 1 && n <= 7 ? `In ${n} days` : "";
    const name = e.link ? `<a href="${esc(e.link)}">${esc(e.release)}</a>` : esc(e.release);
    return `<li>
      <div class="when">${fmtDate(e.date)}${soon ? `<span class="soon">${soon}</span>` : ""}</div>
      <div class="what">${name}<span>${e.indicators.map(esc).join(" · ")}</span></div>
    </li>`;
  }).join("");
}

async function main() {
  try {
    const res = await fetch("data.json", { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    renderVerdict(data);
    renderCategories(data);
    renderCalendar(data);
    document.getElementById("updated").textContent =
      `Last checked ${new Date(data.generated_at).toLocaleString()}.` +
      (data.errors.length ? ` ${data.errors.length} indicator(s) failed to load.` : "");
  } catch (err) {
    document.getElementById("verdict").innerHTML =
      `<h2>No data yet</h2><p>Run the “Update market data” GitHub Action (or <code>python scripts/fetch_data.py</code>) to generate <code>data.json</code>.</p>`;
  }
}

main();
