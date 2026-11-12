// Opening alert shown on both pages: BUY (green) for companies the checklist formula marks as buy candidates,
// SELL (red) for holdings whose business no longer passes the checklist or whose price has become extreme.
// Holdings come from this browser only (see holdings.js).

const Alerts = (() => {
  // Dismissed notices, by "buy:TICKER" / "sell:TICKER". A dismissal lasts while that signal does: once the signal
  // goes away it's forgotten, so the notice shows again if the signal comes back.
  const DISMISSED_KEY = "market-awareness-dismissed-signals";
  const OLD_KEY = "market-awareness-dismissed-alerts";  // whole-banner dismissal from the first version
  const TAB_FOR = { watchlist: "watchlist", ipo: "ipos", discovery: "discover" };

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /** Every current BUY and SELL signal, BUYs first. */
  function signals(companies, discovery) {
    const pool = (discovery && discovery.candidates) || [];
    const lists = [companies.watchlist, companies.ipos, pool];
    const find = (t) => lists.map((l) => l.find((c) => c.ticker === t)).find(Boolean);
    const lots = Holdings.load();
    const owned = new Set(lots.map((l) => l.ticker));
    const { money } = Holdings;

    const out = [], seen = new Set();
    for (const c of lists.flat()) {
      if (c.verdict !== "buy" || seen.has(c.ticker)) continue;
      seen.add(c.ticker);
      out.push({ type: "buy", ticker: c.ticker, name: c.name, tab: TAB_FOR[c.kind] || "watchlist",
        text: `${money(c.price)}, below its buy-below price of ${money(c.valuation.buy_below)}`
          + (owned.has(c.ticker) ? ". You own it." : "."),
        news: newsSummary(c.news_check) });
    }
    for (const p of Holdings.positions(lots, find)) {
      const stance = Holdings.stanceFor(p.company);
      const c = p.company;
      if (stance === "review") {
        out.push({ type: "sell", ticker: p.ticker, name: c.name, tab: "holdings",
          text: `The business no longer meets the checklist (passes ${c.passed} of ${c.scored} checks). Review why you own it.` });
      } else if (stance === "trim") {
        out.push({ type: "sell", ticker: p.ticker, name: c.name, tab: "holdings",
          text: `Priced at ${(c.price / c.valuation.intrinsic_value).toFixed(1)}× its estimated value and ${c.valuation.pe}× earnings. Consider trimming.` });
      }
    }
    return out;
  }

  /** One line summarizing the news check for a BUY: the worst flag, or an all-clear. */
  function newsSummary(check) {
    if (!check) return null;
    const flags = check.flags || [];
    const headlines = (check.headlines || []).length;
    const more = flags.length > 1 ? ` (+${flags.length - 1} more)` : "";
    if (flags.length) {
      return { level: flags[0].level, text: `News check: ${flags[0].text}${more}` };
    }
    return { level: "ok", text: `News check: no warning signs in recent SEC filings or the price trend${headlines ? `; ${headlines} recent headlines to skim` : ""}.` };
  }

  const keyOf = (s) => `${s.type}:${s.ticker}`;

  function loadDismissed() {
    try {
      localStorage.removeItem(OLD_KEY);
      const saved = JSON.parse(localStorage.getItem(DISMISSED_KEY));
      return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
    } catch {
      return {};
    }
  }

  function saveDismissed(map) {
    try { localStorage.setItem(DISMISSED_KEY, JSON.stringify(map)); } catch { /* storage blocked */ }
  }

  /** Render the notices that haven't been dismissed into #alerts. */
  function show(companies, discovery) {
    const el = document.getElementById("alerts");
    if (!el) return;
    const list = signals(companies, discovery);
    const current = new Set(list.map(keyOf));
    const dismissed = loadDismissed();
    for (const key of Object.keys(dismissed)) if (!current.has(key)) delete dismissed[key];
    saveDismissed(dismissed);

    const visible = list.filter((s) => !dismissed[keyOf(s)]);
    const hiddenCount = list.length - visible.length;
    if (!list.length) {
      el.hidden = true;
      el.innerHTML = "";
      return;
    }
    el.hidden = false;
    el.innerHTML = `
      ${visible.length ? `<ul>${visible.map((s) => `
        <li class="alert-item ${s.type}">
          <a href="companies.html?tab=${s.tab}&amp;q=${encodeURIComponent(s.ticker)}">
            <span class="alert-badge">${s.type === "buy" ? "BUY" : "SELL"}</span>
            <span><strong>${esc(s.ticker)}</strong> <span class="muted">${esc(s.name)}</span><br>${esc(s.text)}
              ${s.news ? `<span class="alert-news ${s.news.level}">${s.news.level === "ok" ? "✓" : "⚠"} ${esc(s.news.text)}</span>` : ""}</span>
          </a>
          <button type="button" class="alert-dismiss" data-dismiss="${esc(keyOf(s))}"
                  aria-label="Dismiss the ${s.type === "buy" ? "BUY" : "SELL"} notice for ${esc(s.ticker)}" title="Dismiss">✕</button>
        </li>`).join("")}
      </ul>` : ""}
      <p class="small muted">${visible.length ? "Signals from the checklist formula, not financial advice." : ""}
        ${visible.length > 1 ? `<button type="button" class="linklike" data-dismiss-all>Dismiss all</button>` : ""}
        ${hiddenCount ? `<button type="button" class="linklike" data-restore>Show ${hiddenCount} dismissed notice${hiddenCount === 1 ? "" : "s"}</button>` : ""}</p>`;
    el.onclick = (e) => {
      const one = e.target.closest("[data-dismiss]");
      if (one) dismissed[one.dataset.dismiss] = true;
      else if (e.target.closest("[data-dismiss-all]")) visible.forEach((s) => { dismissed[keyOf(s)] = true; });
      else if (e.target.closest("[data-restore]")) Object.keys(dismissed).forEach((k) => delete dismissed[k]);
      else return;
      saveDismissed(dismissed);
      show(companies, discovery);
    };
  }

  /** For pages that don't already load the company data. */
  async function load() {
    const get = (url) => fetch(`${url}?t=${Date.now()}`, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null));
    try {
      const [companies, discovery] = await Promise.all([get("companies.json"), get("discovery.json").catch(() => null)]);
      if (companies) show(companies, discovery);
    } catch { /* no company data yet */ }
  }

  return { signals, show, load };
})();
