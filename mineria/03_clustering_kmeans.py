# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paso 3: K-means sobre el perfil de alertas de cada entidad (gold_riesgo_entidades).

Agrupa entidades con patrones de contratación parecidos para priorizar la revisión. Un clúster con
muchas alertas indica patrones irregulares a revisar, no conductas indebidas.

Uso: python mineria/03_clustering_kmeans.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score, davies_bouldin_score, silhouette_score
from sklearn.preprocessing import StandardScaler

BASE = Path(__file__).resolve().parent
DATOS, FIG, RES = BASE / "datos", BASE / "figuras", BASE / "resultados"
SEMILLA = 42
MIN_CONTRATOS = 20  # igual que MIN_CONTRATOS_RANKING en secop_transforms.py
K_RANGO = range(2, 11)

plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 300, "font.size": 9, "axes.titlesize": 10,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.alpha": 0.3, "savefig.bbox": "tight",
})
AZUL, NARANJA = "#1F3864", "#E07A00"
PALETA = ["#1F3864", "#E07A00", "#2E7D32", "#B03A2E", "#6A4C93", "#7F8C8D", "#00838F", "#C49000"]

# Variables: % de contratos de la entidad con cada alerta + participación del mayor contratista.
# Se excluyen: anticipo alto (solo 1,6 % de las entidades lo tiene; varianza casi nula) y el % de la
# alerta de concentración (repite la información de pct_valor_mayor_contratista, que es continua).
ALERTAS = ["contratacion_directa", "fin_de_semana", "inicio_antes_de_firma", "valor_atipico",
           "posible_fraccionamiento", "adiciones_altas", "contratista_no_identificado"]
ETIQUETAS = {"contratacion_directa": "% directa", "fin_de_semana": "% fin de semana",
             "inicio_antes_de_firma": "% inicio antes firma", "valor_atipico": "% valor atípico",
             "posible_fraccionamiento": "% fraccionamiento", "adiciones_altas": "% adiciones altas",
             "contratista_no_identificado": "% contratista no ident.",
             "pct_valor_mayor_contratista": "% valor mayor contratista"}


def guardar(fig, nombre: str) -> None:
    fig.savefig(FIG / f"{nombre}.pdf")
    fig.savefig(FIG / f"{nombre}.png")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Datos y variables
# ---------------------------------------------------------------------------
ent = pd.read_csv(DATOS / "07_riesgo_entidades.csv")
n_total = len(ent)
ent = ent[ent["contratos"] >= MIN_CONTRATOS].copy()
n_min = len(ent)
for a in ALERTAS:
    ent[f"pct_{a}"] = ent[f"contratos_{a}"] / ent["contratos"] * 100
ent = ent.dropna(subset=["pct_valor_mayor_contratista"])  # entidades sin ningún valor confiable
variables = [f"pct_{a}" for a in ALERTAS] + ["pct_valor_mayor_contratista"]
X_pct = ent[variables].to_numpy()

# Transformación raíz cuadrada de la proporción (estabiliza la varianza de porcentajes con muchos
# ceros y colas largas) y luego estandarización (media 0, desviación 1) para que ninguna variable
# domine la distancia euclidiana de K-means.
X = StandardScaler().fit_transform(np.sqrt(X_pct / 100))

# Correlación entre variables (Spearman, robusta a colas)
corr = ent[variables].corr(method="spearman")
corr.to_csv(RES / "correlacion_variables_entidades.csv")
fig, ax = plt.subplots(figsize=(3.5, 3.0))
im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
lbl = [ETIQUETAS[v.removeprefix("pct_")] if v != "pct_valor_mayor_contratista" else ETIQUETAS[v] for v in variables]
ax.set_xticks(range(len(lbl)), lbl, rotation=60, ha="right", fontsize=6.5)
ax.set_yticks(range(len(lbl)), lbl, fontsize=6.5)
for i in range(len(lbl)):
    for j in range(len(lbl)):
        ax.text(j, i, f"{corr.iloc[i, j]:.2f}", ha="center", va="center", fontsize=5.5,
                color="white" if abs(corr.iloc[i, j]) > 0.5 else "black")
ax.grid(False)
fig.colorbar(im, ax=ax, shrink=0.75)
guardar(fig, "fig_correlacion_entidades")

# ---------------------------------------------------------------------------
# Selección de k: codo (inercia), silhouette y Davies-Bouldin
# ---------------------------------------------------------------------------
filas = []
for k in K_RANGO:
    km = KMeans(n_clusters=k, n_init=20, random_state=SEMILLA).fit(X)
    filas.append({"k": k, "inercia": km.inertia_, "silhouette": silhouette_score(X, km.labels_),
                  "davies_bouldin": davies_bouldin_score(X, km.labels_)})
sel = pd.DataFrame(filas)
sel.to_csv(RES / "seleccion_k.csv", index=False)

# k elegido: el de mayor silhouette entre k >= 3 (k = 2 suele separar solo "directa / no directa",
# poco útil para priorizar). El codo se revisa en la figura.
cand = sel[sel["k"] >= 3]
K = int(cand.loc[cand["silhouette"].idxmax(), "k"])

fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.1))
axs[0].plot(sel["k"], sel["inercia"], "o-", color=AZUL)
axs[0].axvline(K, color=NARANJA, ls="--", lw=1)
axs[0].set_xlabel("k")
axs[0].set_ylabel("inercia (SSE)")
axs[0].set_title("Método del codo")
axs[1].plot(sel["k"], sel["silhouette"], "o-", color=AZUL, label="silhouette")
axs[1].axvline(K, color=NARANJA, ls="--", lw=1)
axs[1].set_xlabel("k")
axs[1].set_ylabel("silhouette")
axs[1].set_title("Coeficiente de silhouette")
guardar(fig, "fig_codo_silhouette")

# ---------------------------------------------------------------------------
# Modelo final y estabilidad (ARI entre 10 semillas)
# ---------------------------------------------------------------------------
final = KMeans(n_clusters=K, n_init=50, random_state=SEMILLA).fit(X)
etiquetas_semillas = [KMeans(n_clusters=K, n_init=20, random_state=s).fit_predict(X) for s in range(10)]
ari = [adjusted_rand_score(final.labels_, e) for e in etiquetas_semillas]

# Renumerar clústeres de menor a mayor % de contratos con alerta para que sea legible
ent["cluster_raw"] = final.labels_
orden = ent.groupby("cluster_raw")["pct_contratos_con_alerta"].mean().sort_values().index
mapa = {c: i + 1 for i, c in enumerate(orden)}
ent["cluster"] = ent["cluster_raw"].map(mapa)

perfil = ent.groupby("cluster").agg(
    entidades=("nit_entidad", "size"),
    contratos=("contratos", "sum"),
    mediana_contratos=("contratos", "median"),
    pct_con_alerta=("pct_contratos_con_alerta", "mean"),
    **{v: (v, "mean") for v in variables},
).round(1)
perfil.to_csv(RES / "perfil_clusters.csv")

# Departamento y ejemplos más frecuentes por clúster (solo para interpretar)
top_dep = (ent.groupby("cluster")["departamento"]
           .agg(lambda s: ", ".join(s.value_counts().head(3).index.str.title())))
top_dep.to_csv(RES / "departamentos_por_cluster.csv")
ent[["nit_entidad", "nombre_entidad", "departamento", "contratos", "cluster", *variables,
     "pct_contratos_con_alerta"]].sort_values(["cluster", "contratos"], ascending=[True, False]) \
    .to_csv(RES / "entidades_con_cluster.csv", index=False)

# Mapa de calor del perfil (puntaje z promedio de cada variable por clúster)
z = pd.DataFrame(X, columns=variables, index=ent.index).groupby(ent["cluster"]).mean()
fig, ax = plt.subplots(figsize=(3.5, 2.4))
im = ax.imshow(z.to_numpy(), cmap="RdBu_r", vmin=-2, vmax=2, aspect="auto")
ax.set_xticks(range(len(lbl)), lbl, rotation=60, ha="right", fontsize=6.5)
ax.set_yticks(range(K), [f"C{c} (n={perfil.loc[c, 'entidades']:.0f})" for c in z.index], fontsize=7)
for i in range(K):
    for j in range(len(variables)):
        ax.text(j, i, f"{perfil.iloc[i][variables[j]]:.0f}", ha="center", va="center", fontsize=6,
                color="white" if abs(z.iloc[i, j]) > 1.2 else "black")
ax.grid(False)
cb = fig.colorbar(im, ax=ax, shrink=0.8)
cb.set_label("puntaje z medio", fontsize=7)
guardar(fig, "fig_perfil_clusters")

# Proyección PCA en 2D
pca = PCA(n_components=2, random_state=SEMILLA).fit(X)
P = pca.transform(X)
fig, ax = plt.subplots(figsize=(3.5, 2.8))
for c in sorted(ent["cluster"].unique()):
    msk = (ent["cluster"] == c).to_numpy()
    ax.scatter(P[msk, 0], P[msk, 1], s=4, alpha=0.5, color=PALETA[c - 1], label=f"C{c}")
ax.set_xlabel(f"CP1 ({pca.explained_variance_ratio_[0]*100:.0f} % varianza)")
ax.set_ylabel(f"CP2 ({pca.explained_variance_ratio_[1]*100:.0f} % varianza)")
ax.legend(fontsize=7, markerscale=3, frameon=False, ncol=2)
guardar(fig, "fig_pca_clusters")

cargas = pd.DataFrame(pca.components_.T, index=variables, columns=["CP1", "CP2"]).round(2)
cargas.to_csv(RES / "cargas_pca.csv")

resumen = {
    "entidades_gold": n_total, "entidades_min_contratos": n_min, "entidades_modelo": len(ent),
    "k_elegido": K, "silhouette_final": silhouette_score(X, final.labels_),
    "davies_bouldin_final": davies_bouldin_score(X, final.labels_),
    "ari_medio_10_semillas": float(np.mean(ari)), "ari_min_10_semillas": float(np.min(ari)),
    "varianza_pca_2d": float(pca.explained_variance_ratio_.sum()),
}
pd.Series(resumen).to_csv(RES / "resumen_clustering.csv", header=["valor"])
print(sel.round(3).to_string(index=False))
print(pd.Series(resumen).to_string())
print(perfil.to_string())
print(top_dep.to_string())
print(cargas.to_string())
