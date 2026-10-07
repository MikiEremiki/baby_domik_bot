"""Шаг 1. Инвентаризация журналов сессий Junie: какие события есть, сколько промптов.

Запуск: .venv\\Scripts\\python.exe scan_sessions.py [--sessions DIR] [--out DIR]
Результат: <out>\\sessions.json + сводка видов событий в stdout.
"""
import argparse, collections, json, os, tempfile

ap = argparse.ArgumentParser()
ap.add_argument('--sessions', default=os.path.expanduser(r'~\.junie\sessions'))
ap.add_argument('--out', default=os.path.join(tempfile.gettempdir(), 'sessions-audit'))
args = ap.parse_args()
D = args.sessions
os.makedirs(args.out, exist_ok=True)

idx = {}
for l in open(os.path.join(D, 'index.jsonl'), encoding='utf-8'):
    try:
        o = json.loads(l); idx[o['sessionId']] = o
    except Exception:
        pass
kinds = collections.Counter(); akinds = collections.Counter()
out = []
no_events = []
for sid in sorted(os.listdir(D)):
    p = os.path.join(D, sid, 'events.jsonl')
    if not os.path.isdir(os.path.join(D, sid)):
        continue
    if not os.path.isfile(p):
        no_events.append(sid)
        continue
    s = {'id': sid, 'project': os.path.basename((idx.get(sid) or {}).get('projectDir') or ''),
         'task': (idx.get(sid) or {}).get('taskName'), 'status': (idx.get(sid) or {}).get('status'),
         'prompts': [], 'modelSet': [], 'nevents': 0, 'kinds': collections.Counter()}
    for l in open(p, encoding='utf-8', errors='replace'):
        if not l.strip():
            continue
        try:
            e = json.loads(l)
        except Exception:
            continue
        s['nevents'] += 1
        k = e.get('kind'); kinds[k] += 1
        ak = (e.get('event') or {}).get('agentEvent', {}).get('kind') if isinstance(e.get('event'), dict) else None
        if ak:
            akinds[ak] += 1; s['kinds'][ak] += 1
        if k == 'SessionModelEffortSetEvent':
            s['modelSet'].append(e.get('modelId'))
        if k == 'UserPromptEvent':
            m = ef = None
            for a in e.get('customAttachments') or []:
                if a.get('kind') == 'ModelForLaunchAttachment': m = a.get('modelId')
                if a.get('kind') == 'EffortForLaunchAttachment': ef = a.get('effort')
            s['prompts'].append({'model': m, 'effort': ef, 'ts': e.get('timestampMs'),
                                 'text': (e.get('presentablePrompt') or e.get('prompt') or '')[:300]})
    s['kinds'] = dict(s['kinds'])
    out.append(s)
json.dump(out, open(os.path.join(args.out, 'sessions.json'), 'w', encoding='utf-8'), ensure_ascii=False)
print('index lines', sum(1 for _ in open(os.path.join(D, 'index.jsonl'), encoding='utf-8')), 'unique in index', len(idx))
print('sessions with events', len(out), 'without events (transcript only)', len(no_events),
      'prompts', sum(len(s['prompts']) for s in out))
print('top kinds', kinds.most_common(15))
print('agent kinds', akinds.most_common(40))
print('out ->', args.out)
