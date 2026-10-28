// Renders docs/companies.json (written daily by scripts/fetch_companies.py).

const VERDICTS = {
  buy: { label: "Buy candidate", cls: "green" },
  watch: { label: "Wait for a better price", cls: "yellow" },
  avoid: { label: "Doesn't fit", cls: "red" },
  too_early: { label: "Too early", cls: "gray" },
  no_data: { label: "No data yet", cls: "gray" },
};
const ORDER = ["buy", "watch", "too_early", "avoid", "no_data"];
const INTRO = {
  watchlist: "Companies from watchlist.txt in the repository. Edit that file on GitHub to add or remove tickers.",
  ipos: "US companies that went public in roughly the last 12 months, found from their SEC IPO prospectus filings (SPACs and funds excluded).",
};

const state = { data: null, tab: "watchlist", filter: "all", query: "" };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
const money = (v) => (v == null ? "—" : "$" + v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const pct = (v, d = 1) => (v == null ? "—" : v.toFixed(d) + "%");

function big(v) {
  if (v == null) return "—";
  const a = Math.abs(v), sign = v < 0 ? "−" : "";
  if (a >= 1e12) return `${sign}$${(a / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(0)}M`;
  return `${sign}$${a.toLocaleString()}`;
}

function checkValue(c) {
  if (c.value == null) return "n/a";
  if (c.key === "fcf") return `${c.value} yrs positive`;
  if (c.key === "profits") return c.value === 0 ? "no losses" : `${c.value} loss yr${c.value === 1 ? "" : "s"}`;
  if (c.key === "debt") return `${c.value.toFixed(1)} yrs of earnings`;
  return pct(c.value);
}

function row(c) {
  const v = VERDICTS[c.verdict] || VERDICTS.no_data;
  const val = c.valuation || {};
  const checks = (c.checks || []).map((k) => `
    <li class="check ${k.status}">
      <span class="mark" aria-label="${k.status}">${k.status === "pass" ? "✓" : k.status === "fail" ? "✗" : "–"}</span>
      <div><strong>${esc(k.title)}</strong> <span class="muted">${esc(checkValue(k))} · target: ${esc(k.target)}</span>
      <div class="muted small">${esc(k.explain)}</div></div>
    </li>`).join("");
  const history = (c.history || []).slice().reverse().map((h) => `
    <tr><td>${esc(h.end.slice(0, 4))}</td><td>${big(h.revenue)}</td><td>${big(h.net_income)}</td><td>${big(h.fcf)}</td></tr>`).join("");
  const ipo = c.kind === "ipo" ? `
    <div class="facts">
      <span>IPO prospectus: <strong>${fmtDate(c.ipo_date)}</strong></span>
      ${c.first_close ? `<span>First-day close: ${money(c.first_close)}${c.change_since_first_close != null ? ` (${c.change_since_first_close > 0 ? "+" : ""}${c.change_since_first_close}% since)` : ""}</span>` : ""}
      ${c.industry ? `<span>${esc(c.industry)} · ${esc(c.exchange)}</span>` : ""}
    </div>` : "";
  const score = c.scored ? `${c.passed}/${c.scored} checks` : "";
  return `<details class="company">
    <summary>
      <span class="ticker">${esc(c.ticker)}</span>
      <span class="name">${esc(c.name)}</span>
      <span class="pill ${v.cls}">${v.label}</span>
      <span class="nums">
        <span><small>Price</small>${money(c.price)}</span>
        <span><small>Buy below</small>${money(val.buy_below)}</span>
        <span class="hide-sm"><small>Score</small>${score || "—"}</span>
      </span>
    </summary>
    <div class="company-body">
      <p class="verdict-text">${esc(c.verdict_text)}</p>
      ${ipo}
      ${(c.notes || []).map((n) => `<p class="note">${esc(n)}</p>`).join("")}
      <div class="facts">
        <span>Intrinsic value: <strong>${money(val.intrinsic_value)}</strong>/share</span>
        <span>P/E: ${val.pe ?? "—"}</span>
        <span>Owner-earnings yield: ${pct(val.owner_earnings_yield, 2)}${val.treasury_yield != null ? ` vs ${val.treasury_yield}% Treasury` : ""}</span>
        <span>Growth assumed: ${pct(val.growth_used)}</span>
      </div>
      ${checks ? `<ul class="checks">${checks}</ul>` : ""}
      ${history ? `<table class="hist"><caption>Annual results (SEC filings)</caption>
        <thead><tr><th>Year</th><th>Revenue</th><th>Net income</th><th>Free cash flow</th></tr></thead>
        <tbody>${history}</tbody></table>` : ""}
      <p class="small"><a href="${esc(c.sec_url)}">SEC filings</a> · ${c.years_of_data ?? 0} years of annual data${c.price_source ? ` · price via ${esc(c.price_source)}` : ""}</p>
    </div>
  </details>`;
}

function render() {
  const all = state.data[state.tab] || [];
  const counts = Object.fromEntries(ORDER.map((k) => [k, all.filter((c) => c.verdict === k).length]));
  document.getElementById("filters").innerHTML = [["all", `All (${all.length})`],
    ...ORDER.filter((k) => counts[k]).map((k) => [k, `${VERDICTS[k].label} (${counts[k]})`])]
    .map(([k, label]) => `<button data-filter="${k}" aria-pressed="${state.filter === k}">${esc(label)}</button>`).join("");

  const q = state.query.toLowerCase();
  const shown = all
    .filter((c) => state.filter === "all" || c.verdict === state.filter)
    .filter((c) => !q || c.ticker.toLowerCase().includes(q) || (c.name || "").toLowerCase().includes(q))
    .sort((a, b) => ORDER.indexOf(a.verdict) - ORDER.indexOf(b.verdict)
      || (state.tab === "ipos" ? (b.ipo_date || "").localeCompare(a.ipo_date || "") : a.ticker.localeCompare(b.ticker)));
  document.getElementById("list").innerHTML = shown.length
    ? shown.map(row).join("") : `<p class="muted">No companies match.</p>`;
  document.getElementById("tab-intro").textContent = INTRO[state.tab];
}

function setup(data) {
  state.data = data;
  document.getElementById("count-watchlist").textContent = data.watchlist.length;
  document.getElementById("count-ipos").textContent = data.ipos.length;
  for (const el of document.querySelectorAll("[data-rule]")) {
    el.textContent = pct(data.rules[el.dataset.rule] * 100, 0);
  }
  if (data.treasury_yield != null) document.getElementById("treasury").textContent = ` (now ${data.treasury_yield}%)`;
  document.getElementById("updated").textContent = `Last checked ${new Date(data.generated_at).toLocaleString()}.`
    + (data.errors.length ? ` ${data.errors.length} item(s) couldn't be loaded: ${data.errors.map((e) => e.ticker).join(", ")}.` : "");

  document.querySelector(".tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (!b) return;
    state.tab = b.dataset.tab; state.filter = "all";
    for (const t of document.querySelectorAll(".tabs button")) t.setAttribute("aria-selected", t === b);
    render();
  });
  document.getElementById("filters").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-filter]");
    if (b) { state.filter = b.dataset.filter; render(); }
  });
  document.getElementById("search").addEventListener("input", (e) => { state.query = e.target.value.trim(); render(); });
  render();
}

fetch("companies.json", { cache: "no-store" })
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(setup)
  .catch(() => {
    document.getElementById("list").innerHTML =
      `<p>No data yet. Run the “Update market data” GitHub Action to generate <code>companies.json</code>.</p>`;
  });
