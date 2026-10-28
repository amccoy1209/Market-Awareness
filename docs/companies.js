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
  watchlist: "Your watchlist. Add or remove companies right here once GitHub is connected, or edit watchlist.txt in the repository.",
  ipos: "US companies that went public in roughly the last 12 months, found from their SEC IPO prospectus filings (SPACs and funds excluded).",
  discover: "",
  holdings: "Your positions, judged the way Buffett and Munger decide whether to hold or sell. What you paid doesn't change the verdict: "
    + "the only question is whether you'd buy the business today at this price.",
};
const SAMPLE_SIZE = 25;

const state = { data: null, pool: [], tab: "watchlist", filter: "all", query: "" };

function shuffleSample() {
  const pool = state.pool.slice();
  for (let i = pool.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  state.data.discover = pool.slice(0, SAMPLE_SIZE);
}

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

function impliedText(val) {
  const past = val.growth_used != null ? ` (past growth ${pct(val.growth_used)})` : "";
  if (val.implied_growth != null) return `Price assumes <strong>${pct(val.implied_growth)}</strong> growth a year for 10 years${past}`;
  if (val.owner_earnings_yield != null) {
    // Outside the range the reverse calculation searches (−20% to 60% a year).
    return val.price < val.intrinsic_value ? `Price assumes cash flow shrinking over 20% a year${past}`
      : `Price assumes over 60% growth a year${past}`;
  }
  return `Past growth: ${pct(val.growth_used)}`;
}

function newsSection(n) {
  if (!n) return "";
  const t = n.trend || {};
  const trend = t.below_high != null
    ? `${t.below_high > 0 ? `${t.below_high}% below` : "At"} its 52-week high of ${money(t.high_52w)}${t.change_6m != null ? ` · ${t.change_6m > 0 ? "+" : ""}${t.change_6m}% over 6 months` : ""}`
    : "Price trend unavailable";
  const flags = (n.flags || []).map((f) => `<li class="${f.level === "red" ? "bad" : "warn"}">${esc(f.text)}</li>`).join("");
  const filings = (n.filings || []).map((f) => `<li><a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.date)}</a>: ${f.items.map((i) => esc(i.text)).join("; ")}</li>`).join("");
  const headlines = (n.headlines || []).map((h) => `<li><a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a>
    <span class="muted">${esc(h.source)}${h.date ? ` · ${fmtDate(h.date)}` : ""}</span></li>`).join("");
  return `<div class="news">
    <h4>News check <span class="muted small">as of ${fmtDate(n.checked)}</span></h4>
    <p class="small">${esc(trend)}</p>
    <ul class="points">${flags || `<li class="good">No warning signs in recent SEC filings or the price trend.</li>`}</ul>
    ${filings ? `<details><summary>SEC 8-K filings, last 6 months (${n.filings.length})</summary><ul class="small">${filings}</ul></details>` : ""}
    ${headlines ? `<details open><summary>Recent headlines (${n.headlines.length})</summary><ul class="small headlines">${headlines}</ul></details>`
      : `<p class="small muted">No headlines found in the last 30 days.</p>`}
    <p class="small muted">A low price can have a reason the financial statements don't show yet. Read these before buying.</p>
  </div>`;
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
  const removable = c.kind === "watchlist" && !c.pending && GitHubWatchlist.connected();
  return `<details class="company${c.pending ? " pending" : ""}">
    <summary>
      <span class="ticker">${esc(c.ticker)}</span>
      <span class="name">${esc(c.name)}</span>
      <span class="pill ${v.cls}">${v.label}</span>
      <span class="nums">
        <span><small>Price</small>${money(c.price)}</span>
        <span><small>Buy below</small>${money(val.buy_below)}</span>
        ${c.kind === "discovery"
          ? `<span class="hide-sm"><small>Rev. growth</small>${pct(val.revenue_growth)}</span>`
          : `<span class="hide-sm"><small>Score</small>${score || "—"}</span>`}
      </span>
    </summary>
    <div class="company-body">
      <p class="verdict-text">${esc(c.verdict_text)}</p>
      ${newsSection(c.news_check)}
      ${ipo}
      ${(c.notes || []).map((n) => `<p class="note">${esc(n)}</p>`).join("")}
      <div class="facts">
        <span>Intrinsic value: <strong>${money(val.intrinsic_value)}</strong>/share</span>
        <span>P/E: ${val.pe ?? "—"}</span>
        <span>Owner-earnings yield: ${pct(val.owner_earnings_yield, 2)}${val.treasury_yield != null ? ` vs ${val.treasury_yield}% Treasury` : ""}</span>
        <span>${impliedText(val)}</span>
        <span>Revenue growth: ${pct(val.revenue_growth)}/yr</span>
        <span>Market value: ${big(val.market_cap)}</span>
        ${c.scanned ? `<span class="muted">Scanned ${fmtDate(c.scanned)}</span>` : ""}
      </div>
      ${checks ? `<ul class="checks">${checks}</ul>` : ""}
      ${history ? `<table class="hist"><caption>Annual results (SEC filings)</caption>
        <thead><tr><th>Year</th><th>Revenue</th><th>Net income</th><th>Free cash flow</th></tr></thead>
        <tbody>${history}</tbody></table>` : ""}
      ${removable ? `<p><button class="remove" data-remove="${esc(c.ticker)}">Remove ${esc(c.ticker)} from watchlist</button></p>` : ""}
      ${c.pending ? "" : `<p class="small"><a href="${esc(c.sec_url)}">SEC filings</a> · ${c.years_of_data ?? 0} years of annual data${c.price_source ? ` · price via ${esc(c.price_source)}` : ""}</p>`}
    </div>
  </details>`;
}

function render() {
  Alerts.show(state.raw, state.discoveryRaw);
  const holdingsTab = state.tab === "holdings";
  document.getElementById("holdings").hidden = !holdingsTab;
  document.querySelector(".toolbar").hidden = holdingsTab;
  document.getElementById("list").hidden = holdingsTab;
  document.getElementById("count-holdings").textContent = new Set(Holdings.load().map((l) => l.ticker)).size || "";
  if (holdingsTab) {
    document.getElementById("tab-intro").textContent = INTRO.holdings;
    renderHoldings();
    renderEditor();
    return;
  }
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
      || (state.tab === "ipos" ? (b.ipo_date || "").localeCompare(a.ipo_date || "")
        : state.tab === "discover" ? (b.valuation.revenue_growth || 0) - (a.valuation.revenue_growth || 0)
        : a.ticker.localeCompare(b.ticker)));
  document.getElementById("list").innerHTML = shown.length ? shown.map(row).join("")
    : state.tab === "discover" && !state.pool.length
      ? `<p class="muted">No hidden-gem candidates found yet. The daily scan adds more companies each day.</p>`
      : `<p class="muted">No companies match.</p>`;
  document.getElementById("shuffle").hidden = state.tab !== "discover" || state.pool.length <= SAMPLE_SIZE;
  document.getElementById("tab-intro").textContent = INTRO[state.tab];
  document.getElementById("count-watchlist").textContent = state.data.watchlist.length;
  renderEditor();
}

function applyData(data, discovery) {
  const sample = state.data && state.data.discover;
  state.raw = data;
  // Work on a copy so pending edits can be overlaid and recomputed without touching the published data.
  state.data = { ...data, watchlist: [...data.watchlist], errors: [...data.errors] };
  if (discovery === undefined) {
    state.data.discover = sample || [];
  } else {
    state.discoveryRaw = discovery;
    state.pool = discovery ? discovery.candidates : [];
    shuffleSample();
    const r = discovery && discovery.rules;
    INTRO.discover = discovery
      ? `${SAMPLE_SIZE} random picks from ${state.pool.length} under-the-radar candidates: market value $${r.gem_min_cap / 1e6}M–$${r.gem_max_cap / 1e9}B, `
        + `revenue growing ${r.gem_min_revenue_growth}%+ a year, and passing the business checks. `
        + `${discovery.scanned_count.toLocaleString()} of ${discovery.universe.toLocaleString()} NYSE/Nasdaq companies scanned so far (250 a day, rescanned monthly). `
        + `Buy candidates (below their buy-below price) are listed first.`
      : "The discovery scan hasn't run yet.";
    document.getElementById("count-discover").textContent = Math.min(SAMPLE_SIZE, state.pool.length);
  }
  document.getElementById("count-ipos").textContent = data.ipos.length;
  for (const el of document.querySelectorAll("[data-rule]")) {
    el.textContent = pct(data.rules[el.dataset.rule] * 100, 0);
  }
  if (data.treasury_yield != null) document.getElementById("treasury").textContent = ` (now ${data.treasury_yield}%)`;
  if (data.discount_rate != null) document.getElementById("discount-rate").textContent = ` (${data.discount_rate}% now)`;
  document.getElementById("updated").textContent = `Last checked ${new Date(data.generated_at).toLocaleString()}.`
    + (data.errors.length ? ` ${data.errors.length} item(s) couldn't be loaded: ${data.errors.map((e) => e.ticker).join(", ")}.` : "");
  const pending = applyPendingEdits();
  render();
  return pending;
}

// --- My holdings (see holdings.js) -------------------------------------------------

function findCompany(ticker) {
  return state.data.watchlist.find((c) => c.ticker === ticker)
    || state.data.ipos.find((c) => c.ticker === ticker)
    || state.pool.find((c) => c.ticker === ticker);
}

function setTab(tab, query = "") {
  state.tab = tab; state.filter = "all"; state.query = query;
  document.getElementById("search").value = query;
  for (const t of document.querySelectorAll(".tabs button")) t.setAttribute("aria-selected", t.dataset.tab === tab);
  render();
}

function setHoldingsStatus(text, kind = "") {
  const el = document.getElementById("holdings-status");
  el.className = `small${kind ? ` status-${kind}` : ""}`;
  el.textContent = text;
}

function renderHoldings() {
  const { money } = Holdings;
  const list = Holdings.positions(Holdings.load(), findCompany).sort((a, b) => b.weight - a.weight);
  const buyCandidates = [...new Set([...state.data.watchlist, ...state.pool]
    .filter((c) => c.verdict === "buy").map((c) => c.ticker))];
  const ctx = { treasury: state.data.treasury_yield, buyCandidates, today: new Date() };

  const priced = list.filter((p) => p.value != null);
  const value = priced.reduce((s, p) => s + p.value, 0);
  const cost = priced.reduce((s, p) => s + p.cost, 0);
  const gain = value - cost;
  const signed = (v) => `${v > 0 ? "+" : ""}${money(v)}`;
  document.getElementById("holdings-summary").innerHTML = list.length ? `
    <div><small>Market value</small><strong>${money(value)}</strong></div>
    <div><small>Cost</small><strong>${money(cost)}</strong></div>
    <div><small>Gain / loss</small><strong class="${gain >= 0 ? "gain" : "loss"}">${signed(gain)}${cost ? ` (${((gain / cost) * 100).toFixed(1)}%)` : ""}</strong></div>
    <div><small>Positions</small><strong>${list.length}</strong></div>
    ${priced.length < list.length ? `<p class="small muted">Value and gain leave out ${list.filter((p) => p.value == null).map((p) => esc(p.ticker)).join(", ")}, which ${list.length - priced.length === 1 ? "has" : "have"} no price yet.</p>` : ""}` : "";

  const connected = GitHubWatchlist.connected();
  document.getElementById("holdings-list").innerHTML = list.length ? list.map((p) => {
    const a = Holdings.analyze(p, ctx);
    const c = p.company;
    const pctGain = p.gain != null && p.cost ? (p.gain / p.cost) * 100 : null;
    const lots = p.lots.map((l) => {
      const g = p.price != null ? (p.price - l.price) * l.shares : null;
      return `<tr><td>${l.date ? esc(l.date) : "—"}</td><td>${l.shares.toLocaleString()}</td><td>${money(l.price)}</td>
        <td class="${g == null ? "" : g >= 0 ? "gain" : "loss"}">${g == null ? "—" : signed(g)}</td>
        <td><button class="linklike" data-del-lot="${esc(l.id)}" aria-label="Delete this lot">Delete</button></td></tr>`;
    }).join("");
    const where = c && !c.pending ? { watchlist: "watchlist", ipo: "ipos", discovery: "discover" }[c.kind] : null;
    const action = where
      ? `<button class="linklike" data-view="${where}" data-ticker="${esc(p.ticker)}">See the full checklist</button>`
      : c && c.pending ? `<span class="muted small">Being scored now; check back in a few minutes.</span>`
        : connected ? `<button class="remove" data-score="${esc(p.ticker)}">Score it (adds ${esc(p.ticker)} to your watchlist)</button>`
          : `<span class="muted small">Connect GitHub on the Watchlist tab to have it scored. Only the ticker becomes public, never your shares or cost.</span>`;
    return `<details class="company">
      <summary>
        <span class="ticker">${esc(p.ticker)}</span>
        <span class="name">${esc(c && !c.pending ? c.name : "")}</span>
        <span class="pill ${a.cls}">${esc(a.label)}</span>
        <span class="nums">
          <span><small>Value</small>${money(p.value ?? p.cost)}</span>
          <span><small>Gain</small><span class="${pctGain == null ? "" : pctGain >= 0 ? "gain" : "loss"}">${pctGain == null ? "—" : `${pctGain > 0 ? "+" : ""}${pctGain.toFixed(1)}%`}</span></span>
          <span class="hide-sm"><small>Weight</small>${p.weight.toFixed(0)}%</span>
        </span>
      </summary>
      <div class="company-body">
        <p class="verdict-text">${esc(a.text)}</p>
        <ul class="points">${a.points.map((pt) => `<li class="${pt.kind}">${esc(pt.text)}</li>`).join("")}</ul>
        <table class="hist"><caption>Your lots${p.price != null ? ` · latest price ${money(p.price)}` : ""}</caption>
          <thead><tr><th>Bought</th><th>Shares</th><th>Paid</th><th>Gain</th><th></th></tr></thead>
          <tbody>${lots}</tbody></table>
        <div class="lot-actions">${action}</div>
      </div>
    </details>`;
  }).join("") : `<p class="muted">No holdings yet. Add a position above: ticker, number of shares and the price you paid per share.</p>`;
}

function addLot() {
  const ticker = document.getElementById("lot-ticker").value.trim().toUpperCase().replace(/^\$/, "");
  const shares = parseFloat(document.getElementById("lot-shares").value);
  const price = parseFloat(document.getElementById("lot-price").value);
  const date = document.getElementById("lot-date").value;
  const lot = { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, ticker, shares, price, date: date || null };
  if (!Holdings.valid(lot)) {
    return setHoldingsStatus("Enter a ticker (like NFLX), a number of shares above 0 and the price you paid per share.", "err");
  }
  if (!Holdings.save([...Holdings.load(), lot])) {
    return setHoldingsStatus("This browser is blocking storage, so holdings can't be saved here.", "err");
  }
  for (const id of ["lot-ticker", "lot-shares", "lot-price", "lot-date"]) document.getElementById(id).value = "";
  setHoldingsStatus(findCompany(ticker) ? `Added ${ticker}.`
    : `Added ${ticker}. It isn't scored yet; open it below to have it scored.`, "ok");
  render();
}

function exportHoldings() {
  const blob = new Blob([JSON.stringify(Holdings.load(), null, 1)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "market-awareness-holdings.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

async function importHoldings(file) {
  try {
    const lots = JSON.parse(await file.text());
    if (!Array.isArray(lots)) throw new Error();
    const good = lots.filter(Holdings.valid).map((l) => ({ id: String(l.id || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`),
      ticker: l.ticker, shares: l.shares, price: l.price, date: l.date || null }));
    if (!good.length) throw new Error();
    if (Holdings.load().length && !confirm(`Replace your current holdings with the ${good.length} lot(s) in this file?`)) return;
    Holdings.save(good);
    setHoldingsStatus(`Imported ${good.length} lot(s)${good.length < lots.length ? `; skipped ${lots.length - good.length} invalid` : ""}.`, "ok");
    render();
  } catch {
    setHoldingsStatus("That file isn't a holdings export from this app.", "err");
  }
}

// --- Watchlist editing (see github.js) -------------------------------------------

let refreshTimer = null;

// Edits GitHub has accepted but the published data may not show yet (the rescore and site redeploy take a few
// minutes). Kept in this browser so they survive closing the app.
const PENDING_KEY = "market-awareness-pending-edits";
const PENDING_MAX_AGE = 30 * 60 * 1000;

function loadPending() {
  try { return JSON.parse(localStorage.getItem(PENDING_KEY)) || []; } catch { return []; }
}

function savePending(list) {
  try { localStorage.setItem(PENDING_KEY, JSON.stringify(list)); } catch { /* storage blocked */ }
}

const listed = (data, t) => data.watchlist.some((c) => c.ticker === t) || data.errors.some((e) => e.ticker === t);

/** Overlay pending edits on state.data. Returns {open, stale}: edits still waiting, and ones that gave up. */
function applyPendingEdits() {
  const open = [], stale = [];
  for (const p of loadPending()) {
    if ((p.action === "add") === listed(state.raw, p.ticker)) continue;  // published data shows it now
    (Date.now() - p.at < PENDING_MAX_AGE ? open : stale).push(p);
  }
  savePending(open);
  for (const p of open) {
    state.data.watchlist = state.data.watchlist.filter((c) => c.ticker !== p.ticker);
    state.data.errors = state.data.errors.filter((e) => e.ticker !== p.ticker);
    if (p.action === "add") {
      state.data.watchlist.push({ kind: "watchlist", ticker: p.ticker, name: "Scoring…", pending: true, verdict: "no_data",
        verdict_text: "Being scored now. This page will refresh by itself when the results are ready." });
    }
  }
  if (stale.length) {
    setStatus(`${stale.map((p) => p.ticker).join(", ")} still hadn't updated after 30 minutes. Check`, "err",
      { href: GitHubWatchlist.actionsUrl, text: "GitHub Actions" });
  }
  return { open, stale };
}

function watchErrors() {
  const ipoTickers = new Set(state.data.ipos.map((i) => i.ticker));
  return state.data.errors.filter((e) => e.ticker !== "IPOs" && !ipoTickers.has(e.ticker));
}

function setStatus(text, kind = "", link = null) {
  const el = document.getElementById("editor-status");
  el.className = `small${kind ? ` status-${kind}` : ""}`;
  el.textContent = text;
  if (link) {
    const a = document.createElement("a");
    a.href = link.href; a.textContent = link.text; a.target = "_blank"; a.rel = "noopener";
    el.append(" ", a, ".");
  }
}

function renderEditor() {
  const connected = GitHubWatchlist.connected();
  document.getElementById("editor").hidden = state.tab !== "watchlist";
  document.getElementById("editor-connected").hidden = !connected;
  document.getElementById("editor-connect").hidden = connected;
  document.getElementById("watch-errors").innerHTML = watchErrors().map((e) => `
    <div class="watch-error status-err">
      <span>Couldn't score <strong>${esc(e.ticker)}</strong>: ${esc(e.error)}</span>
      ${connected ? `<button class="remove" data-remove="${esc(e.ticker)}">Remove</button>` : ""}
    </div>`).join("");
}

function setBusy(busy) {
  for (const b of document.querySelectorAll("#editor button, .remove")) b.disabled = busy;
}

/** Poll for newly published data until every pending edit shows up in it. */
function waitForRescore() {
  clearInterval(refreshTimer);
  refreshTimer = setInterval(async () => {
    try {
      const data = await getJSON("companies.json");
      if (data.generated_at === state.raw.generated_at) return;
      const { open, stale } = applyData(data);
      if (!open.length) {
        clearInterval(refreshTimer);
        if (!stale.length) setStatus("Watchlist updated.", "ok");
      }
    } catch { /* site still redeploying; try again */ }
  }, 20000);
}

async function runEdit(action, ticker, kind, doneText) {
  setBusy(true);
  setStatus("Saving to GitHub…");
  try {
    if (!(await action())) {
      setStatus("Nothing to change: the watchlist file already had that.");
      return false;
    }
    savePending([...loadPending().filter((p) => p.ticker !== ticker), { ticker, action: kind, at: Date.now() }]);
    applyData(state.raw);
    setStatus(`${doneText} Rescoring now; this page refreshes by itself in about 2–5 minutes.`, "ok");
    waitForRescore();
    return true;
  } catch (err) {
    setStatus(err.message, "err");
    return false;
  } finally {
    setBusy(false);
  }
}

async function addTicker(raw) {
  const t = raw.trim().toUpperCase().replace(/^\$/, "");
  if (!/^[A-Z][A-Z0-9.-]{0,9}$/.test(t)) return setStatus("Enter a stock ticker, like NVDA or BRK-B.", "err");
  if (listed(state.data, t)) return setStatus(`${t} is already on your watchlist.`, "err");
  if (await runEdit(() => GitHubWatchlist.add(t), t, "add", `Added ${t}.`)) {
    document.getElementById("add-ticker").value = "";
  }
}

function removeTicker(t) {
  if (!confirm(`Remove ${t} from your watchlist?`)) return;
  return runEdit(() => GitHubWatchlist.remove(t), t, "remove", `Removed ${t}.`);
}

function bindEvents() {
  document.querySelector(".tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (b) setTab(b.dataset.tab, state.query);
  });
  document.getElementById("lot-form").addEventListener("submit", (e) => { e.preventDefault(); addLot(); });
  document.getElementById("export-holdings").addEventListener("click", exportHoldings);
  document.getElementById("import-holdings").addEventListener("change", (e) => {
    if (e.target.files[0]) importHoldings(e.target.files[0]);
    e.target.value = "";
  });
  document.getElementById("holdings-list").addEventListener("click", async (e) => {
    const del = e.target.closest("button[data-del-lot]");
    const view = e.target.closest("button[data-view]");
    const score = e.target.closest("button[data-score]");
    if (del && confirm("Delete this lot from your holdings?")) {
      Holdings.save(Holdings.load().filter((l) => l.id !== del.dataset.delLot));
      render();
    } else if (view) {
      setTab(view.dataset.view, view.dataset.ticker);
      document.querySelector("#list details.company")?.setAttribute("open", "");
    } else if (score) {
      setHoldingsStatus(`Adding ${score.dataset.score} to your watchlist…`);
      await addTicker(score.dataset.score);
      const msg = document.getElementById("editor-status");
      setHoldingsStatus(msg.textContent, msg.className.includes("err") ? "err" : "ok");
      render();
    }
  });
  document.getElementById("filters").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-filter]");
    if (b) { state.filter = b.dataset.filter; render(); }
  });
  document.getElementById("search").addEventListener("input", (e) => { state.query = e.target.value.trim(); render(); });
  document.getElementById("shuffle").addEventListener("click", () => { shuffleSample(); state.filter = "all"; render(); });

  document.getElementById("repo-name").textContent = GitHubWatchlist.repo;
  document.getElementById("file-link").href = GitHubWatchlist.fileUrl;
  document.getElementById("connect-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("token");
    if (!input.value.trim()) return;
    setBusy(true);
    setStatus("Checking the token with GitHub…");
    try {
      await GitHubWatchlist.connect(input.value.trim());
      input.value = "";
      setStatus("Connected. You can now add and remove companies.", "ok");
      render();
    } catch (err) {
      setStatus(err.message, "err");
    } finally {
      setBusy(false);
    }
  });
  document.getElementById("disconnect").addEventListener("click", () => {
    GitHubWatchlist.disconnect();
    setStatus("Disconnected. The token was removed from this browser (you can also delete it on GitHub).");
    render();
  });
  document.getElementById("add-form").addEventListener("submit", (e) => {
    e.preventDefault();
    addTicker(document.getElementById("add-ticker").value);
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-remove]");
    if (b) removeTicker(b.dataset.remove);
  });
}

// The query string sidesteps GitHub Pages' ~10-minute CDN cache, so a reopened page sees the latest data.
const getJSON = (url) => fetch(`${url}?t=${Date.now()}`, { cache: "no-store" })
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });

Promise.all([getJSON("companies.json"), getJSON("discovery.json").catch(() => null)])
  .then(([data, discovery]) => {
    bindEvents();
    const { open } = applyData(data, discovery);
    // Links from the BUY/SELL alert: companies.html?tab=watchlist&q=NFLX
    const params = new URLSearchParams(location.search);
    if (params.get("tab") in INTRO) {
      const ticker = (params.get("q") || "").toUpperCase();
      setTab(params.get("tab"), params.get("tab") === "holdings" ? "" : ticker);
      const match = [...document.querySelectorAll("#list details, #holdings-list details")]
        .find((d) => !d.closest("[hidden]") && d.querySelector(".ticker")?.textContent === ticker);
      if (match) {
        match.open = true;
        match.scrollIntoView({ block: "start" });
      }
    }
    if (open.length) {
      setStatus(`Still updating ${open.map((p) => p.ticker).join(", ")}. This page refreshes by itself when the results are ready.`);
      waitForRescore();
    }
  })
  .catch(() => {
    document.getElementById("list").innerHTML =
      `<p>No data yet. Run the “Update market data” GitHub Action to generate <code>companies.json</code>.</p>`;
  });
