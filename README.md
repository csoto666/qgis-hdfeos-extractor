# HDF-EOS Explorer

[![pruebas](https://github.com/csoto666/qgis-hdfeos-extractor/actions/workflows/pruebas.yml/badge.svg)](https://github.com/csoto666/qgis-hdfeos-extractor/actions/workflows/pruebas.yml)
[![descargar](https://img.shields.io/github/v/release/csoto666/qgis-hdfeos-extractor?label=descargar%20ZIP)](https://github.com/csoto666/qgis-hdfeos-extractor/releases/latest)
[![plugins.qgis.org](https://img.shields.io/badge/QGIS-plugins.qgis.org-589632)](https://plugins.qgis.org/plugins/hdfeos_extractor/)

Complemento de QGIS para **abrir cubos hiperespectrales HDF-EOS5 y
explorarlos** —enlazando en tiempo real dónde está un píxel, cómo se ve y cómo
responde espectralmente— y para **extraerlos al formato nativo de ENVI** cuando
hay que sacarlos a otro programa.

*A QGIS plugin that opens hyperspectral HDF-EOS5 cubes and explores them,
linking spatial position, image and spectral response in real time; and that
extracts them to ENVI's native format when they have to leave.*

![icono](hdfeos_extractor/icono_explorador.png)

> **Un píxel no es un píxel. Es un espectro.**

---

## Qué hace

- **Clic en un píxel y aparece su firma espectral completa**, directamente
  sobre el HDF-EOS5, sin convertir nada antes.
- **Línea de muestreo** que recorre la escena y resume cada píxel que cruza, y
  **firma media de un área** con su desviación por banda.
- **El cubo hiperespectral dibujado de verdad**: las caras laterales son el
  corte que pasa por la cruz, así que arrastrarla recorre el dato.
- **Composición RGB elegida por longitud de onda**, no por número de banda, así
  que los presets significan lo mismo en cualquier sensor.
- **Bandas malas fuera del análisis**: la `bbl` del archivo, las ventanas de
  vapor de agua y los extremos ruidosos quedan fuera de la media, de la
  desviación y del ángulo espectral, no sólo escondidas del gráfico.
- **Biblioteca de firmas** con nombre, notas, comparación por ángulo espectral,
  guardado en JSON y exportación a CSV.
- **Cada firma sabe dónde se tomó**: dos capas vectoriales con su huella —los
  píxeles como puntos, las áreas como polígonos—, que se mantienen al día
  solas y se exportan a GeoJSON.
- **Nube n-dimensional** de las firmas guardadas, en una ventana aparte que se
  enciende y se apaga: cada píxel de cada firma es un punto, proyectado sobre
  un plano que gira. Dos clases que se tapan en el par de bandas que elegiste
  se separan al girar, y el lazo devuelve ese grupo como una firma nueva.
- **Enviar la vista a QGIS** como capa georreferenciada, y **vincular** la
  navegación del cubo con la del mapa.
- **Algoritmo de Processing «HDF-EOS5 to ENVI»**, por lotes y desde el
  modelador, con longitudes de onda, FWHM, valor de relleno y lista de bandas
  malas.

## Instalación

**Desde el repositorio oficial de QGIS** —la forma recomendada—:
**Complementos → Administrar e instalar complementos**, buscar
*HDF-EOS Explorer* e instalar. Las actualizaciones llegan solas.

**Desde el ZIP**, si preferís una versión concreta: descargá el de
[Releases](https://github.com/csoto666/qgis-hdfeos-extractor/releases/latest) y en QGIS **Complementos → Instalar a
partir de ZIP**. Ese ZIP lo arma el repositorio en cada versión y es el único
archivo pensado para instalar.

**Desde el código fuente**, si querés armarlo vos: `./empaquetar.sh`.

### No uses el botón verde «Code → Download ZIP»

Ese ZIP trae una carpeta raíz llamada `qgis-hdfeos-extractor-main`, y QGIS toma
el nombre de la carpeta como nombre del complemento. Como el plugin vive un
nivel más adentro, QGIS arma un nombre de módulo con barras y guiones —que no
es un identificador válido de Python— y la carga falla:

```
Couldn't load plugin 'qgis-hdfeos-extractor-main/hdfeos_extractor'
ModuleNotFoundError: No module named 'qgis-hdfeos-extractor-main/hdfeos_extractor'
```

Si ya te pasó, borrá la carpeta `qgis-hdfeos-extractor-main` del directorio de
complementos de tu perfil y volvé a instalar como arriba:

```
~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/   (macOS)
~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/                  (Linux)
%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\                     (Windows)
```

**Requisitos.** Probado contra QGIS 3.16 en adelante. El código no usa sintaxis
posterior a Python 3.8, así que funciona en el Python 3.9 que traen las
compilaciones de QGIS para macOS. Compatible con Qt5 y Qt6.

## Primeros pasos

Abrí el panel en **Ráster → HDF-EOS → Explorador hiperespectral**, o con el
icono de la barra de herramientas. Después **Abrir…** y elegí el `.h5`.

```
   .h5  ──►  explorar  ──►  firmas / biblioteca / CSV
              │
              └──►  extraer a ENVI  (sólo si hay que salir a otro programa)
```

### Explorar

| Interacción | Resultado |
|---|---|
| Clic en un píxel | Se dibuja su firma espectral completa y el píxel queda resaltado |
| Arrastrar la **línea X** o la **línea Y** | Fija una columna o una fila y resume el transecto: media, mínimo y máximo por banda |
| Arrastrar un **rectángulo** | Firma media del área, con la desviación por banda como envolvente |
| Modo **Píxeles** | Cada clic suma un píxel; la firma sale del promedio, con su variabilidad |
| Arrastrar sobre el **cubo** | La cruz recorre la escena y las dos caras laterales cambian con ella |
| Clic en un **costado del cubo** | Esa banda pasa a la cara frontal |
| Cambiar **R/G/B** | La imagen se recompone al instante y el gráfico marca esas tres bandas |
| Botón derecho sobre el cubo | Acerca a ese rectángulo; sin arrastrar, o con la rueda, aleja |
| **Ajustar a los datos** | Encuadra lo que tiene dato y deja fuera el relleno y los ceros |
| Pulsar el nombre de una sección | La pliega o la despliega, para darle el alto al cubo |

### Extraer

Algoritmo **HDF-EOS5 to ENVI** en la Caja de herramientas, o el botón
**Extraer…** del panel, con tres salidas seleccionables:

| Salida | Archivo | Contenido |
|---|---|---|
| Cubo | `<prefijo>_cube.dat` + `.hdr` | El cubo en **BIL**, el intercalado que ENVI espera |
| Geolocalización | `<prefijo>_igm.dat` + `.hdr` | IGM de 2 bandas para *Georeference from Input Geometry* |
| Capas auxiliares | `<prefijo>_aux.dat` + `.hdr` | Máscaras, atmósfera y geometría sol-sensor apiladas |

La cabecera del cubo lleva `wavelength`, `fwhm`, `data ignore value` y `bbl`
—con las ventanas de absorción de vapor de agua ya marcadas—, así que MNF, PPI
y el desmezclado espectral no arrastran esas bandas.

```python
import processing
processing.run("hdfeos_extractor:extraer_hdfeos_a_envi", {
    'ENTRADA': '/ruta/escena.h5',
    'CUBO': True, 'IGM': True, 'MASCARAS': True,
    'ATMOSFERA': False, 'GEOMETRIA': False,
    'CARPETA': '/ruta/salida', 'PREFIJO': '',
})
```

### Dónde se tomó cada firma

Cada firma guarda desde siempre la lista completa de píxeles de los que salió.
En **Archivo → Huellas al mapa** esa lista se convierte en geometría y aparecen
dos capas en el proyecto:

| Capa | Qué lleva |
|---|---|
| **Firmas - puntos** | Las firmas de un píxel y las de píxeles sueltos, como punto y multipunto |
| **Firmas - áreas** | Las firmas de un rectángulo, como polígono de su borde exterior |

Dos capas y no una porque casi ninguna herramienta abre una capa de geometría
mixta. Cada huella lleva el **color de su curva** en el gráfico, que es lo que
relaciona el mapa con el perfil espectral sin leer ninguna leyenda, y una tabla
con el nombre, el tipo, el número de píxeles, la fecha, la procedencia, las
notas y el rango espectral.

**Se agregan una vez y se mantienen al día solas**: a partir de ahí cada firma
nueva aparece en el mapa sin volver a pedirlo. Si las quitas del proyecto, el
complemento las suelta y no te las devuelve —quitarlas es una decisión tuya—.

Los píxeles sueltos salen como varios puntos y **no** como su caja envolvente: esa
caja pinta en el mapa hectáreas que nadie midió. Y una firma leída de un CSV
ajeno, que no trae píxeles, se queda fuera y se dice cuántas —inventarle una
posición sería afirmar algo falso—.

**Archivo → Huellas a GeoJSON…** escribe lo mismo en dos archivos,
**reproyectados a longitud/latitud**, que es lo que el formato significa.

### La nube n-dimensional

Un gráfico de dispersión de dos bandas casi siempre miente por omisión: dos
clases que en el espectro completo están clarísimamente separadas pueden caer
una encima de la otra en el par de bandas que elegiste. La separación existe,
pero no en ese plano.

Pulsa **Nube n-D** en la columna de salida. Cada píxel de cada firma guardada
es un punto, coloreado por su firma, y la nube entera se proyecta sobre un
plano que **gira**: el ojo separa grupos en movimiento muchísimo mejor que
quietos. Los radios etiquetados son los ejes de cada banda; uno que apunta
hacia donde se alarga un grupo dice que esa banda es la que lo separa.

| Control | Para qué |
|---|---|
| **Girar** | Arranca la rotación. Con dos bandas no hay nada que girar y el botón se apaga |
| Arrastrar | Gira la nube a mano, para quedarse en una vista concreta |
| **Lazo** | Rodea un grupo y lo devuelve a la biblioteca como una firma nueva, con sus píxeles |
| **Repartir** | Elige N bandas repartidas por todo el espectro: bandas vecinas están casi correlacionadas y diez seguidas son una sola dimensión |
| Clases | Apagar una la saca de la vista sin borrarla; es lo que deja mirar el grupo que quedaba tapado |

El porqué de cada decisión —la rotación, los radios, el submuestreo— está en
[NOTAS.md](NOTAS.md#la-nube-n-dimensional).

> **Si vas a recorrer mucho una misma escena, extraela a ENVI primero.** Un
> HDF5 comprimido obliga a descomprimir trozos enteros por cada espectro; el
> ENVI se abre por memoria mapeada. Medido sobre un Tanager de 426 bandas, el
> mismo gesto pasa de 5 s a 0,004 s.

## Dependencias

**Ninguna obligatoria más allá de lo que trae QGIS.** Usa numpy y GDAL, los dos
incluidos.

| Paquete | Para qué | Si falta |
|---|---|---|
| `h5py` | Acceso más completo a los atributos HDF5 y lectura aleatoria más rápida | GDAL lo reemplaza solo, sin avisar ni fallar |
| `pyqtgraph` | Gráfico espectral con zoom y desplazamiento | Un lienzo propio dibuja lo mismo con QPainter |
| `xarray` | `cube.to_xarray()` | Sólo falla esa función |

Nada se descarga y no se contacta ningún servicio remoto.

## Más adentro

- **[NOTAS.md](NOTAS.md)** — por qué cada cosa está como está: el problema, la
  proyección y de dónde salen las coordenadas, el cubo como vista viva, las
  bandas malas, el rendimiento medido, la arquitectura, Qt5 y Qt6, y cómo se
  publica una versión.
- **[Uso del núcleo sin QGIS](NOTAS.md#uso-del-núcleo-sin-qgis)** — el análisis
  no importa QGIS ni Qt, así que el mismo código corre desde Jupyter.
- **[Historial de versiones](https://github.com/csoto666/qgis-hdfeos-extractor/releases)**.

## Pruebas

```sh
./verificar.sh     # pruebas, estilo, seguridad, Qt6 y demo: lo mismo que el CI
python3 -m pytest  # sólo las pruebas
```

Corren en cada empujón, en **Python 3.9 y 3.12**. Más detalle en
[NOTAS.md](NOTAS.md#pruebas).

## Licencia

GNU GPL v2 o posterior. Ver [LICENSE](LICENSE).

## Autor

Carlo Soto Castro — carlo.soto.castro@gmail.com
