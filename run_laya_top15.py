# -*- coding: utf-8 -*-
"""Задача 2a: Laya (convaiinnovations/laya, multilingual, System-1) на GPU —
топ-N запросов на агента, choice-вопрос с критериями-описаниями из desc.py.

С --idp добавляется класс idp (фолбэк, без описания) и idp-запросы из gold.xlsx.

Важно: Laya архитектурно обрезает каждое описание-опцию до 48 токенов
(весь «head» — вопрос+опции — по умолчанию 192 токена). Поднимаем
head_max_len до 420+, чтобы каждая опция получила свои максимум 48.

Запуск: python run_laya_top15.py [--top 15] [--idp]
Результаты: results_laya_top{N}{_idp}.xlsx
"""
import argparse
import importlib.util
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import laya

# idp не имеет описания: критерий — явная опция-фолбэк (пустую опцию API не допускает)
IDP_LABEL = "Нет подходящего агента: запрос не относится ни к одному из агентов выше"

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
classes = dict(desc.mapping)
if args.idp:
    classes["idp"] = IDP_LABEL
print("Классы:", list(classes.keys()))

df = pd.read_excel("gold.xlsx")
df = df[df["true_routing"].isin(classes.keys())].copy()
top = (
    df.sort_values("frequency", ascending=False)
    .groupby("true_routing", group_keys=False)
    .head(TOP_N)
    .sort_values(["true_routing", "frequency"], ascending=[True, False])
    .reset_index(drop=True)
)

agent = laya.load("convaiinnovations/laya", subfolder="multilingual", device="cuda")
print("Загружен:", getattr(agent, "model_id", "?"))

rows = []
t0 = time.time()
for i, r in top.iterrows():
    res = agent.predict(
        str(r["user_message_text"]),
        {"agent": {"type": "choice", "instructions": INSTRUCTION, "criteria": classes}},
        head_max_len=420,          # 6 опций x 49 токенов + инструкция (7 опций -> 512)
    )
    ans = res["answers"]["agent"]
    pred = ans["choice"]
    probs = dict(ans.get("probabilities", {}))
    rows.append({
        "true_agent": r["true_routing"],
        "user_message": r["user_message_text"],
        "frequency": int(r["frequency"]),
        "predicted": pred,
        "correct": int(pred == r["true_routing"]),
        "prob": round(float(probs.get(pred, float("nan"))), 4),
        **{f"p_{k}": round(float(v), 4) for k, v in probs.items()},
    })
    if (i + 1) % 15 == 0 or i + 1 == len(top):
        print(f"  {i + 1}/{len(top)} ({time.time() - t0:.0f} c)")

print(f"Готово за {time.time() - t0:.0f} c")
res_df = pd.DataFrame(rows)
per_agent = res_df.groupby("true_agent").agg(n=("correct", "size"), acc=("correct", "mean"))
print("\nТочность по агентам (Laya multilingual):")
print(per_agent.to_string())
print(f"\nOverall accuracy: {res_df['correct'].mean():.3f}")

out = f"results_laya_top{TOP_N}{SUFFIX}.xlsx"
with pd.ExcelWriter(out) as xw:
    res_df.to_excel(xw, sheet_name="predictions", index=False)
    per_agent.to_excel(xw, sheet_name="accuracy")
print(f"Сохранено: {out}")
