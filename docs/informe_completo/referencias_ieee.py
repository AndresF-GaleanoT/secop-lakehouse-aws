# SPDX-License-Identifier: AGPL-3.0-or-later
"""Referencias del informe completo en formato IEEE.

Cambia las citas autor-año por citas numeradas (\\cite), numera las referencias en el
orden en que aparecen en el informe, escribe referencias.tex y deja el título de las
figuras debajo de cada figura, como pide IEEE. Se puede ejecutar solo:
    python -I referencias_ieee.py
"""
import re
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PRINCIPAL = AQUI / "informe_proyecto_secop.tex"
ACC = "[Accedido: 13-nov-2026]."
WEB = "[En línea]. Disponible: "

def web(autor, titulo, url, sitio=""):
    sitio = f" {sitio}." if sitio else ""
    return rf"{autor}, ``{titulo},''{sitio} {WEB}\url{{{url}}}. {ACC}"

AWS = "Amazon Web Services"
REFS = {
    "ancp_secop": web(r"Agencia Nacional de Contratación Pública -- Colombia Compra Eficiente", r"SECOP~II -- Contratos Electrónicos", "https://www.datos.gov.co/d/jbjy-vk9h", r"Portal de Datos Abiertos de Colombia, conjunto \texttt{jbjy-vk9h}"),
    "ley1712": r"Congreso de la República de Colombia, ``Ley 1712 de 2014, por medio de la cual se crea la Ley de Transparencia y del Derecho de Acceso a la Información Pública Nacional,'' \emph{Diario Oficial}, n.\textsuperscript{o}~49.084, 6 mar. 2014.",
    "ocp2016": web("Open Contracting Partnership", "Red flags for integrity: Giving the green light to open data solutions", "https://www.open-contracting.org/resources/red-flags-integrity-giving-green-light-open-data-solutions/", "2016"),
    "fazekas2020": r"M. Fazekas y G. Kocsis, ``Uncovering high-level corruption: Cross-national objective corruption risk indicators using public procurement data,'' \emph{British Journal of Political Science}, vol.~50, n.\textsuperscript{o}~1, pp.~155--164, 2020, doi: 10.1017/S0007123417000461.",
    "ley996": r"Congreso de la República de Colombia, ``Ley 996 de 2005, por medio de la cual se reglamenta la elección de Presidente de la República (Ley de Garantías Electorales),'' \emph{Diario Oficial}, n.\textsuperscript{o}~46.102, 24 nov. 2005.",
    "onu_ods16": web("Naciones Unidas", "Objetivo 16: Promover sociedades justas, pacíficas e inclusivas", "https://www.un.org/sustainabledevelopment/es/peace-justice/", "Objetivos de Desarrollo Sostenible"),
    "onu_ods9": web("Naciones Unidas", "Objetivo 9: Construir infraestructuras resilientes, promover la industrialización sostenible y fomentar la innovación", "https://www.un.org/sustainabledevelopment/es/infrastructure/", "Objetivos de Desarrollo Sostenible"),
    "brown2008": r"T. Brown, ``Design thinking,'' \emph{Harvard Business Review}, vol.~86, n.\textsuperscript{o}~6, pp.~84--92, jun. 2008.",
    "armbrust2021": r"M. Armbrust, A. Ghodsi, R. Xin y M. Zaharia, ``Lakehouse: A new generation of open platforms that unify data warehousing and advanced analytics,'' en \emph{Proc. 11th Conf. Innovative Data Systems Research (CIDR)}, 2021.",
    "zaharia2016": r"M. Zaharia \emph{et al.}, ``Apache Spark: A unified engine for big data processing,'' \emph{Communications of the ACM}, vol.~59, n.\textsuperscript{o}~11, pp.~56--65, nov. 2016, doi: 10.1145/2934664.",
    "tyler_soda": web("Tyler Technologies", "Socrata Open Data API (SODA) documentation", "https://dev.socrata.com/"),
    "tyler_order": web("Tyler Technologies", "The ORDER BY clause", "https://dev.socrata.com/docs/queries/order.html", "Socrata Developers"),
    "databricks_medallion": web("Databricks", "What is the medallion lakehouse architecture?", "https://docs.databricks.com/aws/en/lakehouse/medallion"),
    "asf_iceberg_spec": web("Apache Software Foundation", "Apache Iceberg table format specification", "https://iceberg.apache.org/spec/"),
    "asf_iceberg_evolution": web("Apache Software Foundation", "Evolution", "https://iceberg.apache.org/docs/latest/evolution/", "Apache Iceberg Documentation"),
    "aws_sfn_map": web(AWS, "Map workflow state", "https://docs.aws.amazon.com/step-functions/latest/dg/state-map.html", "AWS Step Functions Developer Guide"),
    "aws_glue_guide": web(AWS, "What is AWS Glue?", "https://docs.aws.amazon.com/glue/latest/dg/what-is-glue.html", "AWS Glue Developer Guide"),
    "ley1581": r"Congreso de la República de Colombia, ``Ley Estatutaria 1581 de 2012, por la cual se dictan disposiciones generales para la protección de datos personales,'' \emph{Diario Oficial}, n.\textsuperscript{o}~48.587, 18 oct. 2012.",
    "ley80": r"Congreso de la República de Colombia, ``Ley 80 de 1993, por la cual se expide el Estatuto General de Contratación de la Administración Pública,'' \emph{Diario Oficial}, n.\textsuperscript{o}~41.094, 28 oct. 1993.",
    "dean2008": r"J. Dean y S. Ghemawat, ``MapReduce: Simplified data processing on large clusters,'' \emph{Communications of the ACM}, vol.~51, n.\textsuperscript{o}~1, pp.~107--113, 2008, doi: 10.1145/1327452.1327492.",
    "zaharia2012": r"M. Zaharia \emph{et al.}, ``Resilient distributed datasets: A fault-tolerant abstraction for in-memory cluster computing,'' en \emph{Proc. 9th USENIX Symp. Networked Systems Design and Implementation (NSDI)}, 2012, pp.~15--28.",
    "grama2003": r"A. Grama, A. Gupta, G. Karypis y V. Kumar, \emph{Introduction to Parallel Computing}, 2.\textsuperscript{a} ed. Harlow, Reino Unido: Addison-Wesley, 2003.",
    "psf_threading": web("Python Software Foundation", "threading: Thread-based parallelism", "https://docs.python.org/3/library/threading.html", "The Python Standard Library"),
    "psf_futures": web("Python Software Foundation", "concurrent.futures: Launching parallel tasks", "https://docs.python.org/3/library/concurrent.futures.html", "The Python Standard Library"),
    "amdahl1967": r"G. M. Amdahl, ``Validity of the single processor approach to achieving large scale computing capabilities,'' en \emph{Proc. AFIPS Spring Joint Computer Conf.}, 1967, pp.~483--485, doi: 10.1145/1465482.1465560.",
    "gustafson1988": r"J. L. Gustafson, ``Reevaluating Amdahl's law,'' \emph{Communications of the ACM}, vol.~31, n.\textsuperscript{o}~5, pp.~532--533, 1988, doi: 10.1145/42411.42415.",
    "karp1990": r"A. H. Karp y H. P. Flatt, ``Measuring parallel processor performance,'' \emph{Communications of the ACM}, vol.~33, n.\textsuperscript{o}~5, pp.~539--543, 1990, doi: 10.1145/78607.78614.",
    "aws_icons": web(AWS, "AWS Architecture Icons", "https://aws.amazon.com/architecture/icons/"),
    "aws_lambda_quotas": web(AWS, "Lambda quotas", "https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html", "AWS Lambda Developer Guide"),
    "aws_glue_pricing": web(AWS, "AWS Glue pricing", "https://aws.amazon.com/glue/pricing/"),
    "aws_s3_sse": web(AWS, "Using server-side encryption with Amazon S3 managed keys (SSE-S3)", "https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingServerSideEncryption.html", "Amazon S3 User Guide"),
    "aws_iam_bp": web(AWS, "Security best practices in IAM", "https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html", "IAM User Guide"),
    "aws_glue_iceberg": web(AWS, "Using the Iceberg framework in AWS Glue", "https://docs.aws.amazon.com/glue/latest/dg/aws-glue-programming-etl-format-iceberg.html", "AWS Glue Developer Guide"),
    "aws_pricing": web(AWS, "AWS pricing", "https://aws.amazon.com/pricing/"),
    "aws_lambda_pricing": web(AWS, "AWS Lambda pricing", "https://aws.amazon.com/lambda/pricing/"),
    "aws_sfn_pricing": web(AWS, "AWS Step Functions pricing", "https://aws.amazon.com/step-functions/pricing/"),
    "aws_s3_pricing": web(AWS, "Amazon S3 pricing", "https://aws.amazon.com/s3/pricing/"),
    "aws_athena_pricing": web(AWS, "Amazon Athena pricing", "https://aws.amazon.com/athena/pricing/"),
    "aws_budget_actions": web(AWS, "Configuring budget actions", "https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-controls.html", "AWS Cost Management User Guide"),
    "aws_glue_versions": web(AWS, "AWS Glue versions", "https://docs.aws.amazon.com/glue/latest/dg/release-notes.html", "AWS Glue Developer Guide"),
    "tukey1977": r"J. W. Tukey, \emph{Exploratory Data Analysis}. Reading, MA, EE.~UU.: Addison-Wesley, 1977.",
    "macqueen1967": r"J. MacQueen, ``Some methods for classification and analysis of multivariate observations,'' en \emph{Proc. 5th Berkeley Symp. Mathematical Statistics and Probability}, vol.~1, 1967, pp.~281--297.",
    "arthur2007": r"D. Arthur y S. Vassilvitskii, ``k-means++: The advantages of careful seeding,'' en \emph{Proc. 18th Annu. ACM-SIAM Symp. Discrete Algorithms (SODA)}, 2007, pp.~1027--1035.",
    "pedregosa2011": r"F. Pedregosa \emph{et al.}, ``Scikit-learn: Machine learning in Python,'' \emph{Journal of Machine Learning Research}, vol.~12, pp.~2825--2830, 2011.",
    "rousseeuw1987": r"P. J. Rousseeuw, ``Silhouettes: A graphical aid to the interpretation and validation of cluster analysis,'' \emph{Journal of Computational and Applied Mathematics}, vol.~20, pp.~53--65, 1987, doi: 10.1016/0377-0427(87)90125-7.",
    "davies1979": r"D. L. Davies y D. W. Bouldin, ``A cluster separation measure,'' \emph{IEEE Trans. Pattern Anal. Mach. Intell.}, vol.~PAMI-1, n.\textsuperscript{o}~2, pp.~224--227, 1979, doi: 10.1109/TPAMI.1979.4766909.",
    "hubert1985": r"L. Hubert y P. Arabie, ``Comparing partitions,'' \emph{Journal of Classification}, vol.~2, n.\textsuperscript{o}~1, pp.~193--218, 1985, doi: 10.1007/BF01908075.",
    "agrawal1994": r"R. Agrawal y R. Srikant, ``Fast algorithms for mining association rules,'' en \emph{Proc. 20th Int. Conf. Very Large Data Bases (VLDB)}, 1994, pp.~487--499.",
}

# Citas narrativas autor-año que pasan a "Autor [n]"
NARRATIVAS = {"tukey1977": "Tukey", "fazekas2020": "Fazekas y Kocsis", "gustafson1988": "Gustafson"}


def a_ieee(t):
    t = re.sub(r"\\citet\{([^}]*)\}", lambda m: NARRATIVAS[m.group(1)] + "~\\cite{" + m.group(1) + "}", t)
    t = t.replace("; \\citealp{", "~\\cite{")
    t = t.replace("\\citealp{", "\\cite{")
    t = re.sub(r" \\citep\{", "~\\\\cite{", t)
    t = t.replace("\\citep{", "\\cite{")
    t = t.replace("Figura~\\ref", "Fig.~\\ref").replace("(Figura~\\ref", "(Fig.~\\ref")
    t = t.replace("Figuras~\\ref", "Figs.~\\ref")
    return t


def caption_abajo(t):
    """IEEE: el título de la figura va debajo de la figura."""
    def mover(m):
        cuerpo = m.group(2)
        i = cuerpo.find("\\caption{")
        if i < 0:
            return m.group(0)
        j, prof = i + len("\\caption{"), 1
        while prof:
            prof += {"{": 1, "}": -1}.get(cuerpo[j], 0)
            j += 1
        lab = re.match(r"\s*\\label\{[^}]*\}", cuerpo[j:])
        if lab:
            j += lab.end()
        cap = cuerpo[i:j].strip()
        resto = (cuerpo[:i] + cuerpo[j:]).rstrip() + "\n" + cap + "\n"
        return m.group(1) + resto + m.group(3)
    return re.sub(r"(\\begin\{figure\*?\}(?:\[[^\]]*\])?)(.*?)(\\end\{figure\*?\})", mover, t, flags=re.S)


def main():
    textos = {}
    for p in [PRINCIPAL] + sorted((AQUI / "partes").glob("parte_*.tex")):
        crudo = p.read_bytes().decode("utf-8")
        crlf = "\r\n" in crudo
        t = caption_abajo(a_ieee(crudo.replace("\r\n", "\n")))
        p.write_bytes((t.replace("\n", "\r\n") if crlf else t).encode("utf-8"))
        textos[p.stem] = t
    # Orden de aparición: el documento principal con cada parte en el lugar de su \input
    completo = re.sub(r"\\input\{partes/(parte_\w+)\}", lambda m: textos[m.group(1)], textos[PRINCIPAL.stem])
    orden = []
    for grupo in re.findall(r"\\cite\{([^}]*)\}", completo):
        for k in (x.strip() for x in grupo.split(",")):
            if k not in orden:
                orden.append(k)
    faltan = [k for k in orden if k not in REFS]
    if faltan:
        raise SystemExit(f"claves sin referencia: {faltan}")
    sobran = [k for k in REFS if k not in orden]
    lineas = [r"\begin{thebibliography}{99}", r"\small"]
    lineas += [rf"\bibitem{{{k}}} {REFS[k]}" for k in orden]
    lineas.append(r"\end{thebibliography}")
    (AQUI / "referencias.tex").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"ok: {len(orden)} referencias; sin citar: {sobran}")


if __name__ == "__main__":
    main()
