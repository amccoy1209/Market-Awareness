"""Fetch indicator data and release dates from FRED, score them, and write docs/data.json.

Usage:
    FRED_API_KEY=your_key python scripts/fetch_data.py

Get a free API key at https://fred.stlouisfed.org/docs/api/api_key.html
Uses only the Python standard library.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from indicators import (CATEGORIES, INDICATORS, category_status, classify, compute_metric,
                        downsample, is_stale, overall_verdict, threshold_text)

API = "https://api.stlouisfed.org/fred"
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "data.json"
HISTORY_YEARS = 6
CALENDAR_DAYS = 45


def fred(endpoint, **params):
    params.update(api_key=os.environ["FRED_API_KEY"], file_type="json")
    url = f"{API}/{endpoint}?{urllib.parse.urlencode(params)}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError) as err:
            if attempt == 3 or (isinstance(err, urllib.error.HTTPError) and err.code < 500 and err.code != 429):
                raise
            time.sleep(2 ** (attempt + 1))


def observations(series_id, start):
    data = fred("series/observations", series_id=series_id, observation_start=start.isoformat())
    obs = []
    for o in data["observations"]:
        if o["value"] != ".":
            obs.append((date.fromisoformat(o["date"]), float(o["value"])))
    return obs


def series_info(series_id):
    return fred("series", series_id=series_id)["seriess"][0]


def release_for(series_id):
    return fred("series/release", series_id=series_id)["releases"][0]


def upcoming_dates(release_id, today):
    data = fred("release/dates", release_id=release_id, realtime_start=today.isoformat(),
                realtime_end=(today + timedelta(days=365)).isoformat(),
                include_release_dates_with_no_data="true", sort_order="asc", limit=10)
    return [d["date"] for d in data["release_dates"]]


def main():
    if not os.environ.get("FRED_API_KEY"):
        sys.exit("Set the FRED_API_KEY environment variable (free key: "
                 "https://fred.stlouisfed.org/docs/api/api_key.html)")

    today = date.today()
    start = today.replace(year=today.year - HISTORY_YEARS)
    cache, releases, results, errors = {}, {}, [], []

    def get_obs(series_id):
        if series_id not in cache:
            cache[series_id] = observations(series_id, start)
        return cache[series_id]

    for ind in INDICATORS:
        try:
            obs = get_obs(ind.series)
            compare = get_obs(ind.compare_series) if ind.compare_series else None
            value = compute_metric(ind, obs, compare)
            info = series_info(ind.series)
            rel = release_for(ind.series)
            if rel["id"] not in releases:
                releases[rel["id"]] = {"id": rel["id"], "name": rel["name"],
                                       "link": rel.get("link"),
                                       "dates": upcoming_dates(rel["id"], today), "indicators": []}
            releases[rel["id"]]["indicators"].append(ind.name)
            latest_date = obs[-1][0] if obs else None
            next_dates = releases[rel["id"]]["dates"]
            results.append({
                "id": ind.id, "name": ind.name, "category": ind.category,
                "series": ind.series, "series_title": info["title"],
                "frequency": info["frequency"], "units": info["units"],
                "metric": ind.metric, "unit": ind.unit,
                "value": None if value is None else round(value, 3),
                "latest_level": obs[-1][1] if obs else None,
                "status": classify(ind, value),
                "as_of": latest_date.isoformat() if latest_date else None,
                "stale": bool(latest_date and is_stale(ind, latest_date, today)),
                "last_updated": info["last_updated"],
                "next_release": next_dates[0] if next_dates else None,
                "release_name": rel["name"],
                "thresholds": threshold_text(ind),
                "why": ind.why,
                "source_url": f"https://fred.stlouisfed.org/series/{ind.series}",
                "history": [[d.isoformat(), v] for d, v in downsample(obs)],
            })
        except Exception as err:  # keep going so one bad series doesn't break the dashboard
            print(f"!! {ind.id} ({ind.series}): {err}", file=sys.stderr)
            errors.append({"indicator": ind.name, "series": ind.series, "error": str(err)})
            results.append({"id": ind.id, "name": ind.name, "category": ind.category,
                            "series": ind.series, "status": None, "error": str(err),
                            "why": ind.why, "thresholds": threshold_text(ind),
                            "source_url": f"https://fred.stlouisfed.org/series/{ind.series}"})

    categories = []
    for cat_id, title, question in CATEGORIES:
        members = [r for r in results if r["category"] == cat_id]
        categories.append({"id": cat_id, "title": title, "question": question,
                           "status": category_status([r["status"] for r in members]),
                           "indicators": members})

    horizon = (today + timedelta(days=CALENDAR_DAYS)).isoformat()
    calendar = sorted(
        ({"date": d, "release": r["name"], "link": r["link"], "indicators": r["indicators"]}
         for r in releases.values() for d in r["dates"] if d <= horizon),
        key=lambda e: e["date"])

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdict": overall_verdict([c["status"] for c in categories]),
        "categories": categories,
        "calendar": calendar,
        "errors": errors,
    }
    OUTPUT.write_text(json.dumps(output, indent=1))
    print(f"Wrote {OUTPUT} — verdict: {output['verdict']['title']} "
          f"({len(results) - len(errors)}/{len(results)} indicators OK)")
    if len(errors) == len(results):
        sys.exit("Every indicator failed; check the API key and network.")


if __name__ == "__main__":
    main()
