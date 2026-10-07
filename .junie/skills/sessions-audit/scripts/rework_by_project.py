"""Шаг 4. Доля негативных следующих промптов по паре (проект, модель) — сравнимо внутри проекта.

Запуск: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe rework_by_project.py [--out DIR] [--min N] [--session ID]
Требует <out>\\prompts.json из scan_prompts.py. --session печатает промпты указанной сессии (например, текущей).
"""
import argparse, collections, json, os, re, tempfile

ap = argparse.ArgumentParser()
ap.add_argument('--out', default=os.path.join(tempfile.gettempdir(), 'sessions-audit'))
ap.add_argument('--min', type=int, default=5, help='минимум промптов в группе')
ap.add_argument('--session', help='ID сессии для детального вывода')
args = ap.parse_args()
rows = json.load(open(os.path.join(args.out, 'prompts.json'), encoding='utf-8'))

NEG = re.compile(r'не работа|не помогл|сломал|опять|снова|до сих пор|всё ещё|все еще|не исправ|не устран|не вижу|не сработ|не поменял|не изменил|почему то|почему-то', re.I)
by = collections.defaultdict(list)
for sid in {r['sid'] for r in rows}:
    ps = [r for r in rows if r['sid'] == sid]
    for i, r in enumerate(ps):
        nxt = ps[i + 1]['text'][:250] if i + 1 < len(ps) else ''
        by[(r['project'], r['sel'])].append((1 if NEG.search(nxt) else 0, r['main_calls'], r['cost'], r['files']))
print(f"{'project':24} {'model':24} {'n':>4} {'neg%':>5} {'steps':>6} {'$/pr':>6} {'edit%':>6}")
for (p, m), v in sorted(by.items(), key=lambda x: (x[0][0], -len(x[1]))):
    if len(v) < args.min:
        continue
    n = len(v)
    print(f"{p[:24]:24} {str(m)[:24]:24} {n:4} {100*sum(a for a,_,_,_ in v)/n:5.0f} {sum(b for _,b,_,_ in v)/n:6.1f} "
          f"{sum(c for _,_,c,_ in v)/n:6.3f} {100*sum(1 for *_,f in v if f)/n:6.0f}")

if args.session:
    print(f'\n== session {args.session} ==')
    for r in rows:
        if r['sid'] == args.session:
            print(r['sel'], r['effort'], r['main_calls'], round(r['cost'], 2), r['text'][:80].replace('\n', ' '))
