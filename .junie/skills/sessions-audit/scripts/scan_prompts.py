"""Шаг 2. Основная агрегация: одна строка на промпт пользователя.

Запуск: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe scan_prompts.py [--sessions DIR] [--out DIR]
Результат: <out>\\prompts.json + таблицы по выбранной модели, фактической модели, категориям, месяцам.

Ключевые правила:
- выбранная модель = ModelForLaunchAttachment в UserPromptEvent, иначе последний SessionModelEffortSetEvent;
- шаги/стоимость считаются по LlmResponseMetadataEvent; agent.kind == MainAgent -> главный агент,
  другой kind -> субагенты, без agent -> служебные вызовы (роутинг, язык, сжатие: gpt-4.1*, gpt-5.4-nano, haiku);
- rework_next = следующий промпт той же сессии начинается с жалобы (грубая метрика переделок).
"""
import argparse, collections, datetime, json, os, re, tempfile

ap = argparse.ArgumentParser()
ap.add_argument('--sessions', default=os.path.expanduser(r'~\.junie\sessions'))
ap.add_argument('--out', default=os.path.join(tempfile.gettempdir(), 'sessions-audit'))
args = ap.parse_args()
D = args.sessions; OUT = args.out
os.makedirs(OUT, exist_ok=True)

idx = {}
for l in open(os.path.join(D, 'index.jsonl'), encoding='utf-8'):
    try:
        o = json.loads(l); idx[o['sessionId']] = o
    except Exception:
        pass
REWORK = re.compile(r'не работа|ошибк|опять|всё ещё|все еще|до сих пор|не исправ|не помогл|сломал|откат|не то|неправильн|не так|снова|traceback|error', re.I)
CATS = [
    ('git', r'\bgit\b|ветк|merge|мерж|слиян|коммит|commit|rebase|push'),
    ('bug', r'ошибк|не работа|баг|traceback|error|exception|исправ|почин|304|500|сломал'),
    ('audit/analysis', r'аудит|анализ|проанализ|проверь|оцен|сравни|dry|покрыти|review|ревью'),
    ('plan/arch', r'план|архитект|роадмап|roadmap|спроектир|дизайн|структур|модул'),
    ('refactor', r'рефактор|раздел|вынес|перенес|переименуй|упрост|дубл'),
    ('docs', r'док|readme|описан|guide|md\b|перепиши отчет'),
    ('setup/env', r'docker|uvicorn|установ|настрой|venv|uv |сервер|запуст|порт'),
    ('feature', r'добав|нужно|сделай|реализ|создай|чтобы|возможност'),
]


def cat(t):
    t = t.lower()
    for n, r in CATS:
        if re.search(r, t):
            return n
    return 'other'


rows = []
for sid in sorted(os.listdir(D)):
    p = os.path.join(D, sid, 'events.jsonl')
    if not os.path.isfile(p):
        continue
    meta = idx.get(sid) or {}
    cur = None; prompts = []; sess_model = None
    for l in open(p, encoding='utf-8', errors='replace'):
        if not l.strip():
            continue
        try:
            e = json.loads(l)
        except Exception:
            continue
        k = e.get('kind')
        if k == 'SessionModelEffortSetEvent':
            sess_model = e.get('modelId')
        if k == 'UserPromptEvent':
            m = ef = None
            for a in e.get('customAttachments') or []:
                if a.get('kind') == 'ModelForLaunchAttachment': m = a.get('modelId')
                if a.get('kind') == 'EffortForLaunchAttachment': ef = a.get('effort')
            txt = (e.get('presentablePrompt') or e.get('prompt') or '')
            cur = {'sid': sid, 'project': os.path.basename(meta.get('projectDir') or ''), 'task': meta.get('taskName'),
                   'ts': e.get('timestampMs'), 'sel': m or sess_model, 'effort': ef, 'text': txt[:400],
                   'cat': cat(txt[:600]), 'main': collections.Counter(), 'sub': collections.Counter(),
                   'svc': collections.Counter(), 'cost': 0.0, 'main_calls': 0, 'out_tok': 0,
                   'failed': 0, 'cancel': 0, 'files': 0, 'subagents': 0}
            prompts.append(cur)
            continue
        if cur is None:
            continue
        if k == 'CancelAgentEvent': cur['cancel'] += 1
        if k == 'AgentTaskFailedEvent': cur['failed'] += 1
        ev = e.get('event') if isinstance(e.get('event'), dict) else None
        if not ev:
            continue
        ae = ev.get('agentEvent') or {}
        ak = ae.get('kind')
        if ak == 'AgentFailureEvent': cur['failed'] += 1
        if ak == 'AgentPatchCreatedEvent': cur['files'] += 1
        if ak == 'SubagentSpawnedEvent': cur['subagents'] += 1
        if ak == 'LlmResponseMetadataEvent':
            ag = (ae.get('agent') or {}).get('kind')
            for u in ae.get('modelUsage') or []:
                mm = u.get('model'); c = u.get('cost') or 0
                cur['cost'] += c; cur['out_tok'] += u.get('outputTokens') or 0
                if ag == 'MainAgent':
                    cur['main'][mm] += 1; cur['main_calls'] += 1
                elif ag:
                    cur['sub'][mm] += 1
                else:
                    cur['svc'][mm] += 1
    for i, pr in enumerate(prompts):
        nxt = prompts[i + 1]['text'] if i + 1 < len(prompts) else ''
        pr['rework_next'] = 1 if nxt and REWORK.search(nxt[:300]) else 0
        pr['main_model'] = pr['main'].most_common(1)[0][0] if pr['main'] else None
        for f in ('main', 'sub', 'svc'):
            pr[f] = dict(pr[f])
        rows.append(pr)
json.dump(rows, open(os.path.join(OUT, 'prompts.json'), 'w', encoding='utf-8'), ensure_ascii=False)


def agg(key):
    g = collections.defaultdict(list)
    for r in rows:
        g[key(r)].append(r)
    print(f"{'key':40} {'n':>4} {'sess':>4} {'steps':>6} {'cost$':>7} {'$tot':>7} {'fail%':>6} {'canc%':>6} {'rewk%':>6} {'noLLM':>5}")
    for k_, rs in sorted(g.items(), key=lambda x: -len(x[1])):
        n = len(rs); act = [r for r in rs if r['main_calls']]
        st = sum(r['main_calls'] for r in act) / max(1, len(act))
        co = sum(r['cost'] for r in act) / max(1, len(act))
        print(f"{str(k_)[:40]:40} {n:4} {len({r['sid'] for r in rs}):4} {st:6.1f} {co:7.3f} {sum(r['cost'] for r in rs):7.2f} "
              f"{100*sum(1 for r in rs if r['failed'])/n:6.0f} {100*sum(1 for r in rs if r['cancel'])/n:6.0f} "
              f"{100*sum(r['rework_next'] for r in rs)/n:6.0f} {n-len(act):5}")


print('prompts', len(rows), 'sessions', len({r['sid'] for r in rows}))
print('\n== by selected model =='); agg(lambda r: r['sel'])
print('\n== by actual main model =='); agg(lambda r: r['main_model'])
print('\n== by category =='); agg(lambda r: r['cat'])
print('\n== selected model x category ==')
ct = collections.Counter((r['sel'], r['cat']) for r in rows)
for (m, c), n in sorted(ct.items(), key=lambda x: (str(x[0][0]), -x[1])):
    print(f'  {m}: {c}={n}')
print('\n== service models (non-agent) ==')
sv = collections.Counter()
for r in rows:
    for m, n in r['svc'].items(): sv[m] += n
print(sv.most_common(10))
sb = collections.Counter()
for r in rows:
    for m, n in r['sub'].items(): sb[m] += n
print('subagent models', sb.most_common(10))
print('\n== effort ==', collections.Counter((r['sel'], r['effort']) for r in rows).most_common(20))
print('\n== projects ==', collections.Counter(r['project'] for r in rows).most_common(8))
print('\n== months x model ==')
mm = collections.Counter((datetime.datetime.fromtimestamp((r['ts'] or 0) / 1000).strftime('%Y-%m'), r['sel']) for r in rows)
for k_, n in sorted(mm.items(), key=lambda x: (x[0][0], str(x[0][1]))):
    print(' ', k_, n)
print('out ->', OUT)
