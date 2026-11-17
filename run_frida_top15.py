# -*- coding: utf-8 -*-
"""Задача 1: FRIDA-Decisions (System-1) на GPU — топ-N запросов по частоте
для каждого агента из gold.xlsx, присутствующего в mapping из desc.py.

С --idp добавляется 7-й класс idp (фолбэк «подходящего агента нет», без описания;
критерий — короткая опция-фолбэк) и в выборку включаются idp-запросы из gold.xlsx.

Запуск: python run_frida_top15.py [--top 15] [--idp]
Результаты: results_frida_top{N}{_idp}.xlsx
"""
import argparse
import importlib.util
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import torch
from frida_decisions import Judge

# idp не имеет описания: критерий — явная опция-фолбэк (пустую опцию API не допускает)
IDP_LABEL = "Нет подходящего агента: запрос не относится ни к одному из агентов выше"

INSTRUCTION = "Какой агент ответит на запрос пользователя?"

ap = argparse.ArgumentParser()
ap.add_argument("--top", type=int, default=15)
ap.add_argument("--idp", action="store_true", help="добавить класс idp (фолбэк)")
args = ap.parse_args()
TOP_N = args.top
SUFFIX = "_idp" if args.idp else ""

# ---------- 1. Описания агентов из desc.py ----------
spec = importlib.util.spec_from_file_location("desc", "desc.py")
desc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desc)
classes = dict(desc.mapping)
if args.idp:
    classes["idp"] = IDP_LABEL
print("Классы:", list(classes.keys()))

# ---------- 2. Топ-N запросов по частоте для каждого агента ----------
df = pd.read_excel("gold.xlsx")
df = df[df["true_routing"].isin(classes.keys())].copy()
top = (
    df.sort_values("frequency", ascending=False)
    .groupby("true_routing", group_keys=False)
    .head(TOP_N)
    .sort_values(["true_routing", "frequency"], ascending=[True, False])
    .reset_index(drop=True)
)
print(f"Запросов: {len(top)} по {top['true_routing'].nunique()} агентам")

# ---------- 3. Judge на GPU ----------
device = "cuda" if torch.cuda.is_available() else "cpu"
print("device:", device)
judge = Judge.from_pretrained("ai-forever/FRIDA-Decisions", device=device, rows_per_forward=1)

# Конфиг как в fr.ipynb (ячейка 14), но option_max_tokens увеличен,
# чтобы длинные описания (УБ ~14k символов) не обрезались.
judge.config.option_max_tokens = 8192
judge.config.max_row_tokens = 1024
judge.config.instruction_max_tokens = 96
judge.config.max_options_per_row = 32

# Сколько токенов реально занимает каждое описание
try:
    enc = judge.encoder  # TextEncoder
    for name, text in classes.items():
        print(f"  {name}: {enc.count(text)} токенов")
except AttributeError:
    pass

# ---------- 4. Прогон ----------
rows = []
t0 = time.time()
for i, r in top.iterrows():
    request = {
        "state": str(r["user_message_text"]),
        "questions": {
            "agent": {
                "type": "choice",
                "instructions": INSTRUCTION,
                "criteria": classes,
            }
        },
    }
    answer = judge(request)["answers"]["agent"]
    pred = answer["choice"]
    probs = dict(answer.get("probabilities", {}))
    rows.append({
        "true_agent": r["true_routing"],
        "user_message": r["user_message_text"],
        "frequency": int(r["frequency"]),
        "predicted": pred,
        "correct": int(pred == r["true_routing"]),
        "prob": round(float(probs.get(pred, float("nan"))), 4),
        **{f"p_{k}": round(float(v), 4) for k, v in probs.items()},
    })
    if (i + 1) % 10 == 0 or i + 1 == len(top):
        print(f"  {i + 1}/{len(top)} ({time.time() - t0:.0f} c)")

print(f"Готово за {time.time() - t0:.0f} c")

# ---------- 5. Результаты ----------
res = pd.DataFrame(rows)
per_agent = res.groupby("true_agent").agg(
    n=("correct", "size"), acc=("correct", "mean"))
print("\nТочность по агентам:")
print(per_agent.to_string())
print(f"\nOverall accuracy: {res['correct'].mean():.3f}")

out = f"results_frida_top{TOP_N}{SUFFIX}.xlsx"
with pd.ExcelWriter(out) as xw:
    res.to_excel(xw, sheet_name="predictions", index=False)
    per_agent.to_excel(xw, sheet_name="accuracy")
print(f"Сохранено: {out}")
