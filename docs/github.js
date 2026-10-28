// Edits watchlist.txt in this repository through the GitHub API and starts a quick rescore.
// The access token is kept only in this browser (localStorage) and is only ever sent to api.github.com.

const GitHubWatchlist = (() => {
  // Work out owner/repo from the GitHub Pages address (owner.github.io/repo/), falling back to this project.
  const pagesOwner = location.hostname.endsWith(".github.io") ? location.hostname.split(".")[0] : null;
  const firstSegment = location.pathname.split("/").filter(Boolean)[0];
  const owner = pagesOwner || "amccoy1209";
  const repo = pagesOwner && firstSegment && !firstSegment.endsWith(".html") ? firstSegment : "Market-Awareness";
  const BRANCH = "main", FILE = "watchlist.txt", WORKFLOW = "update-data.yml", KEY = "market-awareness-github-token";

  const token = {
    get() { try { return localStorage.getItem(KEY); } catch { return null; } },
    set(v) { try { localStorage.setItem(KEY, v); return true; } catch { return false; } },
    clear() { try { localStorage.removeItem(KEY); } catch { /* storage blocked */ } },
  };

  async function api(path, options = {}) {
    const res = await fetch(`https://api.github.com/repos/${owner}/${repo}${path}`, {
      ...options,
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token.get()}`,
        "X-GitHub-Api-Version": "2022-11-28",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
      },
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).message || detail; } catch { /* not JSON */ }
      const err = new Error(
        res.status === 401 ? "GitHub rejected the token. It may have expired; disconnect and connect a new one."
          : res.status === 403 || res.status === 404
            ? `The token doesn't have access (${detail}). It needs Contents and Actions read & write on ${repo}.`
            : `GitHub error ${res.status}: ${detail}`);
      err.status = res.status;
      throw err;
    }
    return res.status === 204 ? null : res.json();
  }

  const decode = (b64) => new TextDecoder().decode(Uint8Array.from(atob(b64.replace(/\s/g, "")), (c) => c.charCodeAt(0)));
  const encode = (text) => {
    let binary = "";
    for (const byte of new TextEncoder().encode(text)) binary += String.fromCharCode(byte);
    return btoa(binary);
  };
  const tickerOf = (line) => line.split("#")[0].trim().toUpperCase();

  async function readList() {
    const file = await api(`/contents/${FILE}?ref=${BRANCH}`);
    return { text: decode(file.content), sha: file.sha };
  }

  /** Apply `change` to watchlist.txt, commit it, then start a watchlist-only rescore. False if nothing changed. */
  async function editList(change, message) {
    const { text, sha } = await readList();
    const next = change(text);
    if (next === text) return false;
    await api(`/contents/${FILE}`, {
      method: "PUT",
      body: JSON.stringify({ message, content: encode(next), sha, branch: BRANCH }),
    });
    await api(`/actions/workflows/${WORKFLOW}/dispatches`, {
      method: "POST",
      body: JSON.stringify({ ref: BRANCH, inputs: { watchlist_only: "true" } }),
    });
    return true;
  }

  return {
    owner, repo,
    actionsUrl: `https://github.com/${owner}/${repo}/actions/workflows/${WORKFLOW}`,
    fileUrl: `https://github.com/${owner}/${repo}/blob/${BRANCH}/${FILE}`,
    connected: () => Boolean(token.get()),
    async connect(value) {
      if (!token.set(value)) throw new Error("This browser is blocking storage, so the token can't be saved.");
      try {
        await readList();
      } catch (err) {
        token.clear();
        throw err;
      }
    },
    disconnect: token.clear,
    add(ticker) {
      const today = new Date().toISOString().slice(0, 10);
      return editList(
        (text) => (text.split("\n").some((l) => tickerOf(l) === ticker) ? text
          : `${text.replace(/\n*$/, "\n")}${ticker.padEnd(8)}# added from the app ${today}\n`),
        `Add ${ticker} to watchlist`);
    },
    remove(ticker) {
      return editList((text) => text.split("\n").filter((l) => tickerOf(l) !== ticker).join("\n"),
        `Remove ${ticker} from watchlist`);
    },
  };
})();
