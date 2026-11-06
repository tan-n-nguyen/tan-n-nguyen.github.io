# Tan N. Nguyen — academic website

Source of https://tan-n-nguyen.github.io

- `index.html` — the whole site (single self-contained page).
- `data/exclude.json` — works that must never be added to the publication list.
- `scripts/check_new_works.py` — weekly check (GitHub Actions, Monday morning Bangkok time) for works linked to ORCID 0000-0001-7734-2058 on OpenAlex and Crossref that are not on the site yet. Results arrive as the issue "New publications to review"; the site itself is never changed automatically.
- `tests/sample_openalex.json` — offline sample the workflow uses to test the checker before every run.
