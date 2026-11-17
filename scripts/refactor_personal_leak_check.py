"""Pre-publication check: does any public GET leak the operator's personal state to an anonymous visitor?

Run against the candidate API in the public mode (loopback):
  python3 scripts/refactor_personal_leak_check.py <session-file> <entity_id> <watch_group_id> <stock_code> [<channel> <hs_code>]
<session-file> holds "<operator session token> <csrf token>". Every contract GET (frontend routes.json and
live samples) is read anonymously and as the operator; then only the operator's personal ledgers change
(a follow, a saved item, a tracker condition, a watch-group member, a prediction pin; all undone through the API
afterwards; with <channel> and <hs_code> also a feed read mark and a trade-item follow, which the API cannot undo:
pick a channel the operator has no mark for and an item with no owner_trade_follow row, then delete the two rows
by key with the command in LEAK_CHECK_CLEANUP, run before the after-undo sweep) and
every GET is read again. Shared data does not move when only personal ledgers change, so an anonymous
response that changes is a leak; caches are not cleared, so a stale shared result shows up too. Routes
whose anonymous response also differs after the undo vary with time (e.g. decaying activation) and are
reported apart, as are routes that already differ between two back-to-back anonymous reads.
With OBSERVER_SESSION (another signed-in member's "<token> <csrf>" file) the session file may be a member's:
that member's ledgers change and the observer's responses are judged the same way as the anonymous ones.
"""
import json, os, re, sys, urllib.request, urllib.parse
FRONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend') + '/'
BASE = os.environ.get('API_BASE', 'http://127.0.0.1:18012')
ORIGIN = 'https://candidate.test'
token, csrf = open(sys.argv[1]).read().split()
routes = json.load(open(FRONT + 'src/api/generated/routes.json'))
samples = json.load(open(FRONT + 'scripts/live-contract-samples.json'))
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
        urls.append((r['path'], urllib.parse.quote(p) + ('?' + urllib.parse.quote(q, safe='=&') if q else '')))
VOLATILE = re.compile(r'^(as_of|generated_at|now|server_time|elapsed_ms|fetched_at|checked_at)$')
def norm(x):
    if isinstance(x, dict): return {k: norm(v) for k, v in x.items() if not VOLATILE.match(k)}
    if isinstance(x, list): return [norm(v) for v in x]
    return x
sessions = {'op': (token, csrf)}
if os.environ.get('OBSERVER_SESSION'):
    sessions['obs'] = tuple(open(os.environ['OBSERVER_SESSION']).read().split())
def call(method, url, who=None, body=None):
    h = {'x-observe-skip': '1'}
    if who: h['cookie'] = f'__Host-explorer-session={sessions[who][0]}'
    if who and method != 'GET': h.update({'origin': ORIGIN, 'x-csrf-token': sessions[who][1]})
    rq = urllib.request.Request(BASE + url, method=method, headers=h, data=json.dumps(body).encode() if body is not None else None)
    if body is not None: rq.add_header('content-type', 'application/json')
    try:
        with urllib.request.urlopen(rq, timeout=60) as resp: return resp.status, json.loads(resp.read() or b'null')
    except urllib.error.HTTPError as e: return e.code, None
    except Exception as e: return 0, str(e)[:60]
def sweep(who=None):
    return {path: (lambda s, b: (s, json.dumps(norm(b), sort_keys=True, ensure_ascii=False)))(*call('GET', u, who)) for path, u in urls}
print('GET urls', len(urls), flush=True)
A1, A2, O1 = sweep(), sweep(), sweep('op')
W1 = sweep('obs') if 'obs' in sessions else None
noisy = {p for p in A1 if A1[p] != A2[p]}
print('anon status', {s: sum(1 for v in A1.values() if v[0] == s) for s in {v[0] for v in A1.values()}}, 'noisy', sorted(noisy), flush=True)
undo = []
try:
    s, b = call('POST', '/api/spine/follows', 'op', {'entity_id': int(sys.argv[2])}); print('perturb follow', s); undo.append(('DELETE', f'/api/spine/follows/{sys.argv[2]}')) if s in (200, 201) else None
    s, b = call('POST', '/api/spine/saved', 'op', {'kind': 'doc', 'ref': '29424', 'url': '/doc/29424', 'title': 'RV22 시험 저장'}); print('perturb saved', s); undo.append(('DELETE', f"/api/spine/saved/{b['id']}")) if s in (200, 201) else None
    s, b = call('POST', '/api/spine/tracker/005930/conditions', 'op', {'role': 'check', 'kind': 'manual', 'label': 'RV22 시험 조건'}); print('perturb tracker', s); undo.append(('DELETE', f"/api/spine/tracker/conditions/{b['id']}")) if s in (200, 201) else None
    s, b = call('POST', f'/api/spine/groups/{sys.argv[3]}/members', 'op', {'stock_code': sys.argv[4]}); print('perturb group member', s, b if s >= 400 else ''); undo.append(('DELETE', f'/api/spine/groups/{sys.argv[3]}/members/{sys.argv[4]}')) if s in (200, 201) else None
    s, b = call('GET', '/api/spine/home/predictions', 'op')
    free = [i for i in (b or {}).get('items', []) if not i.get('pinned')] if s == 200 else []
    if free:
        t = free[0]; s, _ = call('POST', f"/api/spine/home/predictions/{t['event_ticker']}/pin", 'op', {'series_ticker': t.get('series_ticker') or '', 'pinned': True})
        print('perturb pin', s); undo.append(('POST', f"/api/spine/home/predictions/{t['event_ticker']}/pin", {'series_ticker': t.get('series_ticker') or '', 'pinned': False})) if s == 200 else None
    else:
        print('perturb pin: no unpinned prediction', s)
    if len(sys.argv) > 6:
        s, _ = call('POST', '/api/spine/feed/channels/read', 'op', {'channel': sys.argv[5], 'read_until': '2099-01-01T00:00:00Z'}); print('perturb read mark', s)
        s, _ = call('POST', '/api/spine/trade/follow', 'op', {'hs_code': sys.argv[6], 'active': False}); print('perturb trade follow', s)
    B, O2 = sweep(), sweep('op')
    W2 = sweep('obs') if W1 is not None else None
finally:
    for m, u, *body in undo: print('undo', u, call(m, u, 'op', *body)[0])
if len(sys.argv) > 6:
    import subprocess
    print('cleanup', subprocess.run(os.environ['LEAK_CHECK_CLEANUP'], shell=True).returncode)
A3 = sweep()  # after the undo: personal state is back, time is not
W3 = sweep('obs') if W1 is not None else None
timed = sorted(p for p in A1 if p not in noisy and A1[p] != B[p] and A1[p] != A3[p])
print('time-varying (changed and did not come back after the undo, not a leak):', timed)
leaks = sorted(p for p in A1 if p not in noisy and A1[p] != B[p] and A1[p] == A3[p])
changed_op = sorted(p for p in O1 if O1[p] != O2[p])
print('ANON LEAKS (anonymous response changed with the operator\'s personal ledger):', leaks)
print('operator responses that changed (personal parts reflected):', changed_op)
if W1 is not None:
    w_leaks = sorted(p for p in W1 if p not in noisy and W1[p] != W2[p] and W1[p] == W3[p])
    print('OBSERVER LEAKS (another member\'s response changed with this session\'s personal ledger):', w_leaks)
    print('observer time-varying:', sorted(p for p in W1 if p not in noisy and W1[p] != W2[p] and W1[p] != W3[p]))
