"""Apply a Google Scholar snapshot to index.html.

Input: a JSON file read from the owner's Scholar profile page, shaped as
    {"date": "2026-11-07",
     "metrics": [cit_all, cit_2021, h_all, h_2021, i10_all, i10_2021],
     "hist": [[year, citations], ...],
     "rows": [{"t": title, "a": authors, "v": venue_with_year, "c": "123", "y": "2024"}, ...]}

What it changes in index.html:
  * the citation-metrics table, the citations-per-year chart and the dates;
  * the citation count of every listed paper that matches a Scholar row;
  * adds papers that are on Scholar but not yet on the site, except duplicates,
    notices (expression of concern, erratum, correction) and titles listed in
    data/exclude.json.
It never removes or renames a paper that is already on the site.

Safety checks (the script exits with an error and writes nothing if one fails):
  * six metrics are positive integers, all-time >= since-2021, h <= i10 <= papers on Scholar;
  * the number of papers on the site does not decrease;
  * the summed citations of papers already on the site do not drop by more than 5 %.

Usage:
    python scripts/apply_scholar.py snapshot.json            # update index.html
    python scripts/apply_scholar.py snapshot.json --dry-run  # report only
"""
import argparse
import difflib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTICE = re.compile(r"expression of concern|erratum|author correction|corrigendum|retraction", re.I)
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def same_paper(scholar_title: str, site_key: str) -> bool:
    """True when a Scholar title and a site title are the same paper.

    Scholar cuts long titles with '…' and sometimes appends text (': M. Dang et al.');
    the site keeps the clean title. So a long common prefix counts as a match, and
    otherwise only tiny wording differences (ratio >= 0.95) are allowed.
    """
    k = norm(scholar_title.strip().rstrip(".… \u00a0"))
    if not k:
        return False
    if k == site_key:
        return True
    short, long_ = sorted((k, site_key), key=len)
    if len(short) >= 40 and long_.startswith(short):
        return True
    return difflib.SequenceMatcher(None, k, site_key).ratio() >= 0.95


def split_P(html: str):
    start = html.index("const P=[") + len("const P=")
    end = html.index("];", start) + 1
    rows = json.loads(html[start:end])
    return rows, start, end


def fmt_rows(rows) -> str:
    return "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n]"


def clean_venue(v: str, year: str) -> str:
    v = (v or "").strip()
    return re.sub(r",\s*" + re.escape(year) + r"\s*$", "", v) if year else v


def journal_name(venue: str) -> str:
    """'Thin-Walled Structures 220, 112000' -> 'Thin-Walled Structures'."""
    name = re.split(r",|\s+\d", venue.strip(), maxsplit=1)[0].strip()
    return name.rstrip(" .:;") or venue.strip()


def add_news(html: str, items) -> str:
    start = html.index("const NEWS=") + len("const NEWS=")
    end = html.index("];", start) + 1
    news = json.loads(html[start:end])
    have = {norm(n.get("title", "")) for n in news if n.get("type") == "paper"}
    fresh = [n for n in items if norm(n["title"]) not in have]
    return html[:start] + json.dumps(fresh + news, ensure_ascii=False) + html[end:]


def check_metrics(m, n_rows):
    if len(m) != 6 or not all(isinstance(x, int) and x >= 0 for x in m):
        raise SystemExit(f"metrics malformed: {m}")
    c, c21, h, h21, i10, i1021 = m
    if not (c >= c21 and h >= h21 and i10 >= i1021 and h <= n_rows and i10 <= n_rows and c > 0):
        raise SystemExit(f"metrics fail sanity checks: {m}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--html", default=str(ROOT / "index.html"))
    args = ap.parse_args()

    snap = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    html = Path(args.html).read_text(encoding="utf-8")
    excluded = {norm(t) for t in json.loads((ROOT / "data" / "exclude.json").read_text(encoding="utf-8"))["titles"]}

    rows, ps, pe = split_P(html)
    before_n = len(rows)
    before_sum = sum(int(r[1] or 0) for r in rows)
    keys = [norm(r[2]) for r in rows]

    counted = sum(1 for s in snap["rows"] if (s.get("c") or "").strip())
    if len(snap["rows"]) < 0.9 * before_n or counted < 0.5 * len(snap["rows"]):
        raise SystemExit(f"Scholar page looks incomplete ({len(snap['rows'])} rows, {counted} with counts); refusing")
    metrics = [int(str(x).replace(",", "")) for x in snap["metrics"]]
    check_metrics(metrics, len(snap["rows"]))

    updated, added, skipped, matched = [], [], [], set()
    for s in snap["rows"]:
        t, c = (s.get("t") or "").strip(), (s.get("c") or "").strip()
        y = (s.get("y") or "").strip()
        if not y or not (s.get("v") or "").strip():
            # Scholar's merged duplicates have no year or venue; never let them touch a real entry
            skipped.append((t[:60], "no year or venue (Scholar duplicate)"))
            continue
        hit = next((i for i, k in enumerate(keys) if same_paper(t, k)), None)
        if hit is not None and hit in matched:
            skipped.append((t[:60], "second Scholar row for a paper already updated"))
            continue
        if hit is not None:
            matched.add(hit)
            if c and c != rows[hit][1]:
                updated.append((rows[hit][2][:60], rows[hit][1] or "0", c))
                rows[hit][1] = c
            continue
        reason = None
        if NOTICE.search(t):
            reason = "notice"
        elif any(same_paper(t, e) for e in excluded):
            reason = "in exclude.json"
        elif any(same_paper(t, norm(r[2])) for r in [x for x in rows]):
            reason = "duplicate"
        if reason:
            skipped.append((t[:60], reason))
            continue
        new = [y, c, t, s.get("a", "").strip(), clean_venue(s.get("v", ""), y)]
        rows.append(new)
        keys.append(norm(t))
        added.append((y, t[:80]))

    unmatched_titles = [rows[i][2][:70] for i in range(before_n) if i not in matched]
    after_old_sum = sum(int(rows[i][1] or 0) for i in range(before_n))
    if after_old_sum < 0.95 * before_sum:
        raise SystemExit(f"citations of existing papers dropped {before_sum} -> {after_old_sum}; refusing")
    if len(rows) < before_n:
        raise SystemExit("paper count decreased; refusing")

    d = date.fromisoformat(snap["date"])
    news_items = [{"d": d.strftime("%Y-%m"), "type": "paper", "title": r[2], "venue": journal_name(r[4])}
                  for r in rows[before_n:]]
    rows.sort(key=lambda r: -int(r[0] or 0))  # stable: keeps order within a year
    html = html[:ps] + fmt_rows(rows) + html[pe:]
    if news_items:
        html = add_news(html, news_items)

    c, c21, h, h21, i10, i1021 = metrics
    html, n1 = re.subn(r"<tr><td>Citations</td><td>[\d,]+</td><td>[\d,]+</td></tr>",
                       f"<tr><td>Citations</td><td>{c:,}</td><td>{c21:,}</td></tr>", html)
    html, n2 = re.subn(r"<tr><td>h-index</td><td>\d+</td><td>\d+</td></tr>",
                       f"<tr><td>h-index</td><td>{h}</td><td>{h21}</td></tr>", html)
    html, n3 = re.subn(r"<tr><td>i10-index</td><td>\d+</td><td>\d+</td></tr>",
                       f"<tr><td>i10-index</td><td>{i10}</td><td>{i1021}</td></tr>", html)
    hist = [[int(a), int(b)] for a, b in snap["hist"]]
    html, n4 = re.subn(r"const CITES=\[.*?\];", "const CITES=" + json.dumps(hist, separators=(",", ":")) + ";", html)
    mon = MONTHS[d.month - 1]
    html, n5 = re.subn(r"retrieved \d{1,2} \w+ \d{4}", f"retrieved {d.day} {mon} {d.year}", html)
    html, n6 = re.subn(r"The \d{4} bar covers January to early \w+\.", f"The {d.year} bar covers January to early {mon}.", html)
    html, n7 = re.subn(r"Last updated \w+ \d{4}", f"Last updated {mon} {d.year}", html)
    html, n8 = re.subn(r"Citation counts as of \d{1,2} \w+ \d{4}", f"Citation counts as of {d.day} {mon} {d.year}", html)
    if (n1, n2, n3, n4) != (1, 1, 1, 1) or not (n5 and n6 and n7):
        raise SystemExit(f"template anchors not found: {(n1, n2, n3, n4, n5, n6, n7, n8)}")

    report = {
        "metrics": {"citations": c, "h": h, "i10": i10},
        "papers_before": before_n, "papers_after": len(rows),
        "citation_counts_updated": len(updated), "added": added,
        "news_added": [n["title"][:60] + " | " + n["venue"] for n in news_items],
        "skipped": skipped,
        "site_papers_not_found_on_scholar": unmatched_titles,
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if not args.dry_run:
        Path(args.html).write_text(html, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
