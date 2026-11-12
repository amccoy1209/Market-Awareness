// "My holdings": positions are stored only in this browser (localStorage). They are never uploaded and never
// written to the repository, which is public. Each position is judged with the same checklist data as the other tabs.

const Holdings = (() => {
  const KEY = "market-awareness-holdings";
  const SALES_KEY = "market-awareness-sales";

  const STANCES = {
    add: { label: "Buy-more zone", cls: "green",
      text: "A quality business trading below its buy-below price. Buffett would be comfortable adding here." },
    hold: { label: "Hold", cls: "green",
      text: "A quality business at or below its estimated value: the classic case for simply holding." },
    hold_no_add: { label: "Hold, don't add", cls: "yellow",
      text: "A quality business priced above its estimated value. Buffett and Munger would usually keep holding a great business like this, but not buy more at this price." },
    trim: { label: "Consider trimming", cls: "red",
      text: "Priced at more than twice its estimated value and at 40+ times earnings. Extreme overvaluation is one of the few reasons Buffett has trimmed a great business (he regretted not selling Coca-Cola at about 50× earnings in 1998)." },
    review: { label: "Review your thesis", cls: "red",
      text: "The business doesn't meet the checklist. Buffett sells when the business, not the price, has gone wrong, or when he realizes he misjudged it. Check whether your original reasons for owning it still hold." },
    early: { label: "Too early to judge", cls: "gray",
      text: "Fewer than 3 years of annual results. Buffett waits for a long track record before trusting a business." },
    unknown: { label: "Not scored yet", cls: "gray",
      text: "There's no checklist data for this ticker yet. Add it to your watchlist to have it scored." },
  };

  // --- Storage -------------------------------------------------------------------

  function load() {
    try {
      const lots = JSON.parse(localStorage.getItem(KEY));
      return Array.isArray(lots) ? lots.filter(valid) : [];
    } catch {
      return [];
    }
  }

  function save(lots) {
    try { localStorage.setItem(KEY, JSON.stringify(lots)); return true; } catch { return false; }
  }

  const valid = (l) => l && typeof l.ticker === "string" && /^[A-Z][A-Z0-9.-]{0,9}$/.test(l.ticker)
    && Number.isFinite(l.shares) && l.shares > 0 && Number.isFinite(l.price) && l.price >= 0
    && (!l.date || /^\d{4}-\d{2}-\d{2}$/.test(l.date));

  function loadSales() {
    try {
      const sales = JSON.parse(localStorage.getItem(SALES_KEY));
      return Array.isArray(sales) ? sales.filter(validSale) : [];
    } catch {
      return [];
    }
  }

  function saveSales(sales) {
    try { localStorage.setItem(SALES_KEY, JSON.stringify(sales)); return true; } catch { return false; }
  }

  const validSale = (s) => s && typeof s.ticker === "string" && Number.isFinite(s.shares) && s.shares > 0
    && Number.isFinite(s.price) && s.price >= 0 && /^\d{4}-\d{2}-\d{2}$/.test(s.date || "") && Array.isArray(s.parts);

  // --- Sales (pure) ------------------------------------------------------------------

  const EPSILON = 1e-9;
  const newId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  /** "long" if held more than a year by `soldOn`, "short" if not, "unknown" without a purchase date. */
  function term(boughtOn, soldOn) {
    if (!boughtOn) return "unknown";
    const anniversary = new Date(`${boughtOn}T12:00:00`);
    anniversary.setFullYear(anniversary.getFullYear() + 1);
    return new Date(`${soldOn}T12:00:00`) > anniversary ? "long" : "short";
  }

  /**
   * Sell `shares` of `ticker` at `price` on `date`, taking shares from the oldest purchases first (FIFO, the IRS
   * default). Purchases without a date count as the oldest. Returns { lots, sale } or { error }.
   */
  function sell(lots, ticker, shares, price, date) {
    if (!(shares > 0) || !(price >= 0) || !/^\d{4}-\d{2}-\d{2}$/.test(date || "")) {
      return { error: "Enter the number of shares sold (above 0), the price per share and the date." };
    }
    const own = lots.filter((l) => l.ticker === ticker)
      .sort((a, b) => (a.date || "0000").localeCompare(b.date || "0000"));
    const held = own.reduce((sum, l) => sum + l.shares, 0);
    if (shares > held + EPSILON) return { error: `You only hold ${held.toLocaleString()} shares of ${ticker}.` };
    if (own.some((l) => l.date && l.date > date)) {
      const later = own.filter((l) => l.date && l.date > date);
      if (later.reduce((sum, l) => sum + l.shares, 0) > held - shares + EPSILON) {
        return { error: "The sale date is before some of the shares were bought. Check the date." };
      }
    }
    let left = shares;
    const parts = [];
    const remaining = new Map(lots.map((l) => [l.id, l.shares]));
    for (const lot of own) {
      if (left <= EPSILON) break;
      const take = Math.min(lot.shares, left);
      left -= take;
      remaining.set(lot.id, lot.shares - take);
      parts.push({ lotId: lot.id, shares: take, cost: lot.price, bought: lot.date || null, term: term(lot.date, date),
        gain: (price - lot.price) * take });
    }
    const cost = parts.reduce((sum, p) => sum + p.cost * p.shares, 0);
    const sale = { id: newId(), ticker, shares, price, date, proceeds: shares * price, cost,
      gain: shares * price - cost, parts };
    const updated = lots.map((l) => ({ ...l, shares: remaining.get(l.id) })).filter((l) => l.shares > EPSILON);
    return { lots: updated, sale };
  }

  /** Put a recorded sale's shares back into the purchases they came from. */
  function undoSale(lots, sale) {
    const restored = lots.map((l) => ({ ...l }));
    for (const part of sale.parts) {
      const lot = restored.find((l) => l.id === part.lotId);
      if (lot) lot.shares += part.shares;
      else restored.push({ id: part.lotId, ticker: sale.ticker, shares: part.shares, price: part.cost, date: part.bought });
    }
    return restored;
  }

  /** Realized gains for one calendar year, split by holding period. */
  function realized(sales, year) {
    const totals = { short: 0, long: 0, unknown: 0, total: 0, count: 0 };
    for (const s of sales) {
      if (!s.date.startsWith(String(year))) continue;
      totals.count++;
      for (const p of s.parts) {
        totals[p.term] += p.gain;
        totals.total += p.gain;
      }
    }
    return totals;
  }

  // --- Analysis (pure) -------------------------------------------------------------

  /** Group lots by ticker and value them at the latest checklist price (or cost when no price is known). */
  function positions(lots, findCompany) {
    const byTicker = new Map();
    for (const lot of lots) {
      if (!byTicker.has(lot.ticker)) byTicker.set(lot.ticker, { ticker: lot.ticker, lots: [], shares: 0, cost: 0 });
      const p = byTicker.get(lot.ticker);
      p.lots.push(lot);
      p.shares += lot.shares;
      p.cost += lot.shares * lot.price;
    }
    const list = [...byTicker.values()];
    for (const p of list) {
      p.company = findCompany(p.ticker);
      p.price = p.company && !p.company.pending ? p.company.price : null;
      p.value = p.price != null ? p.shares * p.price : null;
      p.gain = p.value != null ? p.value - p.cost : null;
    }
    const total = list.reduce((sum, p) => sum + (p.value ?? p.cost), 0);
    for (const p of list) p.weight = total ? ((p.value ?? p.cost) / total) * 100 : 0;
    return list;
  }

  function stanceFor(c) {
    if (!c || c.pending) return "unknown";
    if (c.verdict === "too_early" || c.verdict === "no_data") return "early";
    if (c.verdict === "avoid") return "review";
    const val = c.valuation || {};
    if (!c.price || !val.intrinsic_value) return "hold";
    if (val.buy_below && c.price <= val.buy_below) return "add";
    const ratio = c.price / val.intrinsic_value;
    if (ratio <= 1) return "hold";
    // The value estimate is conservative, so only call for trimming when the earnings multiple is extreme too.
    return ratio > 2 && (val.pe ?? 0) >= 40 ? "trim" : "hold_no_add";
  }

  const money = (v) => (v == null ? "—" : `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
  const addYear = (iso) => { const d = new Date(`${iso}T12:00:00`); d.setFullYear(d.getFullYear() + 1); return d; };
  const fmt = (d) => d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

  /** Plain-language points for one position: business, price, size, taxes and alternatives. */
  function analyze(p, ctx) {
    const c = p.company;
    const stance = stanceFor(c);
    const points = [];
    if (c && !c.pending && c.scored) {
      const fails = (c.checks || []).filter((k) => k.status === "fail").map((k) => k.title.toLowerCase());
      points.push({
        kind: c.verdict === "avoid" ? "bad" : "good",
        text: `The business passes ${c.passed} of ${c.scored} checks${fails.length ? `; it misses on ${fails.join(", ")}` : ""}.`,
      });
    }
    const val = (c && c.valuation) || {};
    if (p.price && val.intrinsic_value) {
      const diff = (p.price / val.intrinsic_value - 1) * 100;
      const where = Math.abs(diff) < 2 ? "about equal to" : `${Math.abs(diff).toFixed(0)}% ${diff > 0 ? "above" : "below"}`;
      points.push({
        kind: diff > 100 ? "bad" : diff > 2 ? "warn" : "good",
        text: `Price ${money(p.price)} is ${where} the estimated value of ${money(val.intrinsic_value)} (buy-below ${money(val.buy_below)}).`
          + (diff > 100 ? " The estimate is conservative for slow growers, so treat a big gap as \"expensive\", not as a precise number." : ""),
      });
    }
    if (val.implied_roe != null && val.roe_used != null) {
      const gap = val.implied_roe - val.roe_used;
      points.push({ kind: gap > 2 ? "warn" : "good",
        text: `At ${val.price_to_book}× book value, today's price assumes a sustained ${val.implied_roe}% return on equity, against a median of ${val.roe_used}% recently`
          + (gap > 2 ? ": the market expects better returns than the company has delivered." : ": a reasonable bar given its record.") });
    }
    if (val.implied_growth != null && val.growth_used != null) {
      const gap = val.implied_growth - val.growth_used;
      points.push({ kind: gap > 3 ? "warn" : "good",
        text: `Today's price assumes ${val.implied_growth}% growth a year for 10 years, against ${val.growth_used}% in the past`
          + (gap > 3 ? ": the market expects a better future than the company's history." : ": a reasonable bar given its record.") });
    }
    if (val.owner_earnings_yield != null && ctx.treasury != null && val.owner_earnings_yield < ctx.treasury) {
      points.push({ kind: "warn",
        text: `It yields ${val.owner_earnings_yield}% in owner earnings, less than the ${ctx.treasury}% on 10-year Treasuries, so you're paying for growth that still has to arrive.` });
    }
    if (p.weight > 40) {
      points.push({ kind: "bad", text: `It's ${p.weight.toFixed(0)}% of your holdings. Buffett concentrates, but only in businesses he understands deeply; trimming for size is reasonable if you're less sure.` });
    } else if (p.weight > 25) {
      points.push({ kind: "warn", text: `It's ${p.weight.toFixed(0)}% of your holdings: a large bet, so be sure you understand it well.` });
    }
    for (const lot of p.lots) {
      const gain = p.price != null ? (p.price - lot.price) * lot.shares : null;
      const when = lot.date ? `bought ${fmt(new Date(`${lot.date}T12:00:00`))}` : "with no purchase date";
      if (gain != null && gain < 0) {
        points.push({ kind: "info", text: `Your lot ${when} is down ${money(-gain)}. In the US, selling at a loss can offset other gains, but rebuying within 30 days cancels the deduction (the wash-sale rule).` });
      } else if (gain != null && gain > 0 && lot.date && addYear(lot.date) > ctx.today) {
        points.push({ kind: "info", text: `Your lot ${when} is up ${money(gain)} but held under a year. Selling before ${fmt(addYear(lot.date))} would be taxed as a short-term gain in the US.` });
      }
    }
    if (stance === "review" || stance === "trim" || stance === "early") {
      const others = ctx.buyCandidates.filter((t) => t !== p.ticker);
      points.push({ kind: "info", text: others.length
        ? `Buy candidates in your lists right now: ${others.slice(0, 8).join(", ")}${others.length > 8 ? "…" : ""}.`
        : "None of your lists has a buy candidate right now. Buffett is happy to hold cash while he waits for one." });
    }
    return { stance, ...STANCES[stance], points };
  }

  return { load, save, valid, loadSales, saveSales, validSale, sell, undoSale, realized, term, positions, analyze, stanceFor, STANCES, money };
})();
