# -*- coding: utf-8 -*-
"""Проверка: можно ли в Laya расширить бюджет токенов для описаний-опций?

Часть A (демонстрация): max_len из доки расширяет только STATE (документ),
опции (criteria) режутся до 48 токенов независимо от max_len/head_max_len.

Часть B (обходной путь): кладём полные описания в state (max_len=8192),
опции делаем короткими метками. Оцениваем точность на топ-N запросах.

С --idp добавляется класс idp (фолбэк, без описания; только короткая метка
в опциях — в state описания у него нет) и idp-запросы из gold.xlsx.

Запуск: python run_laya_variants.py [--top 15] [--idp]
Результаты: results_laya_instate_top{N}{_idp}.xlsx
"""
import argparse
import importlib.util
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import laya
from laya import common as lc

INSTRUCTION = "Какой агент ответит на запрос пользователя?"

ap = argparse.ArgumentParser()
ap.add_argument("--top", type=int, default=15)
ap.add_argument("--idp", action="store_true")
args = ap.parse_args()
TOP_N = args.top
SUFFIX = "_idp" if args.idp else ""

spec = importlib.util.spec_from_file_location("desc", "desc.py")
desc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desc)
mapping = desc.mapping

agent = laya.load("convaiinnovations/laya", subfolder="multilingual", device="cuda")

# ---------- Часть A: как режутся опции ----------
q = {"t": "choice", "ins": INSTRUCTION, "crit": mapping}
tok = agent.tok  # TokenizersBackend, есть mask_token
print("A1. build_head: статистика усечения опций (cap на опцию):")
for hml in (192, 420, 8192):
    _, _, stats = lc.build_head(tok, q, head_max_len=hml)
    print(f"  head_max_len={hml:>5}: {stats}")

print("\nA2. predict: max_len не влияет на опции (input_tokens не растёт):")
probe = {"agent": {"type": "choice", "instructions": INSTRUCTION, "criteria": mapping}}
for ml in (512, 8192):
    r = agent.predict("взять кредит", probe, max_len=ml, head_max_len=420)
    print(f"  max_len={ml:>5}: usage={r['usage']}")

# ---------- Часть B: описания в state ----------
# Короткие метки опций (<=48 токенов), суть взята из первых строк описаний.
SHORT = {
    "УБ": "Аналитика личных финансов и благосостояния: расходы, инвестиции, ПДС, налоги, ОСАГО, ВЗР",
    "Самозанятые": "Регистрация и консультирование самозанятых, сервис «Своё Дело», налоги самозанятых",
    "Почтенный Возраст": "Пенсионный консультант: пенсии, стаж, льготы, пенсионные продукты",
    "Лояльность": "Подбор, выбор и подключение категорий кешбэка и бонусов СберСпасибо",
    "Кредиты": "Кредитование физических лиц: подбор кредита, заявки, задолженность, кредитный потенциал",
    "Вклады": "Рублёвые вклады и накопительные/сберегательные счета, их подбор и консультация",
    # idp: описания нет — только короткая метка фолбэка
    "idp": "Нет подходящего агента: запрос не относится ни к одному из агентов выше",
}

doc_parts = [f"{k}:\n{v}" for k, v in mapping.items()]  # описаний у idp нет
DOC = "\n\n".join(doc_parts)

agents = list(mapping.keys()) + (["idp"] if args.idp else [])
df = pd.read_excel("gold.xlsx")
df = df[df["true_routing"].isin(agents)].copy()
top = (
    df.sort_values("frequency", ascending=False)
    .groupby("true_routing", group_keys=False)
    .head(TOP_N)
    .sort_values(["true_routing", "frequency"], ascending=[True, False])
    .reset_index(drop=True)
)

rows = []
t0 = time.time()
for i, r in top.iterrows():
    state = f"Запрос пользователя: {r['user_message_text']}\n\nОписания агентов:\n\n{DOC}"
    res = agent.predict(
        state,
        {"agent": {"type": "choice", "instructions": INSTRUCTION,
                   "criteria": {k: SHORT[k] for k in agents}}},
        max_len=8192,
        head_max_len=420,
    )
    ans = res["answers"]["agent"]
    pred = ans["choice"]
    probs = dict(ans.get("probabilities", {}))
    u = res.get("usage", {})
    rows.append({
        "true_agent": r["true_routing"],
        "user_message": r["user_message_text"],
        "frequency": int(r["frequency"]),
        "predicted": pred,
        "correct": int(pred == r["true_routing"]),
        "prob": round(float(probs.get(pred, float("nan"))), 4),
        "state_dropped": u.get("state_tokens_dropped"),
        **{f"p_{k}": round(float(v), 4) for k, v in probs.items()},
    })
    if (i + 1) % 15 == 0 or i + 1 == len(top):
        print(f"  {i + 1}/{len(top)} ({time.time() - t0:.0f} c)")

print(f"Готово за {time.time() - t0:.0f} c")
res_df = pd.DataFrame(rows)
per_agent = res_df.groupby("true_agent").agg(n=("correct", "size"), acc=("correct", "mean"))
print("\nТочность (Laya, описания в state, max_len=8192):")
print(per_agent.to_string())
print(f"\nOverall accuracy: {res_df['correct'].mean():.3f}")
print("state_tokens_dropped: min/медиана/max =",
      res_df["state_dropped"].min(), res_df["state_dropped"].median(), res_df["state_dropped"].max())

out = f"results_laya_instate_top{TOP_N}{SUFFIX}.xlsx"
with pd.ExcelWriter(out) as xw:
    res_df.to_excel(xw, sheet_name="predictions", index=False)
    per_agent.to_excel(xw, sheet_name="accuracy")
print(f"Сохранено: {out}")
