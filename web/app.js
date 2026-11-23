// SPDX-License-Identifier: AGPL-3.0-or-later
"use strict";

/* Vigilancia SECOP
   Lee los JSON que la Lambda secop-web-export deja en S3 (carpeta data/) y dibuja todo en SVG o HTML,
   sin librerías. Cada gráfica tiene su tabla equivalente y un tooltip que también responde al teclado. */

const RUTA_DATOS = "data/";
const MIN_CONTRATOS_ANIO_CALOR = 10000;
const RESTRICCION = { desde: "2026-01-31", hasta: "2026-06-21" };
// Años con elección presidencial: la Ley de Garantías restringe la contratación directa cuatro meses antes.
const ANIOS_ELECCION_PRESIDENCIAL = [2018, 2022, 2026];
const FILAS_RANKING = 20;

// Las mismas nueve alertas de src/glue/lib/secop_transforms.py.
const ALERTAS = [
  ["contratacion_directa", "Contratación directa", "Adjudicado sin competencia"],
  ["fin_de_semana", "Firma en fin de semana", "Firmado un sábado o un domingo"],
  ["inicio_antes_de_firma", "Ejecución antes de la firma", "La ejecución empezó antes de firmar el contrato"],
  ["valor_atipico", "Valor atípico", "Valor muy superior al habitual para ese tipo de contrato"],
  ["posible_fraccionamiento", "Posible fraccionamiento", "Tres o más contratos del mismo bien o servicio, contratista y entidad en 30 días"],
  ["concentracion", "Concentración en un contratista", "Un contratista se lleva el 30 % o más del valor que contrata la entidad"],
  ["adiciones_altas", "Prórrogas altas", "Prórrogas mayores a la mitad del plazo original"],
  ["contratista_no_identificado", "Contratista no identificado", "No se publicó un documento válido del contratista"],
  ["anticipo_alto", "Anticipo alto", "Anticipo mayor al 50 % del valor (Ley 80 de 1993, art. 40)"],
];

// Mapa de teselas: un cuadro por departamento en una posición aproximada [clave, sigla, columna, fila].
const TESELAS = [
  ["SAN ANDRES", "SAI", 0, 0], ["LA GUAJIRA", "LAG", 5, 0],
  ["ATLANTICO", "ATL", 3, 1], ["MAGDALENA", "MAG", 4, 1], ["CESAR", "CES", 5, 1],
  ["CORDOBA", "COR", 2, 2], ["SUCRE", "SUC", 3, 2], ["BOLIVAR", "BOL", 4, 2], ["NORTE DE SANTANDER", "NSA", 5, 2],
  ["CHOCO", "CHO", 1, 3], ["ANTIOQUIA", "ANT", 2, 3], ["SANTANDER", "SAN", 3, 3], ["BOYACA", "BOY", 4, 3], ["ARAUCA", "ARA", 5, 3],
  ["RISARALDA", "RIS", 1, 4], ["CALDAS", "CAL", 2, 4], ["DISTRITO CAPITAL", "BOG", 3, 4], ["CUNDINAMARCA", "CUN", 4, 4], ["CASANARE", "CAS", 5, 4], ["VICHADA", "VIC", 6, 4],
  ["VALLE DEL CAUCA", "VAL", 1, 5], ["QUINDIO", "QUI", 2, 5], ["TOLIMA", "TOL", 3, 5], ["META", "MET", 4, 5], ["GUAVIARE", "GUV", 5, 5], ["GUAINIA", "GNA", 6, 5],
  ["CAUCA", "CAU", 2, 6], ["HUILA", "HUI", 3, 6], ["CAQUETA", "CAQ", 4, 6], ["VAUPES", "VAU", 5, 6],
  ["NARINO", "NAR", 1, 7], ["PUTUMAYO", "PUT", 2, 7], ["AMAZONAS", "AMA", 4, 7],
];

const MESES = ["ene.", "feb.", "mar.", "abr.", "may.", "jun.", "jul.", "ago.", "sep.", "oct.", "nov.", "dic."];
const MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];

// Rampas secuenciales de un solo tono (claro: de casi superficie a oscuro; oscuro: al revés).
const RAMPAS = {
  claro: ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
  oscuro: ["#0d366b", "#104281", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4"],
};

const reducirMovimiento = matchMedia("(prefers-reduced-motion: reduce)");
const temaOscuro = matchMedia("(prefers-color-scheme: dark)");

/* ============================================================== Formatos */
const nf0 = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("es-CO", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const SD = "sin dato";

const entero = (v) => (v == null ? SD : nf0.format(v));
const pct = (v, decimales = 1) => (v == null || !Number.isFinite(v) ? SD : `${(decimales ? nf1 : nf0).format(v)} %`);

function pesos(v) {
  if (v == null) return SD;
  const a = Math.abs(v);
  if (a >= 1e12) return `$${nf1.format(v / 1e12)} billones`;
  if (a >= 1e9) return `$${nf1.format(v / 1e9)} mil millones`;
  if (a >= 1e6) return `$${nf1.format(v / 1e6)} millones`;
  return `$${nf0.format(v)}`;
}

function compacto(v) {
  if (v >= 1e6) return `${nf1.format(v / 1e6).replace(/,0$/, "")} M`;
  if (v >= 1e3) return `${nf0.format(v / 1e3)} mil`;
  return nf0.format(v);
}

function fecha(iso) {
  const [a, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(a, m - 1, d);
}

const fechaCorta = (f) => `${f.getDate()} ${MESES[f.getMonth()]} ${f.getFullYear()}`;
const diaMes = (f) => `${f.getDate()} ${MESES[f.getMonth()]}`;
const claveDia = (f) => `${f.getFullYear()}-${String(f.getMonth() + 1).padStart(2, "0")}-${String(f.getDate()).padStart(2, "0")}`;

const MINUSCULAS = new Set(["de", "del", "la", "las", "los", "y", "e", "el"]);
function titulo(t) {
  if (!t) return SD;
  return t
    .toLocaleLowerCase("es-CO")
    .split(" ")
    .map((p, i) => (i > 0 && MINUSCULAS.has(p) ? p : p.charAt(0).toLocaleUpperCase("es-CO") + p.slice(1)))
    .join(" ");
}

function oracion(t) {
  if (!t) return SD;
  const l = t.toLocaleLowerCase("es-CO");
  return l.charAt(0).toLocaleUpperCase("es-CO") + l.slice(1);
}

const normalizar = (t) => (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();
const sumar = (filas, clave) => filas.reduce((a, f) => a + (f[clave] || 0), 0);

/* ============================================================== DOM y SVG */
const $ = (sel, raiz = document) => raiz.querySelector(sel);

function h(tag, attrs = {}, ...hijos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "texto") n.textContent = v;
    else if (k === "style") n.style.cssText = v;
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of hijos.flat()) {
    if (c != null) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return n;
}

const NS_SVG = "http://www.w3.org/2000/svg";
function s(tag, attrs = {}, padre) {
  const n = document.createElementNS(NS_SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) n.setAttribute(k, v);
  if (padre) padre.appendChild(n);
  return n;
}

function texto(padre, attrs, contenido) {
  const n = s("text", attrs, padre);
  n.textContent = contenido;
  return n;
}

function lienzoSvg(ancho, alto, etiqueta) {
  return s("svg", { width: ancho, height: alto, viewBox: `0 0 ${ancho} ${alto}`, role: "group", "aria-label": etiqueta });
}

const varCss = (nombre) => getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
const rampa = () => RAMPAS[temaOscuro.matches ? "oscuro" : "claro"];
const colorRampa = (t) => {
  const r = rampa();
  return r[Math.min(r.length - 1, Math.max(0, Math.floor(t * r.length)))];
};

function luminancia(hex) {
  const c = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => {
    const v = parseInt(c.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

// Texto blanco o casi negro sobre un relleno, según cuál contraste más.
function textoSobre(hex) {
  const l = luminancia(hex);
  return 1.05 / (l + 0.05) >= (l + 0.05) / (luminancia("#0b0b0b") + 0.05) ? "#ffffff" : "#0b0b0b";
}

/* ============================================================== Tooltip */
const tooltip = (() => {
  const el = h("div", { class: "tooltip", "aria-hidden": "true" });
  document.body.append(el);

  function mostrar(tituloTexto, filas, x, y) {
    el.replaceChildren(
      h("p", { class: "caption-4 tooltip-titulo", texto: tituloTexto }),
      ...filas.map((f) =>
        h(
          "div",
          { class: "tooltip-fila" },
          f.color ? h("span", { class: "clave-linea", style: `background:${f.color}` }) : null,
          h("span", { class: "body-4", texto: f.valor }),
          f.etiqueta ? h("span", { class: "caption-5 tooltip-etiqueta", texto: f.etiqueta }) : null
        )
      )
    );
    el.classList.add("visible");
    const r = el.getBoundingClientRect();
    let izq = x + 14;
    let arriba = y + 14;
    if (izq + r.width > innerWidth - 8) izq = x - r.width - 14;
    if (arriba + r.height > innerHeight - 8) arriba = y - r.height - 14;
    el.style.left = `${Math.max(8, izq)}px`;
    el.style.top = `${Math.max(8, arriba)}px`;
  }

  const ocultar = () => el.classList.remove("visible");
  document.addEventListener("pointerdown", (e) => {
    if (!e.target.closest("[data-tip]")) ocultar();
  });
  addEventListener("scroll", ocultar, { passive: true });
  return { mostrar, ocultar };
})();

// Conecta un nodo con el tooltip: puntero, toque y foco de teclado muestran lo mismo.
function conTooltip(nodo, contenido) {
  nodo.setAttribute("data-tip", "");
  const desdePuntero = (e) => {
    const [t, filas] = contenido();
    tooltip.mostrar(t, filas, e.clientX, e.clientY);
  };
  nodo.addEventListener("pointermove", desdePuntero);
  nodo.addEventListener("pointerdown", desdePuntero);
  nodo.addEventListener("pointerleave", (e) => {
    if (e.pointerType === "mouse") tooltip.ocultar();
  });
  nodo.addEventListener("focus", () => {
    const r = nodo.getBoundingClientRect();
    const [t, filas] = contenido();
    tooltip.mostrar(t, filas, r.left + r.width / 2, r.top + r.height / 2);
  });
  nodo.addEventListener("blur", tooltip.ocultar);
}

/* ============================================================== Gráficas adaptables */
const dibujos = [];

// Dibuja de una vez y otra vez cuando cambia el ancho del contenedor o el tema del sistema. El primer
// dibujo no espera al ResizeObserver, que no avisa mientras la pestaña está en segundo plano.
function registrar(contenedor, dibujar) {
  const correr = () => {
    const ancho = contenedor.clientWidth;
    if (ancho < 120) return; // aún sin diseño (o un panel oculto): se dibuja cuando tenga ancho
    contenedor.classList.remove("cargando");
    dibujar(ancho);
  };
  dibujos.push(correr);
  let ancho = Math.round(contenedor.getBoundingClientRect().width);
  correr();
  new ResizeObserver(([entrada]) => {
    const w = Math.round(entrada.contentRect.width);
    if (w !== ancho) {
      ancho = w;
      correr();
    }
  }).observe(contenedor);
  return correr;
}

temaOscuro.addEventListener("change", () => dibujos.forEach((f) => f()));

function escalaNice(maximo, partes = 4) {
  if (!(maximo > 0)) return { max: 1, ticks: [0, 1] };
  // El paso redondo más pequeño (1, 2, 2,5, 5 o 10 × 10^n) que cubre el máximo en partes + 1 divisiones.
  const mag = 10 ** Math.floor(Math.log10(maximo / partes));
  const paso = [1, 2, 2.5, 5, 10, 20].map((k) => k * mag).find((p) => Math.ceil(maximo / p) <= partes + 1);
  const tope = Math.ceil(maximo / paso) * paso;
  const ticks = [];
  for (let v = 0; v <= tope + paso / 2; v += paso) ticks.push(v);
  return { max: tope, ticks };
}

// Columna con la punta redondeada (4 px) y la base recta.
function columna(x, y, ancho, alto) {
  const r = Math.min(4, alto, ancho / 2);
  const y0 = y + alto;
  return `M${x},${y0}V${y + r}Q${x},${y} ${x + r},${y}H${x + ancho - r}Q${x + ancho},${y} ${x + ancho},${y + r}V${y0}Z`;
}

function escalaHtml(menos, mas, extra) {
  return h(
    "div",
    { class: "escala caption-5" },
    h("span", { texto: menos }),
    h("span", { class: "escala-pasos", "aria-hidden": "true" }, rampa().map((c) => h("span", { style: `background:${c}` }))),
    h("span", { texto: mas }),
    extra ? h("span", { texto: extra }) : null
  );
}

function tablaSimple(contenedor, columnas, filas, alElegir) {
  const tabla = h(
    "table",
    { class: "tabla" },
    h("thead", {}, h("tr", {}, columnas.map((c) => h("th", { scope: "col", class: clasesColumna(c), texto: c.titulo })))),
    h(
      "tbody",
      {},
      filas.map((f) => {
        const tr = h("tr", {}, columnas.map((c) => h("td", { class: clasesColumna(c), texto: c.formato(f) })));
        if (alElegir) activarFila(tr, () => alElegir(f));
        return tr;
      })
    )
  );
  contenedor.replaceChildren(tabla);
}

// "n": número alineado a la derecha; "col-nombre": columna de nombres con ancho mínimo para no partirse.
const clasesColumna = (c) => [c.num ? "n" : null, c.nombre ? "col-nombre" : null].filter(Boolean).join(" ") || null;

function activarFila(tr, accion) {
  tr.classList.add("accionable");
  tr.tabIndex = 0;
  tr.addEventListener("click", accion);
  tr.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      accion();
    }
  });
}

// Barras horizontales en HTML: nombre arriba, barra con el valor en la punta y, si hay, una marca de referencia.
function barrasHtml(contenedor, items, opciones) {
  const { valor, formato, nombre, detalle, referencia, tip, maximo, reserva } = opciones;
  const max = maximo ?? Math.max(...items.map(valor), ...(referencia ? items.map(referencia) : [0]));
  const lista = h(
    "ul",
    { class: "barras" },
    items.map((it) => {
      const v = valor(it);
      const li = h(
        "li",
        { class: "barra-fila", tabindex: 0, "aria-label": `${nombre(it)}: ${formato(v)}${referencia ? `; promedio nacional ${formato(referencia(it))}` : ""}` },
        h("span", { class: "body-5 barra-nombre", texto: nombre(it) }),
        detalle ? h("span", { class: "caption-5 barra-detalle", texto: detalle(it) }) : null,
        h(
          "span",
          { class: "barra-pista", style: reserva ? `--reserva:${reserva}px` : null },
          h("span", { class: "barra-relleno", style: `--f:${max > 0 ? v / max : 0}` }),
          // Si la referencia queda más allá de la barra, el valor se corre para no pisarla.
          referencia && max > 0 && referencia(it) > v ? h("span", { class: "barra-espacio", style: `--f:${(referencia(it) - v) / max}` }) : null,
          h("span", { class: "body-4 barra-valor num", texto: formato(v) }),
          referencia ? h("span", { class: "barra-referencia", style: `--f:${max > 0 ? referencia(it) / max : 0}` }) : null
        )
      );
      if (tip) conTooltip(li, () => tip(it));
      return li;
    })
  );
  contenedor.classList.remove("cargando");
  contenedor.replaceChildren(lista);
}

/* ============================================================== 01 Panorama */
function dibujarAnual(anual, ultimaFirma) {
  const cont = $("#g-anual");
  const ultimo = anual[anual.length - 1];
  const parcial = !(ultimaFirma.getMonth() === 11 && ultimaFirma.getDate() === 31) && ultimo.anio === ultimaFirma.getFullYear();
  const iMax = anual.reduce((im, d, i) => (d.contratos > anual[im].contratos ? i : im), 0);

  registrar(cont, (ancho) => {
    const alto = 280;
    const m = { t: 28, r: 0, b: 28, l: 52 };
    const pw = ancho - m.l - m.r;
    const ph = alto - m.t - m.b;
    const { max, ticks } = escalaNice(anual[iMax].contratos);
    const svg = lienzoSvg(ancho, alto, "Contratos firmados por año");

    for (const t of ticks) {
      const y = m.t + ph - (t / max) * ph;
      s("line", { class: t === 0 ? "eje" : "grid", x1: m.l, x2: ancho - m.r, y1: y, y2: y }, svg);
      texto(svg, { x: m.l - 8, y: y + 4, "text-anchor": "end", class: "eje-texto" }, compacto(t));
    }

    const banda = pw / anual.length;
    const w = Math.min(24, banda * 0.6);
    const cada = banda < 40 ? 2 : 1;
    anual.forEach((d, i) => {
      const x0 = m.l + i * banda;
      const alturaBarra = (d.contratos / max) * ph;
      const esParcial = parcial && i === anual.length - 1;
      const g = s("g", { class: "marca", tabindex: 0, role: "img", "aria-label": `${d.anio}: ${entero(d.contratos)} contratos${esParcial ? " hasta ahora" : ""}` }, svg);
      s("rect", { class: "hit", x: x0 + 1, y: m.t, width: banda - 2, height: ph, rx: 4, fill: "transparent" }, g);
      if (alturaBarra > 0) {
        s("path", { class: "relleno-1", "fill-opacity": esParcial ? 0.55 : null, d: columna(x0 + (banda - w) / 2, m.t + ph - alturaBarra, w, alturaBarra) }, g);
      }
      if ((anual.length - 1 - i) % cada === 0) {
        texto(svg, { x: x0 + banda / 2, y: alto - 8, "text-anchor": "middle", class: "eje-texto" }, String(d.anio));
      }
      conTooltip(g, () => [
        esParcial ? `${d.anio}, hasta el ${diaMes(ultimaFirma)}` : String(d.anio),
        [
          { valor: entero(d.contratos), etiqueta: "contratos" },
          { valor: pct((100 * d.contratos_directa) / d.contratos), etiqueta: "por contratación directa" },
          { valor: pesos(d.valor_total), etiqueta: "valor contratado" },
        ],
      ]);
    });

    // Etiquetas directas selectivas: el año más alto y, si cabe, el último.
    const etiquetar = [iMax];
    if (iMax !== anual.length - 1 && banda >= 72) etiquetar.push(anual.length - 1);
    for (const i of etiquetar) {
      const y = m.t + ph - (anual[i].contratos / max) * ph;
      texto(svg, { x: m.l + i * banda + banda / 2, y: y - 8, "text-anchor": "middle", class: "etiqueta" }, entero(anual[i].contratos));
    }
    cont.replaceChildren(svg);
  });

  $("#n-anual").textContent = parcial
    ? `${ultimo.anio} va hasta el ${fechaCorta(ultimaFirma)} y se muestra más claro. SECOP II publica con unos días de retraso, así que las últimas semanas aún pueden crecer.`
    : "SECOP II publica con unos días de retraso, así que las últimas semanas aún pueden crecer.";

  tablaSimple($("#t-anual"), [
    { titulo: "Año", formato: (d) => String(d.anio) },
    { titulo: "Contratos", num: true, formato: (d) => entero(d.contratos) },
    { titulo: "Contratación directa", num: true, formato: (d) => pct((100 * d.contratos_directa) / d.contratos) },
    { titulo: "Valor contratado", num: true, formato: (d) => pesos(d.valor_total) },
  ], anual);
}

function dibujarCalor(mensual, ultimaFirma) {
  const cont = $("#g-calor");
  const porAnio = new Map();
  for (const d of mensual) {
    if (!porAnio.has(d.anio)) porAnio.set(d.anio, { anio: d.anio, meses: Array(12).fill(null), total: 0 });
    const r = porAnio.get(d.anio);
    r.meses[d.mes - 1] = d.contratos;
    r.total += d.contratos;
  }
  const todos = [...porAnio.values()];
  const filas = todos.filter((r) => r.total >= MIN_CONTRATOS_ANIO_CALOR);
  const omitidos = todos.filter((r) => r.total < MIN_CONTRATOS_ANIO_CALOR).map((r) => r.anio);
  for (const r of filas) {
    r.cuotas = r.meses.map((v) => (v == null ? null : v / r.total));
    r.pico = r.meses.indexOf(Math.max(...r.meses.filter((v) => v != null)));
  }
  // Color por posición (cuantiles): enero de 2026 (casi la mitad de su año) no aplasta el resto de la escala.
  const cuotasOrdenadas = filas.flatMap((r) => r.cuotas.filter((v) => v != null)).sort((a, b) => a - b);
  const posicionCuota = (v) => cuotasOrdenadas.indexOf(v) / Math.max(1, cuotasOrdenadas.length - 1);

  // El mes pico de cada año. Si los años de elección presidencial tienen su pico en enero y los demás
  // no, se dice así (es el efecto de la Ley de Garantías); si no, se describe el mes pico más común.
  const electorales = filas.filter((r) => ANIOS_ELECCION_PRESIDENCIAL.includes(r.anio));
  const otros = filas.filter((r) => !ANIOS_ELECCION_PRESIDENCIAL.includes(r.anio) && r.anio < ultimaFirma.getFullYear());
  const conteo = Array(12).fill(0);
  otros.forEach((r) => conteo[r.pico]++);
  const mesComun = conteo.indexOf(Math.max(...conteo));
  if (electorales.length && electorales.every((r) => r.pico === 0) && otros.every((r) => r.pico !== 0)) {
    const lista = electorales.map((r) => r.anio);
    const anios = `${lista.slice(0, -1).join(", ")} y ${lista[lista.length - 1]}`;
    $("#s-calor").textContent = `En los años de elección presidencial (${anios}) el pico se adelanta a enero, antes de la restricción de la Ley de Garantías. Los demás años el mes con más contratos suele ser ${MESES_LARGOS[mesComun]} (${conteo[mesComun]} de ${otros.length}).`;
  } else if (otros.length) {
    $("#s-calor").textContent = `${oracion(MESES_LARGOS[mesComun])} es el mes con más contratos firmados en ${conteo[mesComun]} de ${otros.length} años.`;
  }

  registrar(cont, (ancho) => {
    const m = { t: 20, l: 44 };
    const gap = 2;
    const filaAlto = 22;
    const celda = (ancho - m.l - gap * 11) / 12;
    const alto = m.t + filas.length * (filaAlto + gap);
    const svg = lienzoSvg(ancho, alto, "Parte de los contratos de cada año firmada en cada mes");
    const corto = celda < 34;

    MESES.forEach((mes, i) => {
      texto(svg, { x: m.l + i * (celda + gap) + celda / 2, y: 12, "text-anchor": "middle", class: "eje-texto" }, corto ? mes.charAt(0).toUpperCase() : mes);
    });

    filas.forEach((r, fi) => {
      const y = m.t + fi * (filaAlto + gap);
      const electoral = ANIOS_ELECCION_PRESIDENCIAL.includes(r.anio);
      texto(svg, { x: m.l - 8, y: y + filaAlto / 2 + 4, "text-anchor": "end", class: electoral ? "etiqueta" : "eje-texto" }, String(r.anio));
      r.meses.forEach((v, mi) => {
        const x = m.l + mi * (celda + gap);
        if (v == null) {
          s("rect", { class: "vacio", x, y, width: celda, height: filaAlto, rx: 2 }, svg);
          return;
        }
        const color = colorRampa(posicionCuota(r.cuotas[mi]));
        const g = s("g", { class: "marca", tabindex: 0, role: "img", "aria-label": `${MESES_LARGOS[mi]} de ${r.anio}: ${pct(100 * r.cuotas[mi])} de los contratos del año, ${entero(v)} contratos` }, svg);
        s("rect", { class: "celda hit", x, y, width: celda, height: filaAlto, rx: 2, fill: color }, g);
        if (mi === r.pico) s("circle", { cx: x + celda / 2, cy: y + filaAlto / 2, r: 3, fill: textoSobre(color), "pointer-events": "none" }, g);
        conTooltip(g, () => [
          `${oracion(MESES_LARGOS[mi])} de ${r.anio}`,
          [
            { valor: pct(100 * r.cuotas[mi]), etiqueta: "de los contratos del año" },
            { valor: entero(v), etiqueta: "contratos" },
          ],
        ]);
      });
    });
    cont.replaceChildren(svg, escalaHtml("Menor parte del año", "Mayor parte del año", "· color por posición · el punto marca el mes más alto de cada año · en negrita, años de elección presidencial"));
  });

  const notas = [];
  if (omitidos.length) notas.push(`No se muestra ${omitidos.join(" ni ")}: SECOP II apenas empezaba y hubo menos de ${entero(MIN_CONTRATOS_ANIO_CALOR)} contratos.`);
  notas.push(`El mes de ${MESES_LARGOS[ultimaFirma.getMonth()]} de ${ultimaFirma.getFullYear()} aún está en curso.`);
  $("#n-calor").textContent = notas.join(" ");

  tablaSimple(
    $("#t-calor"),
    [{ titulo: "Año", formato: (r) => String(r.anio) }, ...MESES.map((mes, i) => ({ titulo: mes, num: true, formato: (r) => entero(r.meses[i]) }))],
    filas
  );
}

function dibujarDirecta(anual) {
  const cont = $("#g-directa");
  const contratos = sumar(anual, "contratos");
  const directos = sumar(anual, "contratos_directa");
  const valor = sumar(anual, "valor_total");
  const valorDirecto = sumar(anual, "valor_directa");
  const nombres = ["Contratación directa", "Otras modalidades"];
  const variables = ["--serie-1", "--serie-2"];
  const filas = [
    { nombre: "Contratos", partes: [directos, contratos - directos], total: contratos, formato: entero },
    { nombre: "Valor contratado", partes: [valorDirecto, valor - valorDirecto], total: valor, formato: pesos },
  ];

  registrar(cont, () => {
    const colores = variables.map(varCss);
    const leyenda = h("ul", { class: "leyenda caption-4" }, nombres.map((n, i) => h("li", {}, h("span", { class: "clave", style: `background:${colores[i]}` }), n)));
    const cuerpo = h(
      "div",
      { class: "segmentada" },
      filas.map((f) =>
        h(
          "div",
          { class: "segmentada-fila" },
          h("p", { class: "title-4", texto: f.nombre }),
          h(
            "div",
            { class: "segmentada-barra", role: "group", "aria-label": f.nombre },
            f.partes.map((v, i) => {
              const cuota = v / f.total;
              const parte = h("div", {
                class: "segmentada-parte caption-3",
                tabindex: 0,
                "aria-label": `${nombres[i]}: ${pct(100 * cuota)}, ${f.formato(v)}`,
                style: `flex:${cuota} 1 0;background:${colores[i]};color:${textoSobre(colores[i])}`,
                texto: pct(100 * cuota),
              });
              conTooltip(parte, () => [f.nombre, [{ valor: pct(100 * cuota), etiqueta: nombres[i].toLowerCase(), color: colores[i] }, { valor: f.formato(v) }]]);
              return parte;
            })
          )
        )
      ),
      h("p", { class: "caption-5 texto-3", texto: `La contratación directa es el ${pct((100 * directos) / contratos)} de los contratos, pero solo el ${pct((100 * valorDirecto) / valor)} del valor: son contratos más pequeños. Incluye la contratación directa con ofertas, igual que la alerta.` })
    );
    cont.replaceChildren(leyenda, cuerpo);
    // Una etiqueta que no cabe en su parte no se recorta: se quita y el valor queda en el tooltip y la tabla.
    requestAnimationFrame(() => cont.querySelectorAll(".segmentada-parte").forEach((p) => {
      if (p.scrollWidth > p.clientWidth) p.textContent = "";
    }));
  });

  tablaSimple($("#t-directa"), [
    { titulo: "Medida", formato: (f) => f.nombre },
    { titulo: "Contratación directa", num: true, formato: (f) => `${f.formato(f.partes[0])} (${pct((100 * f.partes[0]) / f.total)})` },
    { titulo: "Otras modalidades", num: true, formato: (f) => `${f.formato(f.partes[1])} (${pct((100 * f.partes[1]) / f.total)})` },
  ], filas);
}

function dibujarSectores(sectores) {
  const top = sectores.filter((d) => d.valor_total != null).slice(0, 10);
  barrasHtml($("#g-sectores"), top, {
    valor: (d) => d.valor_total,
    formato: pesos,
    nombre: (d) => oracion(d.sector),
    detalle: (d) => `${entero(d.contratos)} contratos · ${pct((100 * d.contratos_directa) / d.contratos)} por contratación directa`,
    tip: (d) => [oracion(d.sector), [{ valor: pesos(d.valor_total), etiqueta: "valor contratado" }, { valor: entero(d.contratos), etiqueta: "contratos" }]],
  });
  tablaSimple($("#t-sectores"), [
    { titulo: "Sector", nombre: true, formato: (d) => oracion(d.sector) },
    { titulo: "Contratos", num: true, formato: (d) => entero(d.contratos) },
    { titulo: "Contratación directa", num: true, formato: (d) => pct((100 * d.contratos_directa) / d.contratos) },
    { titulo: "Valor contratado", num: true, formato: (d) => pesos(d.valor_total) },
  ], sectores);
}

/* ============================================================== 02 Alertas */
const estado = { depto: null, metrica: "pct_contratos_con_alerta", orden: "posicion_ranking", asc: true, mostrar: FILAS_RANKING, focoMapa: null };
let redibujarMapa = () => {};
let entidades = [];
let ranking = [];
let nacional = {};

const METRICAS_MAPA = {
  pct_contratos_con_alerta: { nombre: "Contratos con alguna alerta", corto: (v) => pct(v, 0), largo: (v) => pct(v) },
  pct_contratacion_directa: { nombre: "Contratación directa", corto: (v) => pct(v, 0), largo: (v) => pct(v) },
  contratos: { nombre: "Contratos", corto: compacto, largo: entero },
};

function teselaDe(nombre) {
  const n = normalizar(nombre);
  return TESELAS.find(([k]) => n === k || n.startsWith(`${k} `) || n.startsWith(`${k},`));
}

function dibujarMapa(deptos) {
  const cont = $("#g-mapa");
  const porClave = new Map();
  for (const d of deptos) {
    const t = teselaDe(d.departamento);
    if (t) porClave.set(t[0], d);
  }
  const fuera = deptos.filter((d) => !teselaDe(d.departamento));

  redibujarMapa = registrar(cont, (ancho) => {
    const met = METRICAS_MAPA[estado.metrica];
    const valores = [...porClave.values()].map((d) => d[estado.metrica]).filter((v) => v != null).sort((a, b) => a - b);
    const posicion = (v) => (valores.length > 1 ? valores.indexOf(v) / (valores.length - 1) : 0.5);
    const gap = 4;
    const lado = Math.min(60, Math.floor((ancho - gap * 6) / 7));
    const anchoMapa = 7 * lado + 6 * gap;
    const alto = 8 * lado + 7 * gap;
    const svg = lienzoSvg(anchoMapa + 8, alto + 8, `Mapa de departamentos: ${met.nombre.toLowerCase()}`);
    const capa = s("g", { transform: "translate(4,4)" }, svg);

    for (const [clave, sigla, c, f] of TESELAS) {
      const d = porClave.get(clave);
      const x = c * (lado + gap);
      const y = f * (lado + gap);
      if (!d) {
        s("rect", { class: "vacio", x, y, width: lado, height: lado, rx: 4 }, capa);
        continue;
      }
      const v = d[estado.metrica];
      const color = colorRampa(posicion(v));
      const tinta = textoSobre(color);
      const elegido = estado.depto === d.departamento;
      const g = s("g", { class: "marca", tabindex: 0, role: "button", "data-clave": clave, "aria-pressed": String(elegido), "aria-label": `${titulo(d.departamento)}: ${met.largo(v)}` }, capa);
      s("rect", { class: "celda hit", x, y, width: lado, height: lado, rx: 4, fill: color }, g);
      const conValor = lado >= 40;
      texto(g, { x: x + lado / 2, y: y + lado / 2 + (conValor ? -2 : 4), "text-anchor": "middle", fill: tinta, "font-size": 12, "font-weight": 600, "pointer-events": "none" }, sigla);
      if (conValor) texto(g, { x: x + lado / 2, y: y + lado / 2 + 13, "text-anchor": "middle", fill: tinta, "font-size": 12, "pointer-events": "none" }, met.corto(v));
      if (elegido) s("rect", { class: "seleccion", x: x - 3, y: y - 3, width: lado + 6, height: lado + 6, rx: 7, "pointer-events": "none" }, g);
      const elegir = () => {
        estado.focoMapa = clave;
        seleccionarDepto(elegido ? null : d.departamento);
      };
      g.addEventListener("click", elegir);
      g.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          elegir();
        }
      });
      conTooltip(g, () => [
        titulo(d.departamento),
        [
          { valor: pct(d.pct_contratos_con_alerta), etiqueta: "contratos con alguna alerta" },
          { valor: pct(d.pct_contratacion_directa), etiqueta: "contratación directa" },
          { valor: entero(d.contratos), etiqueta: "contratos" },
          { valor: pesos(d.valor_total), etiqueta: "valor contratado" },
        ],
      ]);
    }
    const envoltura = h("div", { style: "display:flex;justify-content:center" });
    envoltura.append(svg);
    cont.replaceChildren(envoltura, escalaHtml(met.largo(valores[0]), met.largo(valores[valores.length - 1]), "· el color va por posición, de menor a mayor"));
    if (estado.focoMapa) {
      const foco = cont.querySelector(`[data-clave="${estado.focoMapa}"]`);
      estado.focoMapa = null;
      foco?.focus({ preventScroll: true });
    }
  });

  $("#n-mapa").textContent = fuera.length
    ? `${entero(sumar(fuera, "contratos"))} contratos sin departamento definido no aparecen en el mapa.`
    : "";

  for (const b of document.querySelectorAll("#metricas-mapa button")) {
    b.addEventListener("click", () => {
      estado.metrica = b.dataset.metrica;
      document.querySelectorAll("#metricas-mapa button").forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
      redibujarMapa();
    });
  }

  tablaSimple($("#t-mapa"), [
    { titulo: "Departamento", nombre: true, formato: (d) => titulo(d.departamento) },
    { titulo: "Contratos", num: true, formato: (d) => entero(d.contratos) },
    { titulo: "Con alguna alerta", num: true, formato: (d) => pct(d.pct_contratos_con_alerta) },
    { titulo: "Contratación directa", num: true, formato: (d) => pct(d.pct_contratacion_directa) },
    { titulo: "Valor contratado", num: true, formato: (d) => pesos(d.valor_total) },
  ], [...deptos].sort((a, b) => b.contratos - a.contratos));
}

function dibujarAlertasNacionales(totales) {
  const items = ALERTAS.map(([k, nombre, desc]) => ({ k, nombre, desc, v: nacional[k], n: totales[`contratos_${k}`] })).sort((a, b) => b.v - a.v);
  barrasHtml($("#g-alertas"), items, {
    valor: (it) => it.v,
    formato: (v) => pct(v),
    nombre: (it) => it.nombre,
    detalle: (it) => it.desc,
    reserva: 72,
    tip: (it) => [it.nombre, [{ valor: pct(it.v), etiqueta: "de los contratos" }, { valor: entero(it.n), etiqueta: "contratos" }]],
  });
  tablaSimple($("#t-alertas-tabla"), [
    { titulo: "Alerta", nombre: true, formato: (it) => it.nombre },
    { titulo: "Qué marca", formato: (it) => it.desc },
    { titulo: "Contratos", num: true, formato: (it) => entero(it.n) },
    { titulo: "Porcentaje", num: true, formato: (it) => pct(it.v) },
  ], items);
}

function seleccionarDepto(depto) {
  estado.depto = depto;
  estado.mostrar = FILAS_RANKING;
  $("#f-depto").value = depto ?? "";
  redibujarMapa();
  dibujarRanking();
}

/* ---------------------------------------------- Buscador y ficha */
function buscar(consulta) {
  const q = normalizar(consulta.trim());
  if (q.length < 3) return null;
  const palabras = q.split(/\s+/).filter(Boolean);
  const esNit = /^\d+$/.test(q);
  return entidades
    .filter((e) => (esNit && e._nit.startsWith(q)) || palabras.every((p) => e._n.includes(p)))
    .sort((a, b) => b.contratos - a.contratos);
}

function configurarBuscador() {
  const entrada = $("#q");
  const lista = $("#resultados");
  const ayuda = $("#ayuda-q");
  const ayudaInicial = ayuda.textContent;
  let espera = 0;
  let ultimos = [];

  const pintar = () => {
    const encontrados = buscar(entrada.value);
    lista.replaceChildren();
    $("#sugerencias").hidden = entrada.value.trim().length > 0;
    if (encontrados == null) {
      ultimos = [];
      ayuda.textContent = ayudaInicial;
      return;
    }
    ultimos = encontrados;
    if (!encontrados.length) {
      ayuda.textContent = "Sin resultados.";
      lista.append(h("li", { class: "vacio-mensaje body-6", texto: `No encontramos entidades con «${entrada.value.trim()}». Revisa la ortografía o busca por NIT.` }));
      return;
    }
    ayuda.textContent = encontrados.length > 8 ? `${entero(encontrados.length)} entidades coinciden; estas son las 8 con más contratos.` : `${entero(encontrados.length)} ${encontrados.length === 1 ? "entidad coincide" : "entidades coinciden"}.`;
    for (const e of encontrados.slice(0, 8)) {
      lista.append(
        h(
          "li",
          {},
          h(
            "button",
            { type: "button", class: "resultado", onclick: null },
            h("span", { class: "body-5", texto: e._nombre }),
            h("span", { class: "caption-5", texto: `${titulo(e.departamento)} · NIT ${e._nit || SD} · ${entero(e.contratos)} contratos` })
          )
        )
      );
      lista.lastChild.firstChild.addEventListener("click", () => mostrarFicha(e));
    }
  };

  entrada.addEventListener("input", () => {
    clearTimeout(espera);
    espera = setTimeout(pintar, 120);
  });
  entrada.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      pintar();
      if (ultimos[0]) mostrarFicha(ultimos[0]);
    } else if (e.key === "Escape") {
      entrada.value = "";
      pintar();
    }
  });

  // Sugerencias: la entidad con más contratos, la de más contratos directos sin causal en la restricción y una de Tunja.
  const sugeridas = [];
  const agregar = (e) => e && !sugeridas.includes(e) && sugeridas.push(e);
  agregar(entidades[0]);
  agregar([...entidades].sort((a, b) => b.ley_sin_excepcion_restriccion - a.ley_sin_excepcion_restriccion)[0]);
  agregar(entidades.find((e) => e._n.includes("TUNJA")));
  $("#sugerencias").replaceChildren(
    h("span", { class: "caption-4 texto-3", texto: "Prueba con:" }),
    ...sugeridas.map((e) => {
      const b = h("button", { type: "button", class: "chip caption-4", texto: e._nombre, title: e._nombre });
      b.addEventListener("click", () => mostrarFicha(e));
      return b;
    })
  );

  entrada.disabled = false;
  $("#s-buscador").textContent = `Escribe el nombre o el NIT. Hay ${entero(entidades.length)} entidades con contratos en SECOP II.`;

  // Enlace directo a una ficha: entidades.html?nit=... (o ?q=... para dejar escrita una búsqueda).
  const parametros = new URLSearchParams(location.search);
  const nit = parametros.get("nit");
  const consulta = parametros.get("q");
  const elegida = nit && entidades.find((e) => e._nit === nit);
  if (elegida) mostrarFicha(elegida);
  else if (nit || consulta) {
    entrada.value = nit || consulta;
    pintar();
  }
}

function miniCifra(tituloTexto, valor, nota) {
  return h(
    "div",
    { class: "mini-cifra" },
    h("p", { class: "title-5 titulo", texto: tituloTexto }),
    h("p", { class: "heading-6", texto: valor }),
    nota ? h("p", { class: "caption-5", texto: nota }) : null
  );
}

function mostrarFicha(e) {
  const ficha = $("#ficha");
  const enRanking = e.posicion_ranking != null;
  const alertas = h("div");
  barrasHtml(
    alertas,
    ALERTAS.map(([k, nombre, desc]) => ({ nombre, desc, n: e[`contratos_${k}`], v: e.contratos ? (100 * e[`contratos_${k}`]) / e.contratos : 0, ref: nacional[k] })),
    {
      valor: (it) => it.v,
      formato: (v) => pct(v),
      nombre: (it) => it.nombre,
      referencia: (it) => it.ref,
      maximo: 100,
      reserva: 72,
      tip: (it) => [
        it.nombre,
        [
          { valor: pct(it.v), etiqueta: `esta entidad, ${entero(it.n)} contratos`, color: varCss("--serie-1") },
          { valor: pct(it.ref), etiqueta: "promedio nacional", color: varCss("--referencia") },
        ],
      ],
    }
  );

  const leySinDatos = !e.ley_sin_excepcion_2025 && !e.ley_sin_excepcion_antes && !e.ley_sin_excepcion_restriccion;
  const volver = h("button", { type: "button", class: "boton-secundario button-sm", texto: "Buscar otra entidad" });
  volver.addEventListener("click", () => {
    const q = $("#q");
    q.focus();
    q.select();
  });

  ficha.replaceChildren(
    h(
      "header",
      { class: "ficha-cabecera" },
      h("p", { class: "caption-3", style: "color:var(--marca-texto)", texto: "Ficha de la entidad" }),
      h("h4", { class: "heading-5", texto: e._nombre }),
      h("p", { class: "caption-2", texto: `${titulo(e.departamento)} · NIT ${e._nit || SD}` })
    ),
    h(
      "div",
      { class: "mini-cifras" },
      miniCifra("Contratos", entero(e.contratos)),
      miniCifra("Valor contratado", pesos(e.valor_total)),
      miniCifra("Con al menos una alerta", pct(e.pct_contratos_con_alerta), `${entero(e.contratos_con_alerta)} contratos`),
      miniCifra(
        "Puesto en el ranking",
        enRanking ? `${entero(e.posicion_ranking)} de ${entero(ranking.length)}` : "Sin puesto",
        enRanking ? "1 es la de mayor porcentaje con alerta" : "tiene menos de 20 contratos"
      )
    ),
    e.pct_valor_mayor_contratista != null
      ? h("p", { class: "aviso body-6", texto: `Un solo contratista se lleva el ${pct(e.pct_valor_mayor_contratista)} del valor que contrata esta entidad.` })
      : null,
    h(
      "section",
      { class: "ficha-bloque", "aria-label": "Alertas de la entidad" },
      h("h5", { class: "title-3", texto: "Porcentaje de sus contratos con cada alerta" }),
      h(
        "ul",
        { class: "leyenda caption-4" },
        h("li", {}, h("span", { class: "clave", style: "background:var(--serie-1)" }), "Esta entidad"),
        h("li", {}, h("span", { class: "clave-tick" }), "Promedio nacional")
      ),
      alertas
    ),
    h(
      "section",
      { class: "ficha-bloque", "aria-label": "Ley de Garantías" },
      h("h5", { class: "title-3", texto: "Ley de Garantías: contratos directos sin causal de excepción" }),
      leySinDatos
        ? h("p", { class: "body-6 texto-2", texto: "No firmó contratos directos sin causal de excepción en estos periodos." })
        : h(
            "div",
            { class: "mini-cifras" },
            miniCifra("Mismo mes de 2025", entero(e.ley_sin_excepcion_2025), "31 dic. 2024 a 30 ene. 2025"),
            miniCifra("Mes antes de la restricción", entero(e.ley_sin_excepcion_antes), "31 dic. 2025 a 30 ene. 2026"),
            miniCifra("Durante la restricción", entero(e.ley_sin_excepcion_restriccion), "31 ene. a 21 jun. 2026")
          )
    ),
    h("div", {}, volver)
  );
  ficha.hidden = false;
  ficha.scrollIntoView({ behavior: reducirMovimiento.matches ? "auto" : "smooth", block: "start" });
  ficha.focus({ preventScroll: true });
  // La dirección queda apuntando a esta ficha, para compartirla.
  if (e._nit) history.replaceState(null, "", `?nit=${encodeURIComponent(e._nit)}`);
  document.title = `${e._nombre} · Vigilancia SECOP`;
}

// Desde otras páginas (ranking, Ley de Garantías) se abre la ficha en la página de entidades.
function irAFicha(e) {
  location.href = e._nit ? `entidades.html?nit=${encodeURIComponent(e._nit)}` : `entidades.html?q=${encodeURIComponent(e._nombre)}`;
}

/* ---------------------------------------------- Ranking */
const COLUMNAS_RANKING = [
  { clave: "posicion_ranking", titulo: "Puesto", num: true, formato: (e) => entero(e.posicion_ranking) },
  { clave: "_nombre", titulo: "Entidad", formato: (e) => e._nombre },
  { clave: "departamento", titulo: "Departamento", formato: (e) => titulo(e.departamento) },
  { clave: "contratos", titulo: "Contratos", num: true, formato: (e) => entero(e.contratos) },
  { clave: "pct_contratos_con_alerta", titulo: "Con alerta", num: true, formato: (e) => pct(e.pct_contratos_con_alerta) },
  { clave: "pct_contratacion_directa", titulo: "Directa", num: true, formato: (e) => pct(e.pct_contratacion_directa) },
  { clave: "pct_valor_mayor_contratista", titulo: "Mayor contratista", num: true, formato: (e) => pct(e.pct_valor_mayor_contratista) },
];

function dibujarRanking() {
  const { orden, asc } = estado;
  const lista = ranking
    .filter((e) => !estado.depto || e.departamento === estado.depto)
    .sort((a, b) => {
      const va = a[orden];
      const vb = b[orden];
      if (va == null) return 1;
      if (vb == null) return -1;
      const c = typeof va === "string" ? va.localeCompare(vb, "es") : va - vb;
      return asc ? c : -c;
    });
  const visibles = lista.slice(0, estado.mostrar);

  const cabecera = h(
    "tr",
    {},
    COLUMNAS_RANKING.map((c) => {
      const activa = c.clave === orden;
      const boton = h("button", { type: "button", texto: c.titulo });
      boton.addEventListener("click", () => {
        if (estado.orden === c.clave) estado.asc = !estado.asc;
        else {
          estado.orden = c.clave;
          estado.asc = !c.num || c.clave === "posicion_ranking"; // números: primero los más altos
        }
        dibujarRanking();
        $(`#t-ranking th[data-clave="${c.clave}"] button`)?.focus();
      });
      return h("th", { scope: "col", class: c.num ? "n" : null, "data-clave": c.clave, "aria-sort": activa ? (asc ? "ascending" : "descending") : "none" }, boton);
    })
  );
  const cuerpo = h(
    "tbody",
    {},
    visibles.map((e) => {
      const tr = h("tr", {}, COLUMNAS_RANKING.map((c) => h("td", { class: c.num ? "n" : null, texto: c.formato(e) })));
      activarFila(tr, () => irAFicha(e));
      return tr;
    })
  );
  const tabla = h("table", { class: "tabla" }, h("caption", { class: "solo-lector", texto: "Ranking de entidades por porcentaje de contratos con alerta" }), h("thead", {}, cabecera), cuerpo);
  $("#t-ranking").replaceChildren(
    visibles.length ? tabla : h("p", { class: "vacio-mensaje body-6", style: "margin:0", texto: "Ninguna entidad de este departamento tiene 20 o más contratos." })
  );
  $("#ranking-cuenta").textContent = `Mostrando ${entero(visibles.length)} de ${entero(lista.length)} entidades${estado.depto ? ` de ${titulo(estado.depto)}` : ""}.`;
  $("#ranking-mas").hidden = visibles.length >= lista.length;
}

function configurarRanking(deptos) {
  const select = $("#f-depto");
  for (const d of [...deptos].sort((a, b) => titulo(a.departamento).localeCompare(titulo(b.departamento), "es"))) {
    select.append(h("option", { value: d.departamento, texto: titulo(d.departamento) }));
  }
  select.disabled = false;
  select.addEventListener("change", () => seleccionarDepto(select.value || null));
  $("#ranking-mas").addEventListener("click", () => {
    estado.mostrar += FILAS_RANKING;
    dibujarRanking();
  });
  dibujarRanking();
}

/* ============================================================== 03 Ley de Garantías */
function semanas(diario) {
  const primero = fecha(diario[0].fecha_firma);
  const ultimo = fecha(diario[diario.length - 1].fecha_firma);
  const mapa = new Map();
  for (const d of diario) {
    const f = fecha(d.fecha_firma);
    const lunes = new Date(f.getFullYear(), f.getMonth(), f.getDate() - ((f.getDay() + 6) % 7));
    const k = claveDia(lunes);
    if (!mapa.has(k)) mapa.set(k, { fecha: lunes, sin: 0, con: 0 });
    const r = mapa.get(k);
    r.sin += d.directa_sin_excepcion;
    r.con += d.directa_exceptuada;
  }
  // Solo semanas completas dentro de la ventana de datos.
  return [...mapa.values()]
    .sort((a, b) => a.fecha - b.fecha)
    .filter((r) => r.fecha >= primero && new Date(r.fecha.getFullYear(), r.fecha.getMonth(), r.fecha.getDate() + 6) <= ultimo);
}

function dibujarLey(diario, periodos) {
  const p = Object.fromEntries(periodos.map((r) => [r.periodo.slice(0, 1), r]));
  const antes = p["1"]?.directa_sin_excepcion;
  const previo = p["0"]?.directa_sin_excepcion;
  llenar("ley-antes", entero(antes));
  llenar("ley-2025", entero(previo));
  llenar("ley-veces", previo ? `${nf1.format(antes / previo)} veces` : SD);
  llenar("ley-durante", entero(p["2"]?.directa_sin_excepcion));

  const sem = semanas(diario);
  const series = [
    { clave: "sin", nombre: "Sin causal de excepción", variable: "--serie-2", clase: "2" },
    { clave: "con", nombre: "Con causal de excepción", variable: "--serie-1", clase: "1" },
  ];
  const desde = fecha(RESTRICCION.desde);
  const hasta = fecha(RESTRICCION.hasta);
  const iPico = sem.reduce((im, r, i) => (r.sin > sem[im].sin ? i : im), 0);
  const cont = $("#g-ley");

  registrar(cont, (ancho) => {
    const alto = 320;
    const m = { t: 28, r: 12, b: 28, l: 52 };
    const pw = ancho - m.l - m.r;
    const ph = alto - m.t - m.b;
    const t0 = sem[0].fecha.getTime();
    const t1 = sem[sem.length - 1].fecha.getTime();
    const X = (f) => m.l + ((f.getTime() - t0) / (t1 - t0)) * pw;
    const { max, ticks } = escalaNice(Math.max(...sem.map((r) => Math.max(r.sin, r.con))));
    const Y = (v) => m.t + ph - (v / max) * ph;
    const svg = lienzoSvg(ancho, alto, "Contratos directos por semana, con y sin causal de excepción");

    const xb0 = Math.max(m.l, X(desde));
    const xb1 = Math.min(m.l + pw, X(hasta));
    s("rect", { class: "banda", x: xb0, y: m.t, width: Math.max(0, xb1 - xb0), height: ph }, svg);
    if (xb1 - xb0 > 72) texto(svg, { x: xb0 + 8, y: m.t + ph - 8, class: "etiqueta-2" }, "Restricción");

    for (const t of ticks) {
      const y = Y(t);
      s("line", { class: t === 0 ? "eje" : "grid", x1: m.l, x2: m.l + pw, y1: y, y2: y }, svg);
      texto(svg, { x: m.l - 8, y: y + 4, "text-anchor": "end", class: "eje-texto" }, compacto(t));
    }

    const cadaMeses = pw < 520 ? 6 : 3;
    for (let f = new Date(sem[0].fecha.getFullYear(), sem[0].fecha.getMonth() + 1, 1); f <= sem[sem.length - 1].fecha; f = new Date(f.getFullYear(), f.getMonth() + 1, 1)) {
      if (f.getMonth() % cadaMeses !== 0) continue;
      const x = X(f);
      s("line", { class: "eje", x1: x, x2: x, y1: m.t + ph, y2: m.t + ph + 4 }, svg);
      texto(svg, { x, y: alto - 8, "text-anchor": "middle", class: "eje-texto" }, `${MESES[f.getMonth()]} ${f.getFullYear()}`);
    }

    for (const se of series) {
      const d = sem.map((r, i) => `${i ? "L" : "M"}${X(r.fecha).toFixed(1)},${Y(r[se.clave]).toFixed(1)}`).join("");
      s("path", { d, class: `linea-${se.clase}`, fill: "none", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    }

    // Etiquetas directas al final de cada línea, solo si no chocan.
    const fin = sem[sem.length - 1];
    const yFin = series.map((se) => Y(fin[se.clave]));
    if (Math.abs(yFin[0] - yFin[1]) >= 16) {
      series.forEach((se, i) => texto(svg, { x: m.l + pw, y: yFin[i] - 8, "text-anchor": "end", class: "etiqueta-2" }, se.clave === "sin" ? "Sin causal" : "Con causal"));
    }

    // El pico, anotado.
    const xp = X(sem[iPico].fecha);
    const yp = Y(sem[iPico].sin);
    s("circle", { cx: xp, cy: yp, r: 4, class: "relleno-2 anillo-superficie" }, svg);
    const aLaDerecha = xp < m.l + pw * 0.6;
    texto(svg, { x: aLaDerecha ? xp + 10 : xp - 10, y: Math.max(m.t + 12, yp + 4), "text-anchor": aLaDerecha ? "start" : "end", class: "etiqueta" }, `${entero(sem[iPico].sin)} en la semana del ${diaMes(sem[iPico].fecha)}`);

    // Cursor que sigue al puntero o a las flechas del teclado.
    const cursor = s("line", { class: "cursor", y1: m.t, y2: m.t + ph, visibility: "hidden" }, svg);
    const puntos = series.map((se) => s("circle", { r: 4, class: `relleno-${se.clase} anillo-superficie`, visibility: "hidden", "pointer-events": "none" }, svg));
    const plano = s("rect", { class: "plano", x: m.l, y: m.t, width: pw, height: ph, fill: "transparent", tabindex: 0, role: "img", "data-tip": "", "aria-label": "Contratos directos por semana. Usa las flechas izquierda y derecha para recorrer las semanas." }, svg);
    s("rect", { class: "foco-plano", x: m.l, y: m.t, width: pw, height: ph, rx: 4, fill: "none", "pointer-events": "none" }, svg);
    let indice = null;

    const mover = (i, cx, cy) => {
      indice = i;
      const r = sem[i];
      const x = X(r.fecha);
      cursor.setAttribute("x1", x);
      cursor.setAttribute("x2", x);
      cursor.setAttribute("visibility", "visible");
      series.forEach((se, k) => {
        puntos[k].setAttribute("cx", x);
        puntos[k].setAttribute("cy", Y(r[se.clave]));
        puntos[k].setAttribute("visibility", "visible");
      });
      const enRestriccion = r.fecha >= desde && r.fecha <= hasta;
      tooltip.mostrar(
        `Semana del ${fechaCorta(r.fecha)}${enRestriccion ? " · restricción" : ""}`,
        series.map((se) => ({ valor: entero(r[se.clave]), etiqueta: se.nombre.toLowerCase(), color: varCss(se.variable) })),
        cx,
        cy
      );
    };
    const masCercano = (clientX) => {
      const t = t0 + ((clientX - svg.getBoundingClientRect().left - m.l) / pw) * (t1 - t0);
      let mejor = 0;
      sem.forEach((r, i) => {
        if (Math.abs(r.fecha - t) < Math.abs(sem[mejor].fecha - t)) mejor = i;
      });
      return mejor;
    };
    const salir = () => {
      cursor.setAttribute("visibility", "hidden");
      puntos.forEach((p) => p.setAttribute("visibility", "hidden"));
      tooltip.ocultar();
    };
    const enTeclado = (i) => {
      const caja = svg.getBoundingClientRect();
      mover(i, caja.left + X(sem[i].fecha), caja.top + Y(sem[i].sin));
    };
    plano.addEventListener("pointermove", (e) => mover(masCercano(e.clientX), e.clientX, e.clientY));
    plano.addEventListener("pointerdown", (e) => mover(masCercano(e.clientX), e.clientX, e.clientY));
    plano.addEventListener("pointerleave", (e) => {
      if (e.pointerType === "mouse") salir();
    });
    plano.addEventListener("focus", () => enTeclado(indice ?? iPico));
    plano.addEventListener("blur", salir);
    plano.addEventListener("keydown", (e) => {
      const pasos = { ArrowLeft: -1, ArrowRight: 1 };
      if (e.key in pasos) {
        e.preventDefault();
        enTeclado(Math.min(sem.length - 1, Math.max(0, (indice ?? iPico) + pasos[e.key])));
      } else if (e.key === "Home" || e.key === "End") {
        e.preventDefault();
        enTeclado(e.key === "Home" ? 0 : sem.length - 1);
      }
    });

    cont.replaceChildren(svg);
  });

  $("#n-ley").textContent = `Semanas de lunes a domingo, del ${fechaCorta(sem[0].fecha)} al ${fechaCorta(new Date(sem[sem.length - 1].fecha.getFullYear(), sem[sem.length - 1].fecha.getMonth(), sem[sem.length - 1].fecha.getDate() + 6))}. Las causales de excepción se reconocen por la justificación publicada y por el tipo de entidad; dos causales de la ley no se pueden detectar con los datos.`;

  tablaSimple($("#t-ley"), [
    { titulo: "Semana del", formato: (r) => fechaCorta(r.fecha) },
    { titulo: "Sin causal de excepción", num: true, formato: (r) => entero(r.sin) },
    { titulo: "Con causal de excepción", num: true, formato: (r) => entero(r.con) },
  ], sem);

  const top = [...entidades].filter((e) => e.ley_sin_excepcion_restriccion > 0).sort((a, b) => b.ley_sin_excepcion_restriccion - a.ley_sin_excepcion_restriccion).slice(0, 10);
  tablaSimple($("#t-ley-entidades"), [
    { titulo: "Entidad", nombre: true, formato: (e) => e._nombre },
    { titulo: "Departamento", formato: (e) => titulo(e.departamento) },
    { titulo: "Sin causal", num: true, formato: (e) => entero(e.ley_sin_excepcion_restriccion) },
    { titulo: "Con causal", num: true, formato: (e) => entero(e.ley_exceptuados_restriccion) },
    { titulo: "Mes antes, sin causal", num: true, formato: (e) => entero(e.ley_sin_excepcion_antes) },
  ], top, irAFicha);
}

/* ============================================================== Cifras */
function llenar(clave, valor) {
  document.querySelectorAll(`[data-dato="${clave}"]`).forEach((n) => {
    n.textContent = valor;
  });
}

const CLAVES_TOTALES = ["contratos", "valor_total", "contratos_con_alerta", "contratos_contratacion_directa", "contratos_valor_no_confiable", ...ALERTAS.map(([k]) => `contratos_${k}`)];

function textoExportacion(meta) {
  const generado = new Date(meta.generado);
  const hora = generado.toLocaleTimeString("es-CO", { hour: "numeric", minute: "2-digit" });
  return `La última exportación fue el ${fechaCorta(generado)} a las ${hora}: Athena leyó ${nf1.format(meta.mb_escaneados_athena)} MB y tardó ${nf1.format(meta.segundos)} s.`;
}

// Inicio: la cifra grande y el número clave de cada página.
function llenarInicio({ meta, resumen, ley_periodos }, totales) {
  llenar("contratos", entero(resumen.contratos));
  llenar("ultima-firma", fechaCorta(fecha(resumen.ultima_fecha_firma)));
  llenar("valor", `$${nf1.format(totales.valor_total / 1e12)} billones`);
  llenar("pct-alerta", pct((100 * totales.contratos_con_alerta) / totales.contratos));
  llenar("pct-directa", pct((100 * totales.contratos_contratacion_directa) / totales.contratos));
  llenar("n-entidades", entero(meta.archivos?.entidades?.filas));
  const p = Object.fromEntries(ley_periodos.map((r) => [r.periodo.slice(0, 1), r]));
  const antes = p["1"]?.directa_sin_excepcion;
  const previo = p["0"]?.directa_sin_excepcion;
  llenar("ley-veces", previo ? `${nf1.format(antes / previo)} veces` : SD);
}

/* ============================================================== Menú y pie compartidos */
const NAV = [
  ["inicio", "index.html", "Inicio"],
  ["panorama", "panorama.html", "Panorama"],
  ["alertas", "alertas.html", "Alertas"],
  ["entidades", "entidades.html", "Entidades"],
  ["ley", "ley.html", "Ley de Garantías"],
  ["como", "como-funciona.html", "Cómo funciona"],
];

function enlaceExterno(href, textoEnlace, rel = "noopener") {
  return h("a", { href, rel }, textoEnlace);
}

// El menú y el pie se escriben una sola vez aquí y se insertan en cada página.
function montarMarco(pagina) {
  const enlace = ([clave, href, nombre], extra = {}) => h("a", { href, "aria-current": clave === pagina ? "page" : null, ...extra }, nombre);
  const boton = h("button", { class: "nav-boton", type: "button", "aria-expanded": "false", "aria-controls": "menu-movil", "aria-label": "Abrir menú" }, h("span"), h("span"));
  const nav = h(
    "header",
    { class: "nav-envoltura" },
    h(
      "nav",
      { class: "nav", "aria-label": "Páginas" },
      h("a", { class: "nav-marca title-4", href: "index.html", "aria-current": pagina === "inicio" ? "page" : null }, h("img", { class: "nav-logo", src: "favicon.svg", alt: "", width: 24, height: 24 }), "Vigilancia SECOP"),
      h("ul", { class: "nav-enlaces title-4" }, NAV.slice(1).map((n) => h("li", {}, enlace(n)))),
      boton
    )
  );
  const menu = h("div", { class: "menu-movil", id: "menu-movil", "aria-hidden": "true" }, h("ul", { class: "heading-5" }, NAV.map((n, i) => h("li", { style: `--i:${i}` }, enlace(n, { tabindex: "-1" })))));
  const pie = h(
    "footer",
    { class: "pie" },
    h(
      "div",
      { class: "contenedor pie-rejilla" },
      h(
        "div",
        { class: "pie-bloque" },
        h("p", { class: "title-3", style: "color:var(--texto-1)", texto: "Sistema para la vigilancia ciudadana de la contratación pública en Colombia con datos de SECOP II" }),
        h("p", { class: "body-6", texto: "Andrés Felipe Galeano Téllez · Oscar Esteban Arias López · Juan David Sandoval Bello · Yeikov Jared Ramos Sánchez" }),
        h("p", { class: "body-6", texto: "Docentes: Zalma Valentina Moreno Galeano · Ivan Felipe Mariño Barreto · Julián David Pareja Garzón" }),
        h("p", { class: "body-6", texto: "Proyecto integrador · Facultad de Ingeniería de Datos e Inteligencia Artificial · Universidad Santo Tomás, Tunja · Objetivos de Desarrollo Sostenible 16 y 9" })
      ),
      h(
        "div",
        { class: "pie-bloque" },
        h("p", { class: "body-6" }, "Datos: ", enlaceExterno("https://www.datos.gov.co/d/jbjy-vk9h", "SECOP II, Contratos Electrónicos"), ", Colombia Compra Eficiente. Licencia ", enlaceExterno("https://creativecommons.org/licenses/by-sa/4.0/deed.es", "CC BY-SA 4.0", "noopener license"), ". Se limpiaron, se quitaron duplicados y se resumieron; se comparten con la misma licencia."),
        h("p", { class: "body-6" }, "Código: ", enlaceExterno("https://github.com/AndresF-GaleanoT/secop-lakehouse-aws", "GitHub"), ", licencia ", enlaceExterno("https://www.gnu.org/licenses/agpl-3.0.html", "GNU AGPL 3.0", "noopener license"), "."),
        h("p", { class: "body-6", texto: "Las alertas marcan patrones fuera de lo habitual para priorizar la revisión. No califican conductas." }),
        h("p", { class: "body-6" }, "Datos actualizados el ", h("span", { "data-dato": "actualizado" }, "…"), ". Esta página no usa cookies ni herramientas de rastreo.")
      )
    )
  );
  $("#marco-nav")?.replaceWith(nav, menu);
  $("#marco-pie")?.replaceWith(pie);
}

function configurarMenu() {
  const boton = $(".nav-boton");
  const panel = $("#menu-movil");
  if (!boton || !panel) return;
  const enlacesPanel = [...panel.querySelectorAll("a")];
  const abrir = (si) => {
    boton.setAttribute("aria-expanded", String(si));
    boton.setAttribute("aria-label", si ? "Cerrar menú" : "Abrir menú");
    panel.classList.toggle("abierto", si);
    panel.setAttribute("aria-hidden", String(!si));
    enlacesPanel.forEach((a) => (a.tabIndex = si ? 0 : -1));
    document.body.style.overflow = si ? "hidden" : "";
    if (si) enlacesPanel[0].focus();
  };
  boton.addEventListener("click", () => abrir(boton.getAttribute("aria-expanded") !== "true"));
  enlacesPanel.forEach((a) => a.addEventListener("click", () => abrir(false)));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && boton.getAttribute("aria-expanded") === "true") {
      abrir(false);
      boton.focus();
    }
  });
}

/* ============================================================== Movimiento */
// Las tarjetas suben y aparecen al entrar en pantalla. El contenido nunca se queda oculto: lo que ya se
// ve al cargar aparece de una vez, y si el navegador no avisa intersecciones (pestaña en segundo plano,
// navegador viejo) todo se muestra a los 2,5 s.
function configurarRevelar() {
  const nodos = [...document.querySelectorAll(".revelar")];
  const mostrarTodo = () => nodos.forEach((n) => n.classList.add("visible"));
  if (!("IntersectionObserver" in window)) {
    mostrarTodo();
    return;
  }
  let respondio = false;
  const observador = new IntersectionObserver(
    (entradas) => {
      respondio = true;
      for (const en of entradas) {
        if (en.isIntersecting) {
          en.target.classList.add("visible");
          observador.unobserve(en.target);
        }
      }
    },
    { threshold: 0.08 }
  );
  for (const n of nodos) {
    if (n.getBoundingClientRect().top < innerHeight) n.classList.add("visible");
    else observador.observe(n);
  }
  setTimeout(() => {
    if (!respondio) mostrarTodo();
  }, 2500);
}

// La frase grande del inicio se enciende palabra por palabra al cruzar una línea a 70 % de la pantalla.
function configurarFrase() {
  const p = $("#frase");
  if (!p) return;
  const palabras = p.textContent.trim().split(/\s+/);
  p.replaceChildren(...palabras.flatMap((t, i) => (i < palabras.length - 1 ? [h("span", { class: "palabra", texto: t }), " "] : [h("span", { class: "palabra", texto: t })])));
  const nodos = [...p.querySelectorAll(".palabra")];
  if (reducirMovimiento.matches) {
    nodos.forEach((n) => n.classList.add("activa"));
    return;
  }
  let pendiente = false;
  const actualizar = () => {
    pendiente = false;
    const linea = innerHeight * 0.7;
    for (const n of nodos) n.classList.toggle("activa", n.getBoundingClientRect().top < linea);
  };
  addEventListener(
    "scroll",
    () => {
      if (!pendiente) {
        pendiente = true;
        requestAnimationFrame(actualizar);
      }
    },
    { passive: true }
  );
  actualizar();
}

/* ============================================================== Carga por página */
async function cargar(nombre) {
  const r = await fetch(`${RUTA_DATOS}${nombre}.json`);
  if (!r.ok) throw new Error(`${nombre}.json respondió ${r.status}`);
  const j = await r.json();
  if (!j.columnas) return j;
  return j.filas.map((f) => Object.fromEntries(j.columnas.map((c, i) => [c, f[i]])));
}

function mostrarError(error) {
  console.error(error);
  let aviso = $("#error-general");
  if (!aviso) {
    aviso = h("p", { id: "error-general", class: "error-datos body-6", role: "alert" });
    $("main .contenedor")?.prepend(aviso);
  }
  aviso.textContent = "No se pudieron cargar los datos. Recarga la página en unos minutos; si el problema sigue, la exportación semanal pudo fallar.";
  aviso.hidden = false;
  document.querySelectorAll(".cargando").forEach((n) => {
    n.classList.remove("cargando");
    n.replaceChildren(h("p", { class: "error-datos body-6", texto: "Datos no disponibles por ahora." }));
  });
}

// Una sección que falla no tumba las demás.
function seguro(nombre, fn) {
  try {
    fn();
  } catch (error) {
    console.error(`Falló ${nombre}`, error);
  }
}

// Qué archivos de data/ necesita cada página y qué dibuja con ellos.
const PAGINAS = {
  inicio: {
    archivos: ["meta", "resumen", "departamentos", "ley_periodos"],
    iniciar: (d, totales) => seguro("inicio", () => llenarInicio(d, totales)),
  },
  panorama: {
    archivos: ["meta", "resumen", "anual", "mensual", "sectores"],
    iniciar: (d) => {
      const ultimaFirma = fecha(d.resumen.ultima_fecha_firma);
      seguro("anual", () => dibujarAnual(d.anual, ultimaFirma));
      seguro("calor", () => dibujarCalor(d.mensual, ultimaFirma));
      seguro("directa", () => dibujarDirecta(d.anual));
      seguro("sectores", () => dibujarSectores(d.sectores));
    },
  },
  alertas: {
    archivos: ["meta", "departamentos", "entidades"],
    iniciar: (d, totales) => {
      seguro("mapa", () => dibujarMapa(d.departamentos));
      seguro("alertas", () => dibujarAlertasNacionales(totales));
      seguro("ranking", () => configurarRanking(d.departamentos));
    },
  },
  entidades: {
    archivos: ["meta", "departamentos", "entidades"],
    iniciar: () => seguro("buscador", configurarBuscador),
  },
  ley: {
    archivos: ["meta", "ley_diario", "ley_periodos", "entidades"],
    iniciar: (d) => seguro("ley", () => dibujarLey(d.ley_diario, d.ley_periodos)),
  },
  como: {
    archivos: ["meta", "departamentos"],
    iniciar: (d, totales) => {
      llenar("no-confiables", entero(totales.contratos_valor_no_confiable));
      $("#meta-exportacion").textContent = textoExportacion(d.meta);
    },
  },
};

async function iniciar() {
  const pagina = PAGINAS[document.body.dataset.pagina] ? document.body.dataset.pagina : "inicio";
  montarMarco(pagina);
  configurarMenu();
  configurarRevelar();
  configurarFrase();

  const { archivos, iniciar: dibujarPagina } = PAGINAS[pagina];
  let d;
  try {
    const valores = await Promise.all(archivos.map(cargar));
    d = Object.fromEntries(archivos.map((n, i) => [n, valores[i]]));
  } catch (error) {
    mostrarError(error);
    return;
  }

  if (d.resumen) d.resumen = d.resumen[0];
  llenar("actualizado", fechaCorta(new Date(d.meta.generado)));

  let totales = {};
  if (d.departamentos) {
    totales = Object.fromEntries(CLAVES_TOTALES.map((k) => [k, sumar(d.departamentos, k)]));
    nacional = Object.fromEntries(ALERTAS.map(([k]) => [k, (100 * totales[`contratos_${k}`]) / totales.contratos]));
  }
  if (d.entidades) {
    entidades = d.entidades;
    for (const e of entidades) {
      // Algunos nombres traen caracteres de control de la fuente original.
      e._nombre = e.nombre_entidad.replace(/[\u0080-\u009f]/g, " ").replace(/\s+/g, " ").trim();
      e._n = normalizar(e._nombre);
      e._nit = e.nit_entidad == null ? "" : String(e.nit_entidad);
    }
    ranking = entidades.filter((e) => e.posicion_ranking != null);
  }

  dibujarPagina(d, totales);
}

iniciar();
