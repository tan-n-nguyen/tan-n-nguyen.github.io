"""Weekly check for publications that are not yet on the website.

Looks up works linked to the owner's ORCID in OpenAlex and Crossref, removes
everything already listed in index.html or in data/exclude.json, and writes the
remaining candidates to new_works.md. Nothing on the website is changed: the
workflow turns the report into a GitHub issue for the owner to review.

Run offline for testing:
    python scripts/check_new_works.py --sample tests/sample_openalex.json
"""
import argparse
import difflib
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ORCID = "0000-0001-7734-2058"
MIN_YEAR = 2016
ROOT = Path(__file__).resolve().parent.parent
UA = "tan-n-nguyen.github.io publication check"


def norm(title: str) -> str:
    """Lower-case, strip markup and punctuation so titles compare reliably."""
    title = re.sub(r"<[^>]+>", "", title or "")
    title = title.replace("‐", "-").replace("‑", "-")
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def site_titles(html: str) -> set:
    """Titles in the P array of index.html: each row is [year, cites, title, ...]."""
    block = html.split("const P=[", 1)[1].split("];", 1)[0]
    rows = re.findall(r'\["\d{4}","\d*","((?:[^"\\]|\\.)*)"', block)
    return {norm(t) for t in rows}


def excluded_titles() -> set:
    data = json.loads((ROOT / "data" / "exclude.json").read_text(encoding="utf-8"))
    return {norm(t) for t in data.get("titles", [])}


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def openalex_works() -> list:
    out, cursor = [], "*"
    while cursor:
        q = urllib.parse.urlencode({
            "filter": f"author.orcid:{ORCID}",
            "per_page": 200,
            "cursor": cursor,
            "select": "title,publication_year,doi,type,primary_location",
        })
        data = get_json(f"https://api.openalex.org/works?{q}")
        out += [{
            "title": w.get("title") or "",
            "year": w.get("publication_year"),
            "doi": w.get("doi"),
            "type": w.get("type"),
            "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
            "source": "OpenAlex",
        } for w in data.get("results", [])]
        cursor = data.get("meta", {}).get("next_cursor") if data.get("results") else None
    return out


def crossref_works() -> list:
    q = urllib.parse.urlencode({"filter": f"orcid:{ORCID}", "rows": 1000})
    items = get_json(f"https://api.crossref.org/works?{q}").get("message", {}).get("items", [])
    out = []
    for it in items:
        year = (it.get("issued", {}).get("date-parts") or [[None]])[0][0]
        out.append({
            "title": (it.get("title") or [""])[0],
            "year": year,
            "doi": "https://doi.org/" + it["DOI"] if it.get("DOI") else None,
            "type": it.get("type"),
            "venue": (it.get("container-title") or [None])[0],
            "source": "Crossref",
        })
    return out


def matches(key: str, pool: set, cutoff: float = 0.95) -> bool:
    """Exact match, or a near match that tolerates small wording differences
    between databases (e.g. 'training' vs 'trainings')."""
    return key in pool or bool(difflib.get_close_matches(key, pool, n=1, cutoff=cutoff))


KEEP_TYPES = {"article", "review", "journal-article", "proceedings-article", "book-chapter", "conference-paper"}


def candidates(works: list, known: set, excluded: set) -> list:
    seen, out = set(), []
    for w in works:
        key = norm(w["title"])
        if not key or key in seen or matches(key, known) or matches(key, excluded):
            continue
        if w.get("year") and w["year"] < MIN_YEAR:
            continue
        if w.get("type") and w["type"] not in KEEP_TYPES:
            continue
        seen.add(key)
        out.append(w)
    return sorted(out, key=lambda w: -(w.get("year") or 0))


def report(found: list, errors: list) -> str:
    lines = ["Works linked to ORCID " + ORCID + " that are not on the website yet.", ""]
    if found:
        lines += ["Tick the ones that are yours. Anything left unticked will be added to "
                  "`data/exclude.json` so it is not proposed again.", ""]
        for w in found:
            doi = f" — {w['doi']}" if w.get("doi") else ""
            venue = f"*{w['venue']}*, " if w.get("venue") else ""
            lines.append(f"- [ ] {w['title']} ({venue}{w.get('year') or 'n.d.'}){doi} · {w['source']}")
    else:
        lines.append("No new works found.")
    if errors:
        lines += ["", "Sources that could not be reached this week: " + "; ".join(errors)]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", help="JSON list of works to use instead of the live APIs")
    ap.add_argument("--out", default=str(ROOT / "new_works.md"))
    args = ap.parse_args()

    known = site_titles((ROOT / "index.html").read_text(encoding="utf-8"))
    excluded = excluded_titles()
    works, errors = [], []
    if args.sample:
        works = json.loads(Path(args.sample).read_text(encoding="utf-8"))
    else:
        for name, fn in (("OpenAlex", openalex_works), ("Crossref", crossref_works)):
            try:
                works += fn()
            except Exception as exc:  # report, never fail silently
                errors.append(f"{name}: {exc}")
    found = candidates(works, known, excluded)
    Path(args.out).write_text(report(found, errors), encoding="utf-8")
    print(f"site titles: {len(known)}, excluded: {len(excluded)}, works checked: {len(works)}, "
          f"new candidates: {len(found)}, errors: {len(errors)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
