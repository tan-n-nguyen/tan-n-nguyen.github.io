#!/usr/bin/env bash
# Run before every real update. Fails (non-zero) if the updater misbehaves.
set -euo pipefail
cd "$(dirname "$0")/.."
T=$(mktemp -d)
# 1. a real Scholar snapshot must match every paper on the site and add nothing.
#    Papers added by later syncs are not in this snapshot; they are accepted only
#    if the updater announced them in NEWS (it always does when it adds a paper).
python3 -I scripts/apply_scholar.py tests/scholar_2026-11-16.json --dry-run > "$T/r1.json"
python3 -I - "$T/r1.json" <<'PY'
import json,re,sys
d=json.load(open(sys.argv[1])); assert d['added']==[] and d['news_added']==[], d
h=open('index.html',encoding='utf-8').read(); s=h.index('const NEWS=')+11
news=[re.sub(r'[^a-z0-9]','',n['title'].lower()) for n in json.loads(h[s:h.index('];',s)+1]) if n.get('type')=='paper']
miss=[t for t in d['site_papers_not_found_on_scholar'] if not any(n.startswith(re.sub(r'[^a-z0-9]','',t.lower())) for n in news)]
assert not miss, ('on the site but neither in the reference snapshot nor announced in NEWS', miss)
PY
# 2. a simulated future week: one new paper added, excluded/notice rows rejected, page still valid
cp index.html "$T/p.html"
python3 -I scripts/apply_scholar.py tests/scholar_future_sim.json --html "$T/p.html" > "$T/r2.json"
python3 -c "import json;d=json.load(open('$T/r2.json'));a=[x[1] for x in d['added']];assert any('J2 plasticity' in t for t in a) and not any('Truss' in t or 'Corrigendum' in t for t in a), d; assert len(d['news_added'])==1 and d['news_added'][0].endswith('| Thin-Walled Structures'), d['news_added']"
python3 - "$T/p.html" "$T/p.js" <<'PY'
import re,sys;open(sys.argv[2],'w').write(re.findall(r'<script>(.*?)</script>',open(sys.argv[1]).read(),re.S)[0])
PY
node --check "$T/p.js"
# 3. a half-loaded page must be refused
if python3 -I scripts/apply_scholar.py tests/scholar_halfloaded.json --dry-run >/dev/null 2>&1; then echo "half-loaded page was not refused"; exit 1; fi
# 4. the weekly OpenAlex check must read every site title, before and after an update rewrites the list
python3 -I -c "import sys;sys.path.insert(0,'scripts');from check_new_works import site_titles as s;a=len(s(open('index.html').read()));b=len(s(open('$T/p.html').read()));assert a>=50 and b==a+1,(a,b)"
python3 -I scripts/check_new_works.py --sample tests/sample_openalex.json --out "$T/w.md" >/dev/null
test "$(grep -c '^- \[ \]' "$T/w.md")" = "2"
echo "selftest OK"
