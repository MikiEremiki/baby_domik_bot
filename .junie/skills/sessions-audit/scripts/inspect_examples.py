"""Шаг 3. Проверка «подмены» модели и примеры проблемных промптов (переделки, сбои, отмены).

Запуск: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe inspect_examples.py [--out DIR] [--limit N]
Требует <out>\\prompts.json из scan_prompts.py. Вывод большой — читайте частями (| Select -First 80).
"""
import argparse, collections, json, os, tempfile

ap = argparse.ArgumentParser()
ap.add_argument('--out', default=os.path.join(tempfile.gettempdir(), 'sessions-audit'))
ap.add_argument('--limit', type=int, default=14, help='примеров на модель')
args = ap.parse_args()
rows = json.load(open(os.path.join(args.out, 'prompts.json'), encoding='utf-8'))

print('== selected -> main-agent calls ==')
x = collections.defaultdict(collections.Counter)
for r in rows:
    for m, n in r['main'].items():
        x[r['sel']][m] += n
for s, c in x.items():
    print(s, c.most_common(5))

print('\n== rework / cancel / fail examples ==')
for r in rows:
    if r['rework_next'] or r['failed'] or r['cancel']:
        print(f"[{r['sel']}|{r['cat']}|st{r['main_calls']}|${r['cost']:.2f}|rw{r['rework_next']} f{r['failed']} c{r['cancel']}] "
              f"{r['project'][:12]} :: {r['text'][:130]!r}")

print('\n== samples per model (самые длинные прогоны) ==')
g = collections.defaultdict(list)
for r in rows:
    g[r['sel']].append(r)
for s, rs in g.items():
    rs = sorted(rs, key=lambda r: -r['main_calls'])
    print(f'\n-- {s} --')
    for r in rs[:args.limit]:
        print(f"  [{r['cat']}|st{r['main_calls']}|${r['cost']:.2f}|files{r['files']}] {r['text'][:140]!r}")
