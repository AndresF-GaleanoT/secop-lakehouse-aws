# SPDX-License-Identifier: AGPL-3.0-or-later
"""Genera las partes por materia del informe completo a partir de los informes de cada materia.

Cada informe se convierte en una sección del informe completo (partes/parte_*.tex):
- los informes IEEE (.tex) pierden título y autores, bajan un nivel sus secciones y
  prefijan sus etiquetas y referencias para no chocar entre sí;
- el informe de adquisición se toma de su versión en español (informe_universitario.md).

Uso: python generar_partes.py   (desde docs/informe_completo)
"""
import re
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
SALIDA = AQUI / "partes"

TEX = [
    ("cpd", RAIZ / "informe" / "informe_cpd.tex"),
    ("cloud", AQUI.parent / "informe_cloud" / "informe_cloud_computing.tex"),
    ("mineria", AQUI.parent / "informe_mineria" / "informe_mineria_datos.tex"),
]
MD_ADQ = AQUI.parent / "informe_adquisicion" / "informe_universitario.md"


def leer(p):
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def bloque(texto, inicio, fin):
    m = re.search(re.escape(inicio) + r"(.*?)" + re.escape(fin), texto, re.S)
    return m.group(1).strip() if m else ""


def prefijar(texto, p):
    def claves(m):
        cmd, ks = m.group(1), m.group(2)
        return "\\%s{%s}" % (cmd, ",".join(p + ":" + k.strip() for k in ks.split(",")))
    texto = re.sub(r"\\(cite|ref|eqref|label|bibitem|pageref)\{([^}]*)\}", claves, texto)
    return texto


def convertir_tex(nombre, ruta):
    t = leer(ruta)
    cuerpo = t.split("\\maketitle", 1)[1].split("\\end{document}", 1)[0]
    resumen = bloque(cuerpo, "\\begin{abstract}", "\\end{abstract}")
    claves = bloque(cuerpo, "\\begin{IEEEkeywords}", "\\end{IEEEkeywords}")
    cuerpo = re.sub(r"\\begin\{abstract\}.*?\\end\{abstract\}", "", cuerpo, flags=re.S)
    cuerpo = re.sub(r"\\begin\{IEEEkeywords\}.*?\\end\{IEEEkeywords\}", "", cuerpo, flags=re.S)
    # La declaración de IA va una sola vez, al final del informe completo.
    cuerpo = re.sub(r"\\section\*?\{Declaraci[^}]*\}.*?(?=\\begin\{thebibliography\}|\\section|\Z)", "",
                    cuerpo, flags=re.S)
    cuerpo = re.sub(r"\\balance\b", "", cuerpo)
    # Los informes IEEE definen L{ancho}; en el informe completo L es otra columna, así que se usa Q{ancho}.
    cuerpo = re.sub(r"\\begin\{tabular\}\{[^\n]*", lambda m: re.sub(r"(?<!\\)L\{", "Q{", m.group(0)), cuerpo)
    # Bajar un nivel los títulos (de abajo hacia arriba para no encadenar).
    cuerpo = re.sub(r"\\subsubsection(\*?)\{", r"\\paragraph\1{", cuerpo)
    cuerpo = re.sub(r"\\subsection(\*?)\{", r"\\subsubsection\1{", cuerpo)
    cuerpo = re.sub(r"\\section(\*?)\{", r"\\subsection\1{", cuerpo)
    cuerpo = cuerpo.replace("\\begin{figure*}", "\\begin{figure}").replace("\\end{figure*}", "\\end{figure}")
    cuerpo = cuerpo.replace("\\begin{table*}", "\\begin{table}").replace("\\end{table*}", "\\end{table}")
    # En una columna, \columnwidth es todo el ancho de la página: se reducen las figuras.
    cuerpo = re.sub(r"width=(0?\.\d+)?\\columnwidth", lambda m: "width=%.2f\\textwidth" % (0.7 * float(m.group(1) or 1)), cuerpo)
    cuerpo = re.sub(r"width=(0?\.\d+)?\\textwidth", lambda m: m.group(0), cuerpo)
    cuerpo = cuerpo.replace("\\begin{thebibliography}", "\\begingroup\\renewcommand{\\refname}{Referencias de esta materia}\\begin{thebibliography}")
    cuerpo = cuerpo.replace("\\end{thebibliography}", "\\end{thebibliography}\\endgroup")
    cuerpo = prefijar(cuerpo, nombre)
    inicio = ""
    if resumen:
        inicio += "\\noindent\\textbf{Resumen.} " + prefijar(resumen, nombre) + "\n\n"
    if claves:
        inicio += "\\noindent\\textbf{Palabras clave:} " + claves + "\n\n"
    return inicio + cuerpo.strip() + "\n"


# --------------------------------------------------------------------------- Markdown -> LaTeX
SUP = {"¹": "1", "²": "2", "⁰": "0", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}


def esc(s):
    s = s.replace("\\", "\\textbackslash{}")
    for a, b in [("&", "\\&"), ("%", "\\%"), ("$", "\\$"), ("#", "\\#"), ("_", "\\_"),
                 ("{", "\\{"), ("}", "\\}"), ("~", "\\textasciitilde{}"), ("^", "\\textasciicircum{}")]:
        s = s.replace(a, b)
    s = s.replace("\\textbackslash\\{\\}", "\\textbackslash{}")
    return s


def inline(s):
    partes = re.split(r"(`[^`]*`)", s)
    out = []
    for p in partes:
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            out.append("\\code{" + esc(p[1:-1]) + "}")
            continue
        p = re.sub(r"(\d+(?:,\d+)?)\s*×\s*10([¹²³⁴⁵⁶⁷⁸⁹⁰]+)",
                   lambda m: "%s$\\times 10^{%s}$" % (m.group(1), "".join(SUP[c] for c in m.group(2))), p)
        p = re.sub(r"10([¹²³⁴⁵⁶⁷⁸⁹⁰]+)", lambda m: "$10^{%s}$" % "".join(SUP[c] for c in m.group(1)), p)
        p = p.replace("→", "\x00RA\x00")
        segs = re.split(r"(\$[^$]*\$)", p)
        p = "".join(x if x.startswith("$") and x.endswith("$") and len(x) > 1 else esc(x) for x in segs)
        p = p.replace("\x00RA\x00", "$\\rightarrow$")
        p = re.sub(r"\bTabla (\d+)\b", r"Tabla~\\ref{adq:t\1}", p)
        p = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", p)
        p = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\\emph{\1}", p)
        p = re.sub(r"(https?://\S+?)([.,;)]?)(?=\s|$)", lambda m: "\\url{" + m.group(1).replace("\\_", "_").replace("\\%", "%").replace("\\#", "#").replace("\\&", "&") + "}" + m.group(2), p)
        out.append(p)
    return "".join(out)


def tabla(filas, titulo):
    celdas = [[c.strip() for c in f.strip().strip("|").split("|")] for f in filas]
    cab, alin, datos = celdas[0], celdas[1], celdas[2:]
    spec = "".join("r" if a.strip().endswith(":") and not a.strip().startswith(":") else "l" for a in alin)
    if any(len(inline(c)) > 45 for f in datos for c in f):
        n = len(cab)
        spec = ">{\\raggedright\\arraybackslash}p{0.22\\linewidth}" + "X" * (n - 1)
        env_i, env_f = "\\begin{tabularx}{\\linewidth}{%s}" % spec, "\\end{tabularx}"
    else:
        env_i, env_f = "\\begin{tabular}{%s}" % spec, "\\end{tabular}"
    L = ["\\begin{table}[H]", "\\centering", "\\small"]
    if titulo:
        L.append("\\caption{%s}\\label{adq:t%s}" % (inline(titulo[0]), titulo[1]))
    L += [env_i, "\\toprule", " & ".join(inline(c) for c in cab) + " \\\\", "\\midrule"]
    L += [" & ".join(inline(c) for c in f) + " \\\\" for f in datos]
    L += ["\\bottomrule", env_f, "\\end{table}", ""]
    return "\n".join(L)


def convertir_md(ruta):
    lineas = leer(ruta).split("\n")
    out, i, titulo_tabla, en_lista, en_refs = [], 0, None, None, False
    # Ajuste de coherencia: el trabajo futuro del .md ya se cumplió en el proyecto.
    viejo = ("Como trabajo futuro quedan las consultas SQL sobre oro con Amazon Athena, un sitio web de resultados, "
             "una carga diaria orquestada que relea los últimos diez días y una prueba controlada de aceleración de la adquisición.")
    nuevo = ("La carga diaria automática y las consultas en Amazon Athena ya están en operación; como trabajo futuro "
             "queda un sitio web de resultados.")
    def cerrar_lista():
        nonlocal en_lista
        if en_lista:
            out.append("\\end{%s}" % en_lista)
            en_lista = None
    # Saltar título y metadatos hasta "## Resumen".
    while i < len(lineas) and not lineas[i].startswith("## Resumen"):
        i += 1
    while i < len(lineas):
        l = lineas[i].replace(viejo, nuevo)
        s = l.strip()
        if s == "---" or s == "":
            cerrar_lista(); out.append(""); i += 1; continue
        if s.startswith("|"):
            cerrar_lista()
            filas = []
            while i < len(lineas) and lineas[i].strip().startswith("|"):
                filas.append(lineas[i]); i += 1
            out.append(tabla(filas, titulo_tabla)); titulo_tabla = None; continue
        m = re.match(r"\*\*Tabla (\d+)\.\*\*\s*(.*)", s)
        if m:
            titulo_tabla = (m.group(2), m.group(1)); i += 1; continue
        m = re.match(r"(#{2,4})\s+(?:\d+(?:\.\d+)*\.?\s+)?(.*)", s)
        if m:
            cerrar_lista()
            nivel, txt = len(m.group(1)), m.group(2)
            if txt == "Resumen":
                out.append("\\noindent\\textbf{Resumen.} "); i += 1
                while i < len(lineas) and not lineas[i].strip():
                    i += 1
                out[-1] += inline(lineas[i].strip()); i += 1; continue
            if txt == "Referencias":
                en_refs = True
                out.append("\\subsection*{Referencias de esta materia}")
                out.append("\\begin{list}{}{\\setlength{\\leftmargin}{1.5em}\\setlength{\\itemindent}{-1.5em}\\setlength{\\itemsep}{2pt}}")
                i += 1; continue
            cmd = {2: "subsection", 3: "subsubsection", 4: "paragraph"}[nivel]
            out.append("\\%s{%s}" % (cmd, inline(txt))); i += 1; continue
        m = re.match(r"(\d+)\.\s+(.*)", s)
        if m:
            if en_lista != "enumerate":
                cerrar_lista(); out.append("\\begin{enumerate}"); en_lista = "enumerate"
            out.append("\\item " + inline(m.group(2))); i += 1; continue
        m = re.match(r"[-*]\s+(.*)", s)
        if m:
            if en_lista != "itemize":
                cerrar_lista(); out.append("\\begin{itemize}"); en_lista = "itemize"
            out.append("\\item " + inline(m.group(1))); i += 1; continue
        cerrar_lista()
        out.append(("\\item " if en_refs else "") + inline(s)); i += 1
    cerrar_lista()
    if en_refs:
        out.append("\\end{list}")
    return "\n".join(out) + "\n"


def main():
    import sys
    # Las partes de partes/ son una versión resumida y editada a mano de los informes de cada
    # materia. Regenerarlas desde los informes originales borra esa edición.
    if "--forzar" not in sys.argv:
        raise SystemExit("Las partes están editadas a mano. Use --forzar para regenerarlas desde los informes.")
    SALIDA.mkdir(exist_ok=True)
    for nombre, ruta in TEX:
        (SALIDA / f"parte_{nombre}.tex").write_text(convertir_tex(nombre, ruta), encoding="utf-8")
        print("ok", nombre)
    (SALIDA / "parte_adquisicion.tex").write_text(convertir_md(MD_ADQ), encoding="utf-8")
    print("ok adquisicion")
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import referencias_ieee
    referencias_ieee.main()


if __name__ == "__main__":
    main()
