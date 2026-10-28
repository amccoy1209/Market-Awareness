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
      ${ipo}
      ${(c.notes || []).map((n) => `<p class="note">${esc(n)}</p>`).join("")}
      <div class="facts">
        <span>Intrinsic value: <strong>${money(val.intrinsic_value)}</strong>/share</span>
        <span>P/E: ${val.pe ?? "—"}</span>
        <span>Owner-earnings yield: ${pct(val.owner_earnings_yield, 2)}${val.treasury_yield != null ? ` vs ${val.treasury_yield}% Treasury` : ""}</span>
        <span>Growth assumed: ${pct(val.growth_used)}</span>
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
  document.getElementById("updated").textContent = `Last checked ${new Date(data.generated_at).toLocaleString()}.`
    + (data.errors.length ? ` ${data.errors.length} item(s) couldn't be loaded: ${data.errors.map((e) => e.ticker).join(", ")}.` : "");
  const pending = applyPendingEdits();
  render();
  return pending;
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
    if (open.length) {
      setStatus(`Still updating ${open.map((p) => p.ticker).join(", ")}. This page refreshes by itself when the results are ready.`);
      waitForRescore();
    }
  })
  .catch(() => {
    document.getElementById("list").innerHTML =
      `<p>No data yet. Run the “Update market data” GitHub Action to generate <code>companies.json</code>.</p>`;
  });
