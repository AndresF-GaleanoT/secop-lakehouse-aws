# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paso 2: análisis exploratorio (EDA), nulos y outliers a partir de los CSV de mineria/datos/.

Uso: python mineria/02_eda.py   ->  figuras en mineria/figuras/ y tablas en mineria/resultados/
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
DATOS, FIG, RES = BASE / "datos", BASE / "figuras", BASE / "resultados"
FIG.mkdir(exist_ok=True)
RES.mkdir(exist_ok=True)

AZUL, NARANJA, GRIS, ROJO = "#1F3864", "#E07A00", "#9AA5B1", "#B03A2E"
plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 300, "font.size": 9, "axes.titlesize": 10,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.alpha": 0.3, "savefig.bbox": "tight",
})


def guardar(fig, nombre: str) -> None:
    fig.savefig(FIG / f"{nombre}.pdf")
    fig.savefig(FIG / f"{nombre}.png")
    plt.close(fig)


def miles(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


# ---------------------------------------------------------------------------
# 1. Nulos (toda la tabla de plata, calculado en Athena)
# ---------------------------------------------------------------------------
cal = pd.read_csv(DATOS / "01_calidad_plata.csv").iloc[0]
total = int(cal["total_registros"])
columnas = ["id_contrato", "nit_entidad", "nombre_entidad", "departamento", "sector",
            "modalidad_contratacion", "tipo_contrato", "documento_proveedor", "fecha_firma",
            "fecha_inicio", "fecha_fin", "dias_adicionados", "valor_contrato", "valor_anticipo",
            "codigo_unspsc", "justificacion_modalidad"]
nulos = pd.DataFrame({"columna": columnas, "nulos": [int(cal[c]) for c in columnas]})
nulos["pct"] = nulos["nulos"] / total * 100
nulos.to_csv(RES / "nulos_plata.csv", index=False)

con_nulos = nulos[nulos["nulos"] > 0].sort_values("nulos")
fig, ax = plt.subplots(figsize=(3.5, 2.2))
ax.barh(con_nulos["columna"], con_nulos["pct"], color=AZUL)
for y, (n, p) in enumerate(zip(con_nulos["nulos"], con_nulos["pct"])):
    ax.text(p, y, f" {miles(n)}", va="center", fontsize=7)
ax.set_xlabel("% de los contratos de plata")
ax.set_xlim(0, con_nulos["pct"].max() * 1.45)
ax.grid(axis="y", visible=False)
guardar(fig, "fig_nulos")

# ---------------------------------------------------------------------------
# 2. Muestra determinista (~0,9 %): distribución del valor y outliers
# ---------------------------------------------------------------------------
m = pd.read_csv(DATOS / "03_muestra_plata.csv", parse_dates=["fecha_firma", "fecha_inicio", "fecha_fin"])
m["valor_confiable"] = m["valor_confiable"].astype(str).str.lower() == "true"
m["es_contratacion_directa"] = m["es_contratacion_directa"].astype(str).str.lower() == "true"
pos = m[(m["valor_contrato"] > 0) & m["valor_confiable"]].copy()
pos["log_valor"] = np.log10(pos["valor_contrato"])

fig, ax = plt.subplots(figsize=(3.5, 2.2))
ax.hist(pos["log_valor"], bins=60, color=AZUL, alpha=0.9)
for q, lbl in [(0.5, "mediana"), (0.99, "p99")]:
    v = pos["log_valor"].quantile(q)
    ax.axvline(v, color=NARANJA, lw=1, ls="--")
    ax.text(v, ax.get_ylim()[1] * 0.92, f" {lbl}", color=NARANJA, fontsize=7)
ax.set_xlabel(r"$\log_{10}$(valor del contrato en COP)")
ax.set_ylabel("contratos (muestra)")
guardar(fig, "fig_hist_valor")

# Boxplot por tipo de contrato con el umbral Q3 + 3·IQR calculado en Athena sobre toda la tabla.
out = pd.read_csv(DATOS / "02_outliers_por_tipo.csv")
out.to_csv(RES / "outliers_por_tipo.csv", index=False)
tipos = out[out["q3"] > 0].nlargest(6, "contratos")["tipo_contrato"].tolist()
fig, ax = plt.subplots(figsize=(3.5, 2.6))
datos_box = [pos.loc[pos["tipo_contrato"] == t, "log_valor"] for t in tipos]
ax.boxplot(datos_box, orientation="horizontal", whis=(1, 99), showfliers=False, widths=0.6,
           medianprops={"color": NARANJA}, boxprops={"color": AZUL}, whiskerprops={"color": AZUL})
for i, t in enumerate(tipos, start=1):
    umbral = out.loc[out["tipo_contrato"] == t, "umbral_atipico"].iloc[0]
    ax.plot(np.log10(umbral), i, marker="|", color=ROJO, ms=12, mew=2)
etiquetas = [t.title().replace("De ", "de ").replace("Prestación de Servicios", "Prest. servicios")
             for t in tipos]
ax.set_yticks(range(1, len(tipos) + 1), etiquetas)
ax.set_xlabel(r"$\log_{10}$(valor en COP); bigotes p1–p99; | = Q3 + 3·IQR")
ax.grid(axis="y", visible=False)
guardar(fig, "fig_box_tipo")

# Resumen de outliers para el informe
resumen_out = {
    "atipicos_q3_3iqr_athena": int(out["atipicos"].sum()),
    "no_confiables_mayor_1_billon": int(cal["regla_valor_no_confiable"]),
    "valor_cero": int(cal["regla_valor_cero"]),
    "fin_antes_de_inicio": int(cal["regla_fin_antes_de_inicio"]),
    "muestra_filas": len(m),
    "muestra_skew_valor": float(pos["valor_contrato"].skew()),
    "muestra_skew_log": float(pos["log_valor"].skew()),
}

# ---------------------------------------------------------------------------
# 3. Serie mensual (oro): estacionalidad, contratación directa y Ley de Garantías
# ---------------------------------------------------------------------------
mes = pd.read_csv(DATOS / "04_panorama_mensual.csv")
mes["fecha"] = pd.to_datetime(dict(year=mes["anio"], month=mes["mes"], day=1))
mes = mes[mes["fecha"] >= "2018-01-01"]
mes["pct_directa"] = mes["contratos_directa"] / mes["contratos"] * 100
fig, ax = plt.subplots(figsize=(7.2, 2.4))
ax.bar(mes["fecha"], mes["contratos"] / 1000, width=25, color=GRIS, label="contratos (miles)")
dic = mes[mes["mes"] == 12]
ax.bar(dic["fecha"], dic["contratos"] / 1000, width=25, color=AZUL, label="diciembre")
ax.axvspan(pd.Timestamp("2026-01-31"), pd.Timestamp("2026-06-21"), color=NARANJA, alpha=0.15,
           label="restricción Ley de Garantías 2026")
ax.set_ylabel("contratos (miles)")
ax2 = ax.twinx()
ax2.plot(mes["fecha"], mes["pct_directa"], color=NARANJA, lw=1.2, label="% contratación directa")
ax2.set_ylabel("% directa")
ax2.set_ylim(0, 100)
ax2.grid(False)
ax2.spines["right"].set_visible(True)
h1, l1 = ax.get_legend_handles_labels()
h2, l2 = ax2.get_legend_handles_labels()
ax.legend(h1 + h2, l1 + l2, loc="upper center", bbox_to_anchor=(0.5, -0.12), fontsize=7, ncol=4, frameon=False)
guardar(fig, "fig_serie_mensual")

# Mes de máximo por año (para el texto)
pico = mes.loc[mes.groupby("anio")["contratos"].idxmax(), ["anio", "mes", "contratos"]]
pico.to_csv(RES / "mes_pico_por_anio.csv", index=False)

# ---------------------------------------------------------------------------
# 4. Departamentos y modalidades
# ---------------------------------------------------------------------------
dep = pd.read_csv(DATOS / "05_panorama_departamento.csv")
dep["pct_directa"] = dep["contratos_directa"] / dep["contratos"] * 100
top = dep.nlargest(12, "contratos").iloc[::-1]
fig, ax = plt.subplots(figsize=(3.5, 2.8))
ax.barh(top["departamento"].str.title(), top["contratos"] / 1000, color=AZUL)
for y, p in enumerate(top["pct_directa"]):
    ax.text(top["contratos"].iloc[y] / 1000, y, f" {p:.0f} %", va="center", fontsize=6.5, color=NARANJA)
ax.set_xlabel("contratos (miles); en naranja, % contratación directa")
ax.set_xlim(0, top["contratos"].max() / 1000 * 1.18)
ax.grid(axis="y", visible=False)
ax.tick_params(axis="y", labelsize=7)
guardar(fig, "fig_departamentos")

ms = pd.read_csv(DATOS / "06_panorama_modalidad_sector.csv")
mod = ms[ms["dimension"] == "modalidad"].nlargest(7, "contratos").iloc[::-1]
fig, ax = plt.subplots(figsize=(3.5, 2.2))
ax.barh(mod["categoria"].str.capitalize().str.slice(0, 38), mod["contratos"] / mod["contratos"].sum() * 100,
        color=AZUL)
ax.set_xlabel("% de los contratos")
ax.grid(axis="y", visible=False)
ax.tick_params(axis="y", labelsize=6.5)
guardar(fig, "fig_modalidades")

# ---------------------------------------------------------------------------
# 5. Día de la semana de la firma y plazo (muestra)
# ---------------------------------------------------------------------------
dias = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
dow = m["fecha_firma"].dt.dayofweek.value_counts(normalize=True).sort_index() * 100
plazo = (m["fecha_fin"] - m["fecha_inicio"]).dt.days
plazo = plazo[(plazo >= 0)]
fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.0))
axs[0].bar([dias[int(i)] for i in dow.index], dow.values,
           color=[AZUL] * 5 + [NARANJA] * 2)
axs[0].set_ylabel("% de contratos (muestra)")
axs[0].set_title("Día de la semana de la firma")
axs[1].hist(plazo.clip(upper=730), bins=73, color=AZUL)
axs[1].set_xlabel("plazo (días, recortado en 730)")
axs[1].set_title("Plazo pactado (fin − inicio)")
guardar(fig, "fig_dia_plazo")

# ---------------------------------------------------------------------------
# 6. Frecuencia de cada alerta (todos los contratos, desde las combinaciones de Athena)
# ---------------------------------------------------------------------------
comb = pd.read_csv(DATOS / "08_combinaciones_alertas.csv")
cols_alerta = [c for c in comb.columns if c.startswith("alerta_")]
for c in cols_alerta:
    comb[c] = comb[c].astype(str).str.lower() == "true"
frec = pd.Series({c.replace("alerta_", ""): int(comb.loc[comb[c], "contratos"].sum()) for c in cols_alerta})
frec_total = int(comb["contratos"].sum())
con_alguna = int(comb.loc[comb[cols_alerta].any(axis=1), "contratos"].sum())
frec.sort_values().to_csv(RES / "frecuencia_alertas.csv", header=["contratos"])
nombres = {"contratacion_directa": "Contratación directa", "fin_de_semana": "Fin de semana",
           "inicio_antes_de_firma": "Inicio antes de firma", "valor_atipico": "Valor atípico",
           "posible_fraccionamiento": "Posible fraccionamiento", "concentracion": "Concentración",
           "adiciones_altas": "Adiciones altas", "contratista_no_identificado": "Contratista no identificado",
           "anticipo_alto": "Anticipo > 50 %"}
f = frec.sort_values()
fig, ax = plt.subplots(figsize=(3.5, 2.4))
ax.barh([nombres[i] for i in f.index], f.values, color=AZUL)
ax.set_xscale("log")
for y, v in enumerate(f.values):
    ax.text(v, y, f" {miles(v)}", va="center", fontsize=6.5)
ax.set_xlabel("contratos con la alerta (escala log)")
ax.set_xlim(50, f.max() * 12)
ax.grid(axis="y", visible=False)
ax.tick_params(axis="y", labelsize=7)
guardar(fig, "fig_frecuencia_alertas")

# ---------------------------------------------------------------------------
# Resumen numérico para el informe
# ---------------------------------------------------------------------------
resumen = {
    "total_plata": total,
    "ids_distintos": int(cal["ids_distintos"]),
    "fecha_firma_min": cal["fecha_firma_min"],
    "fecha_firma_max": cal["fecha_firma_max"],
    "contratos_con_alguna_alerta": con_alguna,
    "contratos_en_oro_alertas": frec_total,
    "valor_confiable_con_fecha_billones": float(pd.read_csv(DATOS / "04_panorama_mensual.csv")["valor_total"].sum() / 1e12),
    "pct_directa_total": float(frec["contratacion_directa"] / frec_total * 100),
    "pct_fin_de_semana_muestra": float(dow.loc[[5, 6]].sum()),
    "plazo_mediana_dias_muestra": float(plazo.median()),
    **resumen_out,
    **{f"alerta_{k}": int(v) for k, v in frec.items()},
}
pd.Series(resumen).to_csv(RES / "resumen_eda.csv", header=["valor"])
print(pd.Series(resumen).to_string())
print(pico.to_string(index=False))
