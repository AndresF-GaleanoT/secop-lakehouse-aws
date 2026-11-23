# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paso 4: reglas de asociación (Apriori) entre las 9 alertas de cada contrato.

Cada contrato es una "transacción" y cada alerta activa un "ítem". Athena devolvió cuántos contratos
tiene cada combinación de alertas (08_combinaciones_alertas.csv), así que el soporte de cualquier
conjunto de alertas se calcula EXACTO sobre los 5,7 millones de contratos sin descargarlos.

Apriori (Agrawal y Srikant, 1994) implementado aquí, sin librerías extra:
  1. Conjuntos frecuentes nivel por nivel; un candidato de tamaño k solo se evalúa si todos sus
     subconjuntos de tamaño k-1 son frecuentes (propiedad antimonótona del soporte).
  2. Reglas A -> B con confianza = sop(A u B) / sop(A) y lift = confianza / sop(B).

Uso: python mineria/04_reglas_asociacion.py
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
DATOS, FIG, RES = BASE / "datos", BASE / "figuras", BASE / "resultados"
SOPORTE_MIN = 0.001  # 0,1 % de los contratos (~5.700): un patrón con peso real
CONFIANZA_MIN = 0.30
LIFT_MIN = 1.2

plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 300, "font.size": 9, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.3, "savefig.bbox": "tight",
})
CORTO = {"contratacion_directa": "directa", "fin_de_semana": "fin_semana",
         "inicio_antes_de_firma": "inicio<firma", "valor_atipico": "valor_atípico",
         "posible_fraccionamiento": "fraccionamiento", "concentracion": "concentración",
         "adiciones_altas": "adiciones_altas", "contratista_no_identificado": "no_identificado",
         "anticipo_alto": "anticipo_alto"}

comb = pd.read_csv(DATOS / "08_combinaciones_alertas.csv")
items = [c for c in comb.columns if c.startswith("alerta_")]
M = np.column_stack([comb[c].astype(str).str.lower() == "true" for c in items])
w = comb["contratos"].to_numpy(dtype=float)
N = w.sum()
nombres = [CORTO[c.removeprefix("alerta_")] for c in items]


def soporte(conj: tuple[int, ...]) -> float:
    return float(w[M[:, list(conj)].all(axis=1)].sum() / N)


# --- Apriori: conjuntos frecuentes ---
frecuentes: dict[tuple[int, ...], float] = {}
nivel = [(i,) for i in range(len(items)) if soporte((i,)) >= SOPORTE_MIN]
frecuentes.update({c: soporte(c) for c in nivel})
evaluados = len(items)
k = 2
while nivel:
    previos = set(nivel)
    candidatos = sorted({tuple(sorted(set(a) | set(b))) for a in nivel for b in nivel
                         if len(set(a) | set(b)) == k})
    candidatos = [c for c in candidatos if all(s in previos for s in combinations(c, k - 1))]
    evaluados += len(candidatos)
    nivel = [c for c in candidatos if soporte(c) >= SOPORTE_MIN]
    frecuentes.update({c: soporte(c) for c in nivel})
    k += 1

# --- Reglas ---
reglas = []
for conj, sop in frecuentes.items():
    if len(conj) < 2:
        continue
    for r in range(1, len(conj)):
        for ant in combinations(conj, r):
            cons = tuple(i for i in conj if i not in ant)
            conf = sop / frecuentes[ant]
            lift = conf / frecuentes[cons]
            reglas.append({
                "antecedente": " + ".join(nombres[i] for i in ant),
                "consecuente": " + ".join(nombres[i] for i in cons),
                "soporte_pct": sop * 100, "contratos": round(sop * N),
                "confianza_pct": conf * 100, "lift": lift,
            })
reglas = pd.DataFrame(reglas)
reglas.to_csv(RES / "reglas_todas.csv", index=False)
fuertes = reglas[(reglas["confianza_pct"] >= CONFIANZA_MIN * 100) & (reglas["lift"] >= LIFT_MIN)] \
    .sort_values("lift", ascending=False)
fuertes.round(3).to_csv(RES / "reglas_fuertes.csv", index=False)

conj_df = pd.DataFrame([{"conjunto": " + ".join(nombres[i] for i in c), "tamano": len(c),
                         "soporte_pct": s * 100, "contratos": round(s * N)}
                        for c, s in frecuentes.items()]).sort_values(["tamano", "soporte_pct"],
                                                                      ascending=[True, False])
conj_df.round(4).to_csv(RES / "conjuntos_frecuentes.csv", index=False)

# --- Figura: soporte vs confianza, color = lift ---
fig, ax = plt.subplots(figsize=(3.5, 2.5))
sc = ax.scatter(reglas["soporte_pct"], reglas["confianza_pct"], c=np.log2(reglas["lift"]),
                cmap="RdBu_r", vmin=-3, vmax=3, s=14, edgecolor="k", linewidth=0.2)
ax.set_xscale("log")
ax.axhline(CONFIANZA_MIN * 100, color="#E07A00", ls="--", lw=0.8)
ax.set_xlabel("soporte (% de contratos, escala log)")
ax.set_ylabel("confianza (%)")
cb = fig.colorbar(sc, ax=ax)
cb.set_label(r"$\log_2$(lift)", fontsize=7)
fig.savefig(FIG / "fig_reglas.pdf")
fig.savefig(FIG / "fig_reglas.png")
plt.close(fig)

# --- Matriz de lift entre pares de alertas ---
lift_mat = pd.DataFrame(np.nan, index=nombres, columns=nombres)
for i, j in combinations(range(len(items)), 2):
    sij, si, sj = soporte((i, j)), soporte((i,)), soporte((j,))
    if sij > 0:
        lift_mat.iloc[i, j] = lift_mat.iloc[j, i] = sij / (si * sj)
lift_mat.round(2).to_csv(RES / "lift_pares.csv")
fig, ax = plt.subplots(figsize=(3.5, 3.0))
im = ax.imshow(np.log2(lift_mat.to_numpy()), cmap="RdBu_r", vmin=-3, vmax=3)
ax.set_xticks(range(len(nombres)), nombres, rotation=60, ha="right", fontsize=6.5)
ax.set_yticks(range(len(nombres)), nombres, fontsize=6.5)
for i in range(len(nombres)):
    for j in range(len(nombres)):
        v = lift_mat.iloc[i, j]
        if not np.isnan(v):
            ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=5.5,
                    color="white" if abs(np.log2(v)) > 2 else "black")
ax.grid(False)
cb = fig.colorbar(im, ax=ax, shrink=0.75)
cb.set_label(r"$\log_2$(lift)", fontsize=7)
fig.savefig(FIG / "fig_lift_pares.pdf")
fig.savefig(FIG / "fig_lift_pares.png")
plt.close(fig)

print(f"contratos={N:.0f} conjuntos_frecuentes={len(frecuentes)} candidatos_evaluados={evaluados} "
      f"reglas={len(reglas)} fuertes={len(fuertes)}")
print(conj_df.to_string(index=False))
print(fuertes.round(2).head(25).to_string(index=False))
