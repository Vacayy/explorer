"""Sync rehearsal R6: does any contract GET show the records R3/R3b brought over (their synthetic markers) to an anonymous
visitor or a member? Runs against the public-mode check gateway (scripts/refactor_public_check.sh, 127.0.0.1:18015).
  python3 scripts/refactor_rehearsal_marker_check.py frontend ~/server-data/review/refactor-single/public-check
"""
import json, os, re, sys, urllib.request, urllib.parse
FRONT = sys.argv[1]; D = sys.argv[2]; BASE = 'http://127.0.0.1:18015'
routes = json.load(open(FRONT + '/src/api/generated/routes.json')); samples = json.load(open(FRONT + '/scripts/live-contract-samples.json'))
sessions = {who: open(f'{D}/{who}.session').read().split() for who in ('operator', 'member')}
MARKERS = ['[리허설 합성] 대화', '[리허설 합성] 질문', '[리허설 합성] 답변', '[리허설 합성] 하위 질문', '[리허설 합성] 보드',
           '[리허설 합성] 리포트', 'rehearsal-synthetic-alert', '[리허설 합성] 충돌', '[리허설 합성] 시나리오', '[리허설 합성] 관측']
def fill(path):
    v = samples['paths'].get(path)
    if v is not None: return v if isinstance(v, list) else [v]
    return [re.sub(r'\{(\w+)\}', lambda m: str(samples['params'].get(m.group(1), '{' + m.group(1) + '}')), path)]
urls = []
for r in routes:
    if r['method'] != 'get' or r.get('status') != 200 or r['path'] in samples['skip']: continue
    for p in fill(r['path']):
        if '{' in p: continue
        q = samples['query'].get(r['path'])
        urls.append(urllib.parse.quote(p) + ('?' + urllib.parse.quote(q, safe='=&') if q else ''))
extra = ['/api/spine/conversations', '/api/spine/questions', '/api/spine/proxy-boards', '/api/spine/report/list']
urls += [u for u in extra if u not in urls]
found = {who: {} for who in ('anonymous', 'member', 'operator')}; status = {who: {} for who in found}
for url in urls:
    for who in found:
        h = {'cookie': f'__Host-explorer-session={sessions[who][0]}'} if who in sessions else {}
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + url, headers=h), timeout=120) as r:
                body, code = r.read().decode('utf-8', 'replace'), r.status
        except urllib.error.HTTPError as e:
            body, code = e.read().decode('utf-8', 'replace'), e.code
        except Exception as e:
            body, code = '', type(e).__name__
        status[who][str(code)] = status[who].get(str(code), 0) + 1
        for m in MARKERS:
            if m in body: found[who].setdefault(m, []).append(url)
print(json.dumps({'routes': len(urls), 'status': status,
                  'markers': {who: {m: len(v) for m, v in f.items()} for who, f in found.items()},
                  'anonymous_or_member_hits': {who: f for who, f in found.items() if who != 'operator' and f}}, ensure_ascii=False))
