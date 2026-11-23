# Licencia de los datos y de los documentos

El código de este repositorio usa la licencia **GNU AGPL 3.0 o posterior** (archivo [`LICENSE`](LICENSE)).
Los datos y los documentos usan otra licencia, porque vienen de un conjunto de datos abierto que exige
compartir sus adaptaciones en los mismos términos.

## Fuente

**SECOP II, Contratos Electrónicos** (conjunto `jbjy-vk9h`), publicado por la Agencia Nacional de
Contratación Pública, Colombia Compra Eficiente, en el Portal de Datos Abiertos de Colombia:
<https://www.datos.gov.co/d/jbjy-vk9h>. Licencia: Creative Commons Atribución-CompartirIgual 4.0
Internacional (CC BY-SA 4.0), <https://creativecommons.org/licenses/by-sa/4.0/deed.es>.

## Qué se comparte con CC BY-SA 4.0

Todo lo que se obtiene de esos datos, en el repositorio o fuera de él:

- Las capas plata y oro del lakehouse en S3 y los JSON que lee la web (`web/data/`).
- Los resultados y las muestras de `mineria/datos/`, `mineria/resultados/` y `resultados_*.csv`.
- Las figuras (`mineria/figuras/`, `docs/informe_completo/figuras/`), los informes (`informe/`, `docs/`) y
  el texto de la web.

**Excepción:** los íconos de `docs/informe_cloud/iconos/` son los íconos oficiales de arquitectura de
Amazon Web Services. Son de AWS y se usan según sus términos; no tienen la licencia CC BY-SA 4.0.

## Cambios hechos a los datos

Se descargó el histórico desde 2015, se tiparon las columnas, se quitaron los contratos duplicados, se
conservaron 16 de las 91 columnas (los datos personales se quedan sin procesar en la capa bronce), se
excluyeron de las sumas 85 valores imposibles de más de un billón de pesos y se calcularon agregados y
nueve alertas por contrato. Las alertas marcan patrones fuera de lo habitual para priorizar la revisión;
no califican conductas.

## Cómo citar

> Galeano Téllez, A. F., Arias López, O. E., Sandoval Bello, J. D. y Ramos Sánchez, Y. J. (2026).
> *Sistema para la vigilancia ciudadana de la contratación pública en Colombia con datos de SECOP II*.
> Universidad Santo Tomás, Tunja. Datos: SECOP II, Colombia Compra Eficiente, CC BY-SA 4.0.

Quien reutilice estos datos o documentos debe dar crédito a Colombia Compra Eficiente y a los autores,
indicar si hizo cambios y compartir el resultado con la misma licencia CC BY-SA 4.0.
