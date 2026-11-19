#!/usr/bin/env python3
"""Refresh data/contributions.json and data/repos.json (standard library only).

Contributions: GitHub's GraphQL contribution calendar when a token is available
(GITHUB_TOKEN in Actions), otherwise the public calendar page that the profile
itself renders. Repos: the REST API for the featured repos in profile.json.

Usage:  python scripts/fetch_contributions.py            (user from profile.json)
        GH_USER=someone python scripts/fetch_contributions.py
        python scripts/fetch_contributions.py --parse saved.html   (test the HTML parser)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}


def request(url, data=None, headers=None):
    h = {"User-Agent": "readme-cards", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def api_headers():
    h = {"Accept": "application/vnd.github+json"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h


# ---------------------------------------------------------------- GraphQL
def via_graphql(user):
    q = """query($login:String!){user(login:$login){contributionsCollection{contributionCalendar{
           totalContributions weeks{contributionDays{date contributionCount contributionLevel}}}}}}"""
    body = json.dumps({"query": q, "variables": {"login": user}}).encode()
    res = json.loads(request("https://api.github.com/graphql", body, api_headers()))
    if res.get("errors"):
        raise RuntimeError(res["errors"])
    cal = res["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    days = [{"date": d["date"], "count": d["contributionCount"], "level": LEVELS.get(d["contributionLevel"], 0)}
            for w in cal["weeks"] for d in w["contributionDays"]]
    return days, "graphql"


# ---------------------------------------------------------------- HTML page
class CalendarParser(HTMLParser):
    """Pull date/level from each <td class="ContributionCalendar-day"> and the count
    from the <tool-tip for="..."> that labels it ("3 contributions on ...")."""

    def __init__(self):
        super().__init__()
        self.cells, self.tips, self._tip = {}, {}, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "td" and "ContributionCalendar-day" in (a.get("class") or "") and a.get("data-date"):
            self.cells[a.get("id")] = (a["data-date"], int(a.get("data-level") or 0))
        elif tag == "tool-tip" and a.get("for"):
            self._tip, self.tips[a["for"]] = a["for"], ""

    def handle_data(self, data):
        if self._tip:
            self.tips[self._tip] += data

    def handle_endtag(self, tag):
        if tag == "tool-tip":
            self._tip = None


def parse_calendar(html):
    p = CalendarParser()
    p.feed(html)
    days = []
    for cid, (date, level) in p.cells.items():
        m = re.match(r"\s*([\d,]+)\s+contribution", p.tips.get(cid, ""))
        days.append({"date": date, "count": int(m.group(1).replace(",", "")) if m else 0, "level": level})
    return sorted(days, key=lambda d: d["date"])


def via_html(user):
    html = request(f"https://github.com/users/{user}/contributions")
    days = parse_calendar(html)
    if not days:
        raise RuntimeError("calendar markup not found")
    return days, "html"


# ---------------------------------------------------------------- repos
def fetch_repos(user, featured):
    out = []
    for name in featured:
        r = json.loads(request(f"https://api.github.com/repos/{user}/{name}", headers=api_headers()))
        out.append({"name": r["name"], "description": r.get("description"), "language": r.get("language"),
                    "stars": r.get("stargazers_count", 0), "forks": r.get("forks_count", 0),
                    "pushed_at": r.get("pushed_at"), "fork": r.get("fork", False)})
    public = 0
    page = 1
    while True:
        batch = json.loads(request(f"https://api.github.com/users/{user}/repos?per_page=100&type=owner&page={page}",
                                   headers=api_headers()))
        public += sum(1 for r in batch if not r.get("fork") and not r.get("private"))
        if len(batch) < 100:
            break
        page += 1
    return {"public_repos": public, "repos": out}


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--parse":
        days = parse_calendar(Path(sys.argv[2]).read_text(encoding="utf-8"))
        print(json.dumps({"days": len(days), "total": sum(d["count"] for d in days)}))
        return
    cfg = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
    user = os.environ.get("GH_USER") or cfg["user"]
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    days = source = None
    for fn in ((via_graphql, via_html) if TOKEN else (via_html,)):
        try:
            days, source = fn(user)
            break
        except Exception as e:  # keep going: the other source may work
            print(f"{fn.__name__} failed: {e}", file=sys.stderr)
    if days:
        today = dt.date.today().isoformat()
        days = [d for d in days if d["date"] <= today]
        (ROOT / "data").mkdir(exist_ok=True)
        (ROOT / "data/contributions.json").write_text(json.dumps(
            {"user": user, "updated": now, "source": source, "total": sum(d["count"] for d in days), "days": days},
            indent=1), encoding="utf-8")
        print(f"contributions: {len(days)} days, {sum(d['count'] for d in days)} total ({source})")
    else:
        print("contributions: kept the previous data", file=sys.stderr)

    try:
        repos = fetch_repos(user, cfg.get("featured", []))
        repos["updated"] = now
        (ROOT / "data/repos.json").write_text(json.dumps(repos, indent=1), encoding="utf-8")
        print(f"repos: {len(repos['repos'])} featured, {repos['public_repos']} public")
    except Exception as e:
        print(f"repos: kept the previous data ({e})", file=sys.stderr)


if __name__ == "__main__":
    main()
