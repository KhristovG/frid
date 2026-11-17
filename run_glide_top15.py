# -*- coding: utf-8 -*-
"""Задача 2b: GLiDE-0.8B (fastino/GLiDE-0.8B, System-1) на GPU —
топ-N запросов на агента из gold.xlsx (агенты из mapping desc.py),
choice-вопрос с полными описаниями (GLiDE берёт до 40k токенов на промпт,
обрезки описаний нет — в отличие от Laya).

С --idp добавляется класс idp (фолбэк, без описания) и idp-запросы из gold.xlsx.

Запуск: python run_glide_top15.py [--top 15] [--idp] [--model models/GLiDE-0.8B] [--batch 1] [--vision]
Результаты: results_glide{27b_,}_top{N}{_idp}.xlsx (суффикс 27b_ добавляется для нестандартной модели)
"""
import argparse
import importlib.util
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

# idp не имеет описания: критерий — явная опция-фолбэк (пустую опцию API не допускает)
IDP_LABEL = "Нет подходящего агента: запрос не относится ни к одному из агентов выше"

INSTRUCTION = "Какой агент ответит на запрос пользователя?"

ap = argparse.ArgumentParser()
ap.add_argument("--top", type=int, default=15)
ap.add_argument("--idp", action="store_true")
ap.add_argument("--model", default="models/GLiDE-0.8B",
                help="путь к локальному репозиторию модели (glide/ внутри него)")
ap.add_argument("--batch", type=int, default=1,
                help="размер батча decide_batch (>1 — батченный инференс)")
ap.add_argument("--vision", action="store_true",
                help="грузить vision-энкодер (для текстовой задачи не нужен)")
args = ap.parse_args()
TOP_N = args.top
SUFFIX = "_idp" if args.idp else ""
MODEL_TAG = "" if args.model.rstrip("/").endswith("GLiDE-0.8B") else "27b_"

sys.path.insert(0, args.model)  # glide/ берётся из репозитория выбранной модели
from glide import Glide

model_tag_print = args.model
print(f"Модель: {model_tag_print}, batch={args.batch}, vision={args.vision}")

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

model = Glide.from_pretrained(args.model, device="cuda", vision=args.vision)

def ask_all(rows_out, batch):
    """Прогон всех запросов: батчами через decide_batch или по одному через decide."""
    t0 = time.time()
    items = list(top.iterrows())

    def handle(i, res):
        r = items[i][1]
        ans = res["answers"]["agent"]
        pred = ans["choice"]
        probs = dict(ans.get("probabilities", {}))
        rows_out.append({
            "true_agent": r["true_routing"],
            "user_message": r["user_message_text"],
            "frequency": int(r["frequency"]),
            "predicted": pred,
            "correct": int(pred == r["true_routing"]),
            "prob": round(float(probs.get(pred, float("nan"))), 4),
            **{f"p_{k}": round(float(v), 4) for k, v in probs.items()},
        })

    if batch > 1:
        for s in range(0, len(items), batch):
            chunk = items[s:s + batch]
            reqs = [{"state": str(r["user_message_text"]),
                     "questions": {"agent": {"type": "choice", "instructions": INSTRUCTION,
                                             "criteria": classes}}}
                    for _, r in chunk]
            for j, res in enumerate(model.decide_batch(reqs)):
                if isinstance(res, Exception):
                    raise res
                handle(s + j, res)
            print(f"  {min(s + batch, len(items))}/{len(items)} ({time.time() - t0:.0f} c)")
    else:
        for i, (_, r) in enumerate(items):
            res = model.decide(
                str(r["user_message_text"]),
                {"agent": {"type": "choice", "instructions": INSTRUCTION, "criteria": classes}},
            )
            handle(i, res)
            if (i + 1) % 15 == 0 or i + 1 == len(items):
                print(f"  {i + 1}/{len(items)} ({time.time() - t0:.0f} c)")

rows = []
t_start = time.time()
ask_all(rows, args.batch)
print(f"Готово за {time.time() - t_start:.0f} c")
res_df = pd.DataFrame(rows)
per_agent = res_df.groupby("true_agent").agg(n=("correct", "size"), acc=("correct", "mean"))
print("\nТочность по агентам (GLiDE):")
print(per_agent.to_string())
print(f"\nOverall accuracy: {res_df['correct'].mean():.3f}")

out = f"results_glide{('_' + MODEL_TAG) if MODEL_TAG else ''}_top{TOP_N}{SUFFIX}.xlsx"
with pd.ExcelWriter(out) as xw:
    res_df.to_excel(xw, sheet_name="predictions", index=False)
    per_agent.to_excel(xw, sheet_name="accuracy")
print(f"Сохранено: {out}")
