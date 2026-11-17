# -*- coding: utf-8 -*-
"""Генерация HTML-отчёта по результатам бенчмарка System-1 моделей
(FRIDA / Laya / Laya-in-state / GLiDE-0.8B).

Запуск:
    python make_report.py           # 6 классов (описания из desc.py) -> report_top15.html
    python make_report.py _idp      # + класс idp (фолбэк без описания) -> report_idp.html
"""
import html
import sys

sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

SUFFIX = sys.argv[1] if len(sys.argv) > 1 else ""
IDP = SUFFIX == "_idp"
OUT = "report_idp.html" if IDP else "report_top15.html"

BASE_AGENTS = ["УБ", "Самозанятые", "Почтенный Возраст", "Лояльность", "Кредиты", "Вклады"]
AGENTS = BASE_AGENTS + ["idp"] if IDP else BASE_AGENTS

# Замеренное время прогонов: {suffix: {model_id: text}}
RUN_TIMES = {
    "": {
        "frida": "196 с на 90 запросов (~2.2 с/запрос)",
        "laya": "2 с на 90 запросов (~0.02 с/запрос)",
        "laya_instate": "18 с на 90 запросов (~0.2 с/запрос)",
        "glide": "86 с на 90 запросов (~1 с/запрос)",
    },
    "_idp": {
        "frida": "847 с на 105 запросов (~8 с/запрос; WDDM-своп при 7 длинных опциях)",
        "laya": "3 с на 105 запросов",
        "laya_instate": "21 с на 105 запросов",
        "glide": "~110 с на 105 запросов",
    },
}

MODELS = [
    {
        "id": "frida",
        "name": "FRIDA-Decisions",
        "repo": "https://huggingface.co/ai-forever/FRIDA-Decisions",
        "script": "run_frida_top15.py",
        "color": "#3b82f6",
        "params": "~0.3B (T5-энкодер, ruT5)",
        "backend": "torch, bfloat16, CUDA (RTX 5070 Ti)",
        "options": "полные описания, option_max_tokens=8192 (4096 — как в fr.ipynb — даёт ту же точность)",
        "desc": (
            "System-1 decision-модель от ai-forever: один проход T5-энкодера, типизированные "
            "вопросы (choice/ranking/score/noul), вероятности без генерации текста. "
            "Опции пакуются в строки с block-маской; каждая опция усредняется по своим токенам."
        ),
    },
    {
        "id": "laya",
        "name": "Laya (описания в опциях)",
        "repo": "https://huggingface.co/convaiinnovations/laya",
        "script": "run_laya_top15.py",
        "color": "#f59e0b",
        "params": "0.4B (mmBERT-base, чекпоинт multilingual)",
        "backend": "laya 0.4.35, CUDA",
        "options": "описания обрезаны: ≤48 токенов на опцию (хардкод laya/common.py), head_max_len=420",
        "desc": (
            "System-1 decision-модель от Convai Innovations, Jev-совместимый API. "
            "Архитектурный лимит: каждая опция-критерий режется до 48 токенов "
            "(дефолтный head-бюджет 192 → по 29 токенов на опцию при 6 классах). "
            "max_len=8192 из документации расширяет только state, на опции не влияет. "
            "Карта модели предупреждает: base-чекпоинты near chance zero-shot, точность — после файнтюна."
        ),
    },
    {
        "id": "laya_instate",
        "name": "Laya (описания в state)",
        "repo": "https://huggingface.co/convaiinnovations/laya",
        "script": "run_laya_variants.py",
        "color": "#94a3b8",
        "params": "0.4B (mmBERT-base, чекпоинт multilingual)",
        "backend": "laya 0.4.35, CUDA, max_len=8192",
        "options": "полные описания в state, опции — короткие метки (≤48 токенов)",
        "desc": (
            "Обходной путь для лимита опций: полные описания положены в state "
            "(state умеет до 8192 токенов), опции — короткие метки агентов. "
            "Все 6 описаний = 11 234 токена &gt; 8192, Laya хранит начало state и отрезает "
            "~3 240 токенов хвоста — «Вклады» и хвост «Кредитов» исчезли целиком."
        ),
    },
    {
        "id": "glide",
        "name": "GLiDE-0.8B",
        "repo": "https://huggingface.co/fastino/GLiDE-0.8B",
        "script": "run_glide_top15.py",
        "color": "#10b981",
        "params": "0.75B (Qwen3.5-декодер с linear-attention + 255-way decision readout)",
        "backend": "glide (в репозитории модели), transformers 5.23, CUDA",
        "options": "полные описания, до 40 000 токенов на промпт, без обрезки",
        "desc": (
            "System-1 decision-модель от Fastino: декодер без генерации — вероятность читается "
            "с readout-головки на последнем токене промпта. Русский не заявлен, но работает "
            "лучше всех участников на этой задаче."
        ),
    },
]
for m in MODELS:
    m["file"] = f"results_{m['id']}_top15{SUFFIX}.xlsx" if m["id"] != "laya_instate" \
        else f"results_laya_instate_top15{SUFFIX}.xlsx"
    m["time"] = RUN_TIMES[SUFFIX].get(m["id"], "—")

IDP_NOTE = (
    "idp не имеет описания в desc.py — это фолбэк «подходящего агента нет». "
    "Пустую опцию API моделей не допускает, поэтому idp реализован короткой опцией-фолбэком "
    "«Нет подходящего агента: запрос не относится ни к одному из агентов выше»; "
    "в выборку добавлены топ-N idp-запросов из gold.xlsx (в gold.xlsx их 500)."
)

# Результаты пробы формулировок фолбэка (GLiDE, top-15, 105 запросов; probe_idp_label.py)
PROBE_RESULTS = [
    # (вариант, overall, idp_recall, false_idp из 90)
    ("C (исходный): лейбл «Нет подходящего агента: запрос не относится…»", 0.200, 1.00, 84),
    ("A: лейбл «Другое»", 0.457, 0.73, 51),
    ("B: лейбл «Другое: ни один из агентов выше не подходит»", 0.152, 1.00, 89),
    ("D: лейбл «Другое» + в вопросе «Если ни один не подходит — выбери „Другое“»", 0.457, 0.87, 53),
]


def esc(x):
    return html.escape(str(x))


def load(model):
    return pd.read_excel(model["file"], sheet_name="predictions")


def acc_table(df, color):
    acc = df.groupby("true_agent")["correct"].mean().reindex(AGENTS).fillna(0)
    rows = []
    for a in AGENTS:
        pct = acc[a] * 100
        rows.append(
            f"<tr><td>{esc(a)}</td>"
            f"<td><div class='bar'><div class='bar-fill' style='width:{pct:.1f}%;background:{color}'></div>"
            f"<span class='bar-label'>{pct:.0f}%</span></div></td></tr>"
        )
    total = df["correct"].mean() * 100
    rows.append(
        f"<tr class='total'><td>Итого</td>"
        f"<td><div class='bar'><div class='bar-fill' style='width:{total:.1f}%;background:{color}'></div>"
        f"<span class='bar-label'>{total:.1f}%</span></div></td></tr>"
    )
    return "<table class='acc'>" + "".join(rows) + "</table>"


def confusion(df):
    ct = pd.crosstab(df["true_agent"], df["predicted"])
    ct = ct.reindex(index=AGENTS, columns=AGENTS, fill_value=0)
    head = "".join(f"<th>{esc(a)}</th>" for a in AGENTS)
    body = []
    for a in AGENTS:
        cells = []
        for p in AGENTS:
            v = int(ct.loc[a, p])
            cls = "diag" if a == p else ("miss" if v else "")
            intense = min(v / 15, 1.0)
            if a == p:      # диагональ — верные ответы, зелёная шкала
                style = f"background:rgba(16,185,129,{0.10 + 0.50 * intense:.2f});" if v else ""
            elif v:         # вне диагонали — ошибки, красная шкала
                style = f"background:rgba(239,68,68,{0.08 + 0.55 * intense:.2f});"
            else:
                style = ""
            cells.append(f"<td class='{cls}' style='{style}'>{v or ''}</td>")
        body.append(f"<tr><th>{esc(a)}</th>{''.join(cells)}</tr>")
    return (f"<table class='conf'><tr><th></th>{head}</tr>{''.join(body)}</table>"
            "<p class='hint'>строки — истинный агент, столбцы — предсказание; диагональ — верные ответы</p>")


def examples(df, correct=True, n=5):
    sub = df[df["correct"] == int(correct)].nlargest(n, "prob")
    items = []
    for _, r in sub.iterrows():
        items.append(
            f"<li><code>{esc(r['user_message'])}</code> → <b>{esc(r['predicted'])}</b> "
            f"<span class='muted'>(истина: {esc(r['true_agent'])}, p={r['prob']:.2f})</span></li>"
        )
    return "<ul class='ex'>" + "".join(items) + "</ul>"


def detail_table(df, title):
    cols = ["true_agent", "user_message", "predicted", "correct", "prob"] + [f"p_{a}" for a in AGENTS]
    cols = [c for c in cols if c in df.columns]
    head = "".join(f"<th>{esc(c.replace('p_', '') if c.startswith('p_') else c)}</th>" for c in cols)
    body = []
    for _, r in df.iterrows():
        tds = []
        for c in cols:
            v = r[c]
            if c == "correct":
                tds.append("<td class='ok'>✓</td>" if v else "<td class='bad'>✗</td>")
            elif c == "prob":
                tds.append(f"<td>{v:.2f}</td>")
            elif c.startswith("p_"):
                tds.append(f"<td class='muted'>{v:.2f}</td>")
            else:
                tds.append(f"<td>{esc(v)}</td>")
        cls = "row-ok" if r["correct"] else "row-bad"
        body.append(f"<tr class='{cls}'>{''.join(tds)}</tr>")
    return (f"<details><summary>Все {len(df)} предсказаний — {esc(title)}</summary>"
            f"<div class='scroll'><table class='detail'><tr>{head}</tr>{''.join(body)}</table></div></details>")


dfs = {m["id"]: load(m) for m in MODELS}
N_Q = len(dfs["frida"])

# ---------- idp: колаут про «магнит» и секция пробы формулировок ----------
idp_callout = ""
probe_section = ""
if IDP:
    g = dfs["glide"]
    n_idp_pred = int((g["predicted"] == "idp").sum())
    idp_callout = f"""
    <div class="verdict" style="border-left-color:var(--bad)">
      <b>⚠ Эффект «магнита» у GLiDE.</b> Наивная опция-фолбэк «Нет подходящего агента…» ломает GLiDE:
      {n_idp_pred} из {N_Q} запросов уехали в idp (даже «подбери вклад», p_idp≈0.36–0.55) — точность рухнула
      с 77.8% (без idp) до 20.0%. FRIDA ведёт себя ровно наоборот: ни разу не выбрала idp (recall 0%).
      Подбор формулировки фолбэка — в секции <a href="#glide_probe">Проба формулировок</a>.
    </div>"""
    probe_rows = "".join(
        f"<tr><td>{esc(name)}</td><td>{acc:.1%}</td><td>{rec:.0%}</td><td>{fpos}</td></tr>"
        for name, acc, rec, fpos in PROBE_RESULTS)
    probe_section = f"""
<section id="glide_probe">
  <h2>Проба формулировок фолбэка (GLiDE, top-15)</h2>
  <p class="sub">Скрипт: <code>probe_idp_label.py</code>. Одинаковая выборка (105 запросов, 7 классов),
  меняется только текст опции idp и/или инструкции. Цель — фолбэк, который ловит «чужие» запросы,
  не забирая запросы настоящих агентов.</p>
  <div class="card">
    <table>
      <tr><th>Вариант</th><th>Overall accuracy</th><th>Recall idp</th><th>Ложных idp (из 90)</th></tr>
      {probe_rows}
    </table>
  </div>
  <p class="sub">false_idp — сколько запросов настоящих агентов (не-idp) ошибочно ушли в фолбэк.
  Идеал: высокий recall idp при низких ложных срабатываниях.</p>
  <div class="verdict">
    <b>Вывод пробы:</b> явная опция-фолбэк у GLiDE zero-shot работает как магнит — формулировка меняет
    лишь силу. Негативные формулировки («не относится ни к одному», B и C) — худшие (89–84 ложных из 90);
    нейтральное «Другое» (A/D) лучшее, но и оно уводит больше половины запросов агентов в фолбэк
    (51–53 из 90), точность 45.7% против 77.8% без idp. Правильные пути: порог по вероятности фолбэча
    вместо опции-класса, калибровка или файнтюн — но это уже отдельная задача.
  </div>
</section>"""

# ---------- опциональная секция: GLiDE top-100 ----------
glide100_section = ""
try:
    df100 = pd.read_excel(f"results_glide_top100{SUFFIX}.xlsx", sheet_name="predictions")
    g = next(m for m in MODELS if m["id"] == "glide")
    glide100_section = f"""
<section id="glide100">
  <h2><span class="dot" style="background:{g['color']}"></span>GLiDE-0.8B — контрольный прогон top-100 ({len(df100)} запросов)</h2>
  <p class="sub">Топ-100 запросов по частоте на каждого агента (у «Лояльность» в gold.xlsx всего 108 запросов — взяты 100 из них).
  Скрипт: <code>run_glide_top15.py --top 100{' --idp' if IDP else ''}</code>. Тот же choice-вопрос с полными описаниями.</p>
  <div class="grid2">
    <div><h3>Точность по агентам</h3>{acc_table(df100, g['color'])}</div>
    <div><h3>Матрица ошибок</h3>{confusion(df100)}</div>
  </div>
  <div class="grid2">
    <div><h3>Самые уверенные верные ответы</h3>{examples(df100, correct=True)}</div>
    <div><h3>Самые уверенные ошибки</h3>{examples(df100, correct=False)}</div>
  </div>
  {detail_table(df100, 'GLiDE top-100')}
</section>"""
except FileNotFoundError:
    pass

# ---------- сводная таблица ----------
summary_rows = []
for m in MODELS:
    df = dfs[m["id"]]
    acc = df["correct"].mean() * 100
    summary_rows.append(
        f"<tr><td><span class='dot' style='background:{m['color']}'></span><b>{esc(m['name'])}</b></td>"
        f"<td><div class='bar'><div class='bar-fill' style='width:{acc:.1f}%;background:{m['color']}'></div>"
        f"<span class='bar-label'>{acc:.1f}%</span></div></td>"
        f"<td>{esc(m['params'])}</td><td>{esc(m['time'])}</td></tr>"
    )

per_agent_cmp = []
for a in AGENTS:
    cells = []
    for m in MODELS:
        df = dfs[m["id"]]
        v = df[df["true_agent"] == a]["correct"].mean() * 100
        bg = f"background:rgba(16,185,129,{0.08 + 0.5 * v / 100:.2f});" if v else "background:rgba(239,68,68,0.10);"
        cells.append(f"<td style='{bg}'>{v:.0f}%</td>")
    per_agent_cmp.append(f"<tr><th>{esc(a)}</th>{''.join(cells)}</tr>")
totals = []
for m in MODELS:
    totals.append(f"<td><b>{dfs[m['id']]['correct'].mean() * 100:.1f}%</b></td>")
per_agent_cmp.append(f"<tr class='total'><th>Итого</th>{''.join(totals)}</tr>")

# ---------- вердикт (динамический) ----------
best = max(MODELS, key=lambda m: dfs[m["id"]]["correct"].mean())
best_acc = dfs[best["id"]]["correct"].mean() * 100
if IDP:
    idp_rows = []
    for m in MODELS:
        d = dfs[m["id"]]
        rec = d[d["true_agent"] == "idp"]["correct"].mean() * 100
        false_idp = ((d["predicted"] == "idp") & (d["true_agent"] != "idp")).sum()
        idp_rows.append(f"<li><b>{esc(m['name'])}</b>: полнота idp (recall) {rec:.0f}%; "
                        f"ложных срабатываний idp на чужих запросах — {false_idp} из {N_Q - 15}</li>")
    verdict = f"""
    <div class="verdict">
      <b>С фолбэком idp лучший результат — {esc(best['name'])} ({best_acc:.1f}%)</b>.
      Ключевой вопрос вариации — умеет ли модель «сдаться» и отдать запрос фолбэку, когда подходящего агента нет:
      <ul>{''.join(idp_rows)}</ul>
    </div>"""
else:
    verdict = f"""
    <div class="verdict">
      <b>GLiDE-0.8B — лучший на этой задаче ({best_acc:.1f}%)</b>: единственный, кто читает полные длинные описания
      без обрезки и при этом хорошо справляется с русским. FRIDA сильно смещён в сторону «Вклады».
      Laya без файнтюна задачу не решает — упирается в архитектурный лимит опций
      (48 токенов) и near-chance zero-shot базового чекпоинта.
    </div>"""

# ---------- секции по моделям ----------
sections = []
for m in MODELS:
    df = dfs[m["id"]]
    extra_opt = " + короткая опция-фолбэк idp" if IDP else ""
    sections.append(f"""
<section id="{m['id']}">
  <h2><span class="dot" style="background:{m['color']}"></span>{esc(m['name'])}</h2>
  <div class="card">
    <table class="meta">
      <tr><th>Репозиторий</th><td><a href="{m['repo']}">{esc(m['repo'])}</a></td></tr>
      <tr><th>Параметры</th><td>{esc(m['params'])}</td></tr>
      <tr><th>Бэкенд</th><td>{esc(m['backend'])}</td></tr>
      <tr><th>Бюджет описаний</th><td>{esc(m['options'])}{extra_opt}</td></tr>
      <tr><th>Скорость</th><td>{esc(m['time'])}</td></tr>
      <tr><th>Скрипт</th><td><code>{esc(m['script'])}{(' --idp' if IDP else '')}</code></td></tr>
    </table>
    <p class="desc">{m['desc']}</p>
  </div>
  <div class="grid2">
    <div><h3>Точность по агентам</h3>{acc_table(df, m['color'])}</div>
    <div><h3>Матрица ошибок</h3>{confusion(df)}</div>
  </div>
  <div class="grid2">
    <div><h3>Самые уверенные верные ответы</h3>{examples(df, correct=True)}</div>
    <div><h3>Самые уверенные ошибки</h3>{examples(df, correct=False)}</div>
  </div>
  {detail_table(df, m['name'])}
</section>""")

title_ext = " + фолбэк idp (без описания)" if IDP else ""
method_idp = f"<li><b>Вариация idp:</b> {IDP_NOTE}</li>" if IDP else ""

html_doc = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>System-1 роутинг агентов{(' — с фолбэком idp' if IDP else ' — бенчмарк FRIDA / Laya / GLiDE')}</title>
<style>
  :root {{
    --bg:#0f172a; --card:#1e293b; --text:#e2e8f0; --muted:#94a3b8; --line:#334155;
    --accent:#38bdf8; --ok:#10b981; --bad:#ef4444;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:15px/1.55 "Segoe UI", system-ui, -apple-system, sans-serif;
         background:var(--bg); color:var(--text); }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:32px 20px 80px; }}
  header {{ border-bottom:1px solid var(--line); padding-bottom:20px; margin-bottom:28px; }}
  h1 {{ font-size:26px; margin:0 0 6px; }}
  h2 {{ font-size:20px; margin:40px 0 12px; display:flex; align-items:center; gap:10px; }}
  h3 {{ font-size:15px; color:var(--accent); margin:18px 0 8px; text-transform:uppercase; letter-spacing:.04em; }}
  .sub {{ color:var(--muted); }}
  nav {{ display:flex; flex-wrap:wrap; gap:8px; margin:18px 0 0; }}
  nav a {{ color:var(--accent); text-decoration:none; padding:6px 12px; border:1px solid var(--line);
           border-radius:20px; font-size:13px; }}
  nav a:hover {{ background:var(--card); }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 20px; }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; }}
  th, td {{ border:1px solid var(--line); padding:6px 10px; text-align:left; }}
  th {{ background:rgba(56,189,248,.07); font-weight:600; }}
  .meta th {{ width:170px; color:var(--muted); }}
  .meta td, .meta th {{ border:none; border-bottom:1px solid var(--line); background:none; }}
  .acc td:first-child {{ width:180px; }}
  .bar {{ position:relative; background:rgba(148,163,184,.12); border-radius:6px; height:22px; min-width:220px; }}
  .bar-fill {{ height:100%; border-radius:6px 0 0 6px; }}
  .bar-label {{ position:absolute; left:8px; top:0; line-height:22px; font-size:12.5px; font-weight:600;
                color:#fff; text-shadow:0 1px 2px rgba(0,0,0,.6); }}
  .conf td, .conf th {{ text-align:center; }}
  .conf td.diag {{ font-weight:700; }}
  .conf td:first-child, .conf th:first-child {{ text-align:left; }}
  .hint {{ color:var(--muted); font-size:12.5px; }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:24px; }}
  @media (max-width:860px) {{ .grid2 {{ grid-template-columns:1fr; }} }}
  ul.ex {{ margin:0; padding-left:18px; }}
  ul.ex li {{ margin:4px 0; }}
  .muted {{ color:var(--muted); }}
  .dot {{ display:inline-block; width:12px; height:12px; border-radius:50%; margin-right:2px; }}
  .total td, .total th {{ border-top:2px solid var(--muted); }}
  details {{ margin:14px 0; }}
  summary {{ cursor:pointer; color:var(--accent); padding:8px 0; }}
  .scroll {{ max-height:420px; overflow:auto; border:1px solid var(--line); border-radius:8px; }}
  .detail td, .detail th {{ font-size:12.5px; white-space:nowrap; }}
  .detail td.ok {{ color:var(--ok); }} .detail td.bad {{ color:var(--bad); }}
  tr.row-ok td {{ background:rgba(16,185,129,.04); }}
  tr.row-bad td {{ background:rgba(239,68,68,.05); }}
  code {{ background:rgba(148,163,184,.14); padding:1px 5px; border-radius:4px; font-size:13px; }}
  a {{ color:var(--accent); }}
  .verdict {{ border-left:4px solid var(--accent); padding:12px 16px; background:var(--card);
              border-radius:0 10px 10px 0; margin:16px 0; }}
</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>System-1 модели роутинга банковских агентов{title_ext}</h1>
  <p class="sub">Бенчмарк: FRIDA-Decisions · Laya (2 сетапа) · GLiDE-0.8B &nbsp;|&nbsp; 17.11.2026 · GPU: NVIDIA GeForce RTX 5070 Ti 16&nbsp;ГБ · {N_Q} запросов (топ-15 на агента{', 7 классов' if IDP else ', 6 классов'})</p>
  <nav>
    <a href="#summary">Сводка</a>
    <a href="#method">Методика</a>
    <a href="#frida">FRIDA</a>
    <a href="#laya">Laya (опции)</a>
    <a href="#laya_instate">Laya (state)</a>
    <a href="#glide">GLiDE-0.8B</a>
    {'<a href="#glide100">GLiDE top-100</a>' if glide100_section else ''}
    {'<a href="#glide_probe">Проба формулировок</a>' if IDP else ''}
    <a href="#conclusions">Выводы</a>
  </nav>
</header>

<section id="summary">
  <h2>Сводка</h2>
  <div class="card">
    <table>
      <tr><th>Модель</th><th style="width:38%">Точность ({N_Q} запросов)</th><th>Параметры</th><th>Скорость</th></tr>
      {''.join(summary_rows)}
    </table>
  </div>
  <h3>Точность по агентам, все модели</h3>
  <div class="card">
    <table>
      <tr><th>Агент</th>{''.join(f"<th>{esc(m['name'])}</th>" for m in MODELS)}</tr>
      {''.join(per_agent_cmp)}
    </table>
  </div>
  {verdict}
  {idp_callout}
</section>

<section id="method">
  <h2>Методика</h2>
  <div class="card">
    <ul>
      <li><b>Данные:</b> <code>gold.xlsx</code> (3 110 запросов с частотами и истинной разметкой маршрутизации).
          Взяты агенты из <code>mapping</code> в <code>desc.py</code>:
          УБ, Самозанятые, Почтенный Возраст, Лояльность, Кредиты, Вклады{', плюс idp' if IDP else ''}.
          Метка <code>Домклик</code> (2 запроса) не входит — исключена.</li>
      <li><b>Выборка:</b> топ-15 запросов по частоте на каждого агента → {N_Q} запросов.</li>
      <li><b>Вопрос:</b> choice «Какой агент ответит на запрос пользователя?», критерии — описания агентов из <code>desc.py</code> (полные тексты 3–14 тыс. символов).</li>
      <li><b>Оборудование:</b> GPU CUDA, одинаковый сетап для всех моделей; вероятности всех классов сохранены в xlsx.</li>
      <li><b>FRIDA-конфиг:</b> как в <code>fr.ipynb</code> (ячейка 14), но <code>option_max_tokens=8192</code>;
          контрольный прогон с 4096 (точно как в ноутбуке) дал ту же точность 45.6%.</li>
      <li><b>Проверка лимита Laya:</b> <code>max_len=8192</code> из документации расширяет только state (документ),
          опции-критерии режутся до 48 токенов (<code>max_length=48</code>, захардкожено в <code>laya/common.py</code>, версия 0.4.35 — последняя);
          <code>predict(..., max_len=512)</code> и <code>max_len=8192</code> дают идентичный <code>input_tokens=312</code>.</li>
      {method_idp}
      <li><b>Файлы результатов:</b> results_*_top15{SUFFIX}.xlsx · results_glide_top100{SUFFIX}.xlsx</li>
    </ul>
  </div>
</section>

{''.join(sections)}

{glide100_section}

{probe_section}

<section id="conclusions">
  <h2>Выводы</h2>
  <div class="card">
    <ol>
      {'<li><b>Фолбэк idp «из коробки» не работает ни у одной модели:</b> GLiDE с наивной опцией-фолбэком '
       'отдаёт в idp почти все запросы (точность 20%), FRIDA — ни одного (recall 0%), Laya — 67% recall, '
       'но 39% ложных срабатываний и общая деградация. Нейтральный фолбэк требует подбора формулировки '
       '(см. пробу) или калибровки порога по вероятности.</li>'
       if IDP else ''}
      {'<li><b>GLiDE top-100 с idp не прогонялся:</b> с наивным лейблом прогон дал бы вырожденный результат '
       '(99% запросов в idp); сначала нужно зафиксировать формулировку фолбэка по пробе выше — '
       'отчёт без idp (report_top15.html) содержит контрольный top-100 на 6 классах (74.5%).</li>'
       if IDP else ''}
      <li><b>«То же самое» с Laya и GLiDE сделать можно</b> — обе модели System-1 с тем же Jev-совместимым API
          (<code>state</code> + <code>questions</code> с <code>choice</code>-критериями), обе завелись на GPU из текущего окружения.</li>
      <li><b>GLiDE-0.8B</b> — лучший результат: полные описания (до 40 тыс. токенов на промпт), стабильная
          точность по всем классам. Русский не заявлен в карте, но работает уверенно. Из нюансов — пакеты
          <code>glide</code> и веса лежат в одном HF-репозитории; без <code>flash-linear-attention</code> работает медленнее (reference-кернелы).</li>
      <li><b>FRIDA-Decisions</b> — перекос в «Вклады»: модель отдаёт ему почти половину запросов, включая явные
          кредитные («взять кредит», «рефинансирование»). Точность не меняется между option_max_tokens 4096/8192 —
          дело не в обрезке. Сильная сторона — нативная поддержка длинных опций и ранжирование.</li>
      <li><b>Laya</b> — самый быстрый, но: опции жёстко режутся до 48 токенов, а все полные описания (11 234 токена) не
          влезают и в state (8 192, хранится начало). Карта модели прямо предупреждает: без файнтюна zero-shot
          near chance. Для продакшена — только после файнтюна или с короткими саммари описаний (≤48 токенов).</li>
      <li><b>Рекомендация:</b> для роутинга по полным описаниям агентов из desc.py — GLiDE-0.8B; FRIDA стоит
          дообучить/калибровать (сильный систематический сдвиг к одному классу); Laya — только с файнтюном,
          зато как кандидат для дешёвого первого экрана после обучения.</li>
    </ol>
  </div>
</section>

<p class="sub">Сгенерировано скриптом <code>make_report.py{SUFFIX if IDP else ''}</code> из xlsx-результатов · frida project · 2026-11-17</p>
</div>
</body>
</html>
"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html_doc)
print(f"OK, {OUT}: {len(html_doc)} chars")
