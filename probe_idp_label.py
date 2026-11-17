# -*- coding: utf-8 -*-
"""Подбор формулировки idp-фолбэка для GLiDE (top-15, 105 запросов).

Пробуем варианты лейбла/инструкции и меряем:
overall accuracy, recall idp, ложные idp на чужих запросах.
"""
import importlib.util
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "models/GLiDE-0.8B")

import pandas as pd
from glide import Glide

spec = importlib.util.spec_from_file_location("desc", "desc.py")
desc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desc)
mapping = desc.mapping

BASE_INSTR = "Какой агент ответит на запрос пользователя?"

VARIANTS = {
    "A: лейбл «Другое»": {
        "idp_label": "Другое",
        "instr": BASE_INSTR,
    },
    "B: лейбл «Другое: ни один…»": {
        "idp_label": "Другое: ни один из агентов выше не подходит",
        "instr": BASE_INSTR,
    },
    "D: лейбл «Другое» + инструкция про фолбэк": {
        "idp_label": "Другое",
        "instr": BASE_INSTR + " Если ни один агент не подходит — выбери вариант «Другое».",
    },
}

df = pd.read_excel("gold.xlsx")
agents = list(mapping.keys()) + ["idp"]
df = df[df["true_routing"].isin(agents)].copy()
top = (
    df.sort_values("frequency", ascending=False)
    .groupby("true_routing", group_keys=False)
    .head(15)
    .sort_values(["true_routing", "frequency"], ascending=[True, False])
    .reset_index(drop=True)
)

model = Glide.from_pretrained("models/GLiDE-0.8B", device="cuda")

results = {}
for name, v in VARIANTS.items():
    classes = dict(mapping)
    classes["idp"] = v["idp_label"]
    rows = []
    t0 = time.time()
    for _, r in top.iterrows():
        res = model.decide(
            str(r["user_message_text"]),
            {"agent": {"type": "choice", "instructions": v["instr"], "criteria": classes}},
        )
        ans = res["answers"]["agent"]
        rows.append({"true": r["true_routing"], "pred": ans["choice"],
                     "ok": int(ans["choice"] == r["true_routing"])})
    d = pd.DataFrame(rows)
    acc = d["ok"].mean()
    rec_idp = d[d["true"] == "idp"]["ok"].mean()
    false_idp = int(((d["pred"] == "idp") & (d["true"] != "idp")).sum())
    results[name] = (acc, rec_idp, false_idp)
    print(f"\n=== {name} ===")
    print(f"overall={acc:.3f}  idp_recall={rec_idp:.2f}  false_idp={false_idp}/90  ({time.time()-t0:.0f} c)")
    print(pd.crosstab(d["true"], d["pred"]).to_string())

print("\n\n===== СВОДКА =====")
for name, (acc, rec, fpos) in results.items():
    print(f"{name:45s} acc={acc:.3f}  idp_recall={rec:.2f}  false_idp={fpos}")
