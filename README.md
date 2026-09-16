# HDF-EOS Explorer

[![pruebas](https://github.com/csoto666/qgis-hdfeos-extractor/actions/workflows/pruebas.yml/badge.svg)](https://github.com/csoto666/qgis-hdfeos-extractor/actions/workflows/pruebas.yml)
[![descargar](https://img.shields.io/github/v/release/csoto666/qgis-hdfeos-extractor?label=descargar%20ZIP)](https://github.com/csoto666/qgis-hdfeos-extractor/releases/latest)

Plugin de QGIS para **abrir cubos hiperespectrales HDF-EOS5 y explorarlos**
—enlazando en tiempo real dónde está un píxel, cómo se ve y cómo responde
espectralmente— y para **extraerlos al formato nativo de ENVI** cuando hay que
sacarlos a otro programa.

*A QGIS plugin that opens hyperspectral HDF-EOS5 cubes and explores them,
linking spatial position, image and spectral response in real time; and that
extracts them to ENVI's native format when they have to leave.*

![icono](hdfeos_extractor/icono_explorador.png)

> **Un píxel no es un píxel. Es un espectro.**

---

## El problema

Un producto hiperespectral moderno llega como un solo contenedor HDF-EOS5 con
el cubo, los arreglos de geolocalización por píxel, las máscaras de calidad y
la geometría sol-sensor adentro. Ahí se rompen dos cosas.

**No se abre.** El software anterior al producto no lo entiende: ENVI 5.0 es
de 2013 y Tanager de 2024, y no existe opción de menú que lea ese contenedor.
Exportarlo como ráster común tira a la basura el metadato espectral, que es
justamente lo que vuelve utilizable un cubo.

**Y cuando se abre, se ve mal.** Un cubo es tres cosas a la vez —un lugar, una
imagen y un espectro— y casi todos los visores muestran una sola. El usuario
ve una composición en falso color, reconoce que *ahí* hay algo distinto, y no
tiene manera de preguntarle a ese píxel por qué.

## Una sola herramienta, una sola línea de trabajo

```
   .h5  ──►  explorar  ──►  firmas / biblioteca / CSV
              │
              └──►  extraer a ENVI  (sólo si hay que salir a otro programa)
```

El cubo se abre **directo del HDF-EOS5**, sin conversión previa. La extracción
a ENVI sigue estando —y sigue siendo un algoritmo de Processing, con lotes y
modelador— pero deja de ser un peaje obligatorio para poder mirar la escena.

### Explorar

| Interacción | Resultado |
|---|---|
| Clic en un píxel | Se extrae y dibuja su firma espectral completa, y el píxel queda resaltado |
| Arrastrar la **línea X** | Fija una columna y resume toda la columna: media, mínimo y máximo por banda, mientras se mueve |
| Arrastrar la **línea Y** | Lo mismo fijando una fila |
| Arrastrar un **rectángulo** | Firma media del área, con la desviación por banda como envolvente sombreada |
| Cambiar **R/G/B** | La imagen se recompone al instante, y el gráfico marca dónde caen esas tres bandas |
| Arrastrar sobre el **cubo** | La cruz recorre la escena y las dos caras laterales cambian con ella |
| Clic en un **costado del cubo** | Esa banda pasa a la cara frontal |
| **Bandas malas** | Las descarta del análisis y las sombrea en el gráfico |
| Botón derecho sobre el cubo | Acerca a ese rectángulo; sin arrastrar, o con la rueda, aleja |
| **Ajustar a los datos** | Encuadra lo que tiene dato y deja fuera el relleno y los ceros |
| Modo **Píxeles** | Cada clic suma un píxel; la firma sale del promedio, con su variabilidad |

### Extraer

Algoritmo **HDF-EOS5 to ENVI** en la Caja de herramientas, con cuatro salidas
seleccionables:

| Salida | Archivo | Contenido |
|---|---|---|
| Cubo | `<prefijo>_cube.dat` + `.hdr` | El cubo en **BIL**, el intercalado que ENVI espera para procesamiento espectral |
| Geolocalización | `<prefijo>_igm.dat` + `.hdr` | IGM de 2 bandas (longitud, latitud) para *Georeference from Input Geometry* |
| Capas auxiliares | `<prefijo>_aux.dat` + `.hdr` | Máscaras, atmósfera y geometría sol-sensor apiladas, con nombres de banda |

La cabecera del cubo lleva `wavelength`, `fwhm`, `data ignore value` y `bbl`
—la lista de bandas malas, con las **ventanas de absorción de vapor de agua ya
marcadas** (1340–1460 y 1790–1960 nm) más los extremos ruidosos del rango—.
Así MNF, PPI y el desmezclado espectral no arrastran esas bandas.

```python
import processing
processing.run("hdfeos_extractor:extraer_hdfeos_a_envi", {
    'ENTRADA': '/ruta/escena.h5',
    'CUBO': True, 'IGM': True, 'MASCARAS': True,
    'ATMOSFERA': False, 'GEOMETRIA': False,
    'CARPETA': '/ruta/salida', 'PREFIJO': '',
})
```

## El cubo no es una ilustración

La vista clásica del cubo hiperespectral —la imagen al frente y el espectro en
los costados— aquí no es un adorno: **las caras laterales son los mismos
transectos que alimentan el gráfico**.

```
cara superior  = get_transect("y", fila)     → (x, λ)
cara derecha   = get_transect("x", columna)  → (y, λ)
```

La diferencia con el cubo de ENVI es que aquel es estático —sus caras son el
borde de la escena— y este no: **las caras son el corte que pasa por la cruz**.
Mover la cruz recorre el cubo de verdad. Es la diferencia entre mirar un cubo
y explorarlo.

Las tres bandas que arman la imagen frontal se dibujan **dentro** de las caras,
así que se ve de qué rebanadas está hecho lo que se está mirando. Y un clic en
un costado lleva esa banda al frente: es el gesto natural frente a un cubo
—se ve una franja rara y uno quiere ver esa banda—.

No hay OpenGL ni biblioteca 3D. La proyección es oblicua y se dibuja con
QPainter aplicando una transformación afín a cada cara.

## Bandas malas

Un cubo hiperespectral siempre trae bandas que no sirven, y arrastrarlas
cuesta dos cosas distintas. La visible es que el gráfico se llena de picos que
tapan la forma de la firma. **La cara es que entran en la media, en la
desviación y en el ángulo espectral como si fueran mediciones**, y ahí ya no se
ven: sólo corren los números.

El plugin las descarta por cuatro criterios, que se combinan y se encienden por
separado:

| Criterio | Qué descarta | Por defecto |
|---|---|---|
| **Lista del archivo** | La `bbl` que trae el propio producto | Activo si el archivo la incluye |
| **Vapor de agua** | 1340–1460 y 1790–1960 nm | Activo |
| **Extremos** | Por debajo de 400 y por encima de 2450 nm | Activo |
| **Rangos propios** | Lo que escribas: `1340-1460, 900` | Vacío |

Una banda sobrevive sólo si ninguno la descarta. En la duda, fuera — que es
además lo que hace el extractor al escribir la `bbl`, así que el explorador y
el ENVI extraído coinciden.

La banda descartada sale como **NaN**, y de ahí en adelante todo el resto lo
ignora solo: el gráfico corta la curva, `nanmean` la saltea, el ángulo
espectral la excluye y el realce del cubo deja de estar sesgado por el ruido de
las ventanas de absorción.

Tres detalles que importan:

- **El gráfico sombrea los tramos descartados.** Sin eso la curva simplemente
  se corta y no se sabe si falta el dato o si el sensor no llega hasta ahí.
- **`get_band` no se enmascara.** La máscara limpia el análisis espectral, no
  impide mirar una banda: quien quiere ver cómo se ve la de 1400 nm tiene
  derecho a verla, en ruido, pero verla.
- **El compositor RGB no cae en una banda descartada.** Un preset que aterriza
  dentro de una ventana de absorción devolvería ruido puro, y la imagen saldría
  con textura que no existe en el terreno —y que alguien interpretaría—.

Sin eje espectral en nanómetros los dos criterios por longitud de onda se
apagan solos: sobre un eje que es el número de banda, «descartar por debajo de
400» borraría el cubo entero.

## Los cuatro modos de navegación

Se ven en el cubo, y cada uno mueve algo distinto:

| Modo | Qué mueve | Qué cambia |
|---|---|---|
| **Píxel** | La cruz entera | El espectro de ese píxel |
| **Línea X** | Sólo la vertical | La **cara derecha** del cubo: el corte de esa columna |
| **Línea Y** | Sólo la horizontal | La **cara superior**: el corte de esa fila |
| **Área** | Un rectángulo | Firma media del área, con su desviación como envolvente |
| **Píxeles** | Un punto por clic | Firma media del conjunto, para muestrear variabilidad |

Funcionan tanto sobre el lienzo de QGIS como **dentro de la vista del cubo**.
Eso último importa: con un HDF-EOS5 abierto directamente no hay capa en el
mapa, así que sobre el lienzo no habría dónde actuar.

## Una sola herramienta: el cubo y el espectro

Son las dos caras del mismo dato —dónde está el píxel y qué mide—, así que
van en el mismo panel, separados por un divisor que se arrastra. El reparto
se **acuesta o se apila** según dónde esté acoplado el panel: al costado de
QGIS, el cubo arriba y el espectro abajo; abajo o flotando, uno al lado del
otro. Con dos pantallas, **Soltar aparte** manda el cubo a su propia ventana;
cerrarla lo devuelve al panel.

## El zoom recalcula el realce

Acercarse no es sólo ver más grande. Una escena sin ortorectificar llega dentro
de un rectángulo mucho más grande que la franja que el sensor recorrió, y el
resto es relleno y ceros. Con el realce calculado sobre la escena entera esos
ceros estiran el rango y el terreno queda aplastado en una banda de grises.

Al acercarse se recalculan **el realce y la escala de color sobre lo visible**,
y la barra de color a la derecha del cubo dice en qué valores está.

## Qt5 y Qt6

QGIS se está moviendo a Qt6, y ahí los enums sin calificar —`Qt.Horizontal`,
`QSizePolicy.Expanding`— dejaron de existir. No fallan al importar: fallan al
abrir el panel, a media construcción de la interfaz.

Todos pasan por un resolutor que prueba la forma calificada primero y deja la
plana de respaldo, así que el mismo código corre en QGIS 3.16 y en Qt6. Dos
comprobaciones lo sostienen, y las dos están en `verificar.sh` y en CI:

- **`tests/test_qt6.py`** lee el árbol sintáctico del complemento entero y
  falla si encuentra un solo enum sin calificar.
- **`comprobar_qt6.py`** construye la interfaz con PyQt6 de verdad y la
  dibuja. Lo que el detector estático no vea, se cae al pintar.

## La proyección: de dónde salen las coordenadas

Es el error más caro de los datos geoespaciales porque no se ve: una capa mal
proyectada se dibuja igual de bien, sólo que en el lugar equivocado. El plugin
lee la georreferencia **del propio archivo** y distingue tres casos, porque
tratarlos igual es justamente el error:

| Caso | De dónde sale | Qué se hace |
|---|---|---|
| **Ortho** | `StructMetadata`, un atributo `GeoTransform`, o los ejes `x`/`y` | Se usa su afín exacta. No se toca ningún píxel |
| **Afín** | `map info` de ENVI, o la geotransformación que traiga GDAL | Se escribe tal cual, con sus términos de rotación |
| **Geometría de sensor** | Las capas de latitud y longitud del HDF-EOS5 | Se reproyecta de verdad, por placa delgada, hacia una rejilla al norte |
| **Sin georreferencia** | — | Se dice. No se inventa un SRC |

El primero es el producto **ortorectificado**, y es el que más despista: no
trae capas de latitud y longitud —no las necesita, ya está puesto sobre una
proyección— así que buscárselas no encuentra nada aunque el producto venga
perfectamente ubicado. Su georreferencia es una afín, y puede estar en tres
sitios según quién escribiera el archivo: el `StructMetadata` de HDF-EOS, un
atributo `GeoTransform`, o dos vectores `x`/`y` con el centro de cada columna
y de cada fila. Se reconocen los tres. Extraer a ENVI la conserva: el cubo
extraído sale con su `map info`.

El segundo caso es el de los productos sin ortorectificar, y no es un detalle:
ahí la relación entre píxel y terreno cambia a lo ancho de la franja, y
**ninguna geotransformación afín la describe**. Escribirla como si la tuviera
deja la escena en coordenadas de píxel, es decir en el golfo de Guinea.

El tercero es deliberado. Una capa sin SRC se ve mal puesta y el usuario lo
entiende; una capa con un SRC inventado se ve bien puesta y está mal, que es
peor. El panel dice en su barra de estado de dónde salieron las coordenadas.

## Enviar la vista a QGIS

**Enviar vista a QGIS** agrega al mapa sólo el RGB que se está viendo,
recortado a la vista actual y con el realce puesto. No carga el cubo: son tres
bandas de 8 bits más una de transparencia, así que el relleno no tapa el mapa
de fondo. Sirve para digitalizar encima o componer un mapa mientras se sigue
midiendo espectros en el cubo, al lado.

## La composición RGB se elige por longitud de onda

No por número de banda. Es lo que vuelve portables los presets: `rojo = 665 nm`
significa lo mismo en Tanager, en PRISMA y en EMIT; `rojo = banda 29` no
significa nada fuera del sensor donde se escribió.

Los presets que el sensor no alcanza no se ofrecen. Un preset SWIR sobre un
cubo que llega a 900 nm no falla: resuelve las tres bandas a la última y
devuelve una imagen gris que el usuario no sabe interpretar.

## Biblioteca espectral

Las firmas se guardan con **procedencia**: de qué escena, de qué píxeles,
cuándo y con qué notas. El vector de reflectancia solo no sirve para nada seis
meses después.

Se pueden renombrar, ocultar, borrar, comparar por **ángulo espectral** (SAM)
y exportar a CSV. El ángulo es la medida correcta entre espectros porque
compara la forma y no la magnitud: la misma cubierta en sombra y al sol da dos
curvas a alturas distintas y con el mismo ángulo.

## Arquitectura

El núcleo está deliberadamente separado del frontend.

```
core/     numpy puro. No importa QGIS ni Qt.
   ↓
vista/    widgets de Qt. No importa QGIS.
   ↓
qgis_ui/  lo que habla con QGIS.
```

No es prolijidad: es lo que permite que el mismo núcleo sirva desde Jupyter o
desde un script, y —más inmediato— que se pueda **probar sin tener QGIS
instalado**.

```
hdfeos_extractor/
  lector.py      HDF-EOS5: descubre el cubo, los metadatos y escribe ENVI
  algoritmo.py   el algoritmo de Processing
  core/
    hdf5.py      el HDF-EOS5 como fuente del explorador, sin pasar por ENVI
    envi.py      cabecera ENVI y lectura por memoria mapeada
    sources.py   las otras fuentes: memoria y GDAL
    cube.py      HyperspectralCube: la API con dimensiones nombradas
    geo.py       conversión mapa ↔ píxel
    rgb.py       composición y realce
    colormap.py  paletas para pintar un plano del cubo
    bandas.py    qué banda entra al análisis y cuál no
    spectral.py  firmas, estadísticas, ángulo espectral
    library.py   biblioteca persistente
```

Las cuatro fuentes cumplen el mismo contrato —`shape`, `wavelengths`,
`read_pixel`, `read_band`, `read_window`, `close`—, y por eso agregar HDF-EOS5
fue llenar un hueco que el diseño ya dejaba y no reescribir el explorador.

### El modelo de datos no asume tres dimensiones

Hacia afuera no se ofrece `cubo[y, x, banda]` sino operaciones con nombre:

```python
cube.get_spectrum(x, y)
cube.get_band(wavelength=665)
cube.get_transect(axis="x", position=80)
cube.get_roi(x0, y0, x1, y1)
```

Hoy el cubo es `C(y, x, λ)`. Mañana puede ser `C(tiempo, λ, y, x)`. La API con
nombre deja esa puerta abierta sin reescribir a los consumidores.

## Dependencias

**Ninguna obligatoria más allá de lo que trae QGIS.** Usa numpy y GDAL, los dos
incluidos.

| Paquete | Para qué | Si falta |
|---|---|---|
| `h5py` | Acceso más completo a los atributos HDF5 y lectura aleatoria más rápida | GDAL lo reemplaza solo, sin avisar ni fallar |
| `pyqtgraph` | Gráfico espectral con zoom y desplazamiento | Un lienzo propio dibuja lo mismo con QPainter |
| `xarray` | `cube.to_xarray()` | Sólo falla esa función |
| `rasterio` | — | No se usa. GDAL hace lo mismo y sí viene con QGIS |

> El respaldo de h5py es más necesario de lo que parece. Varias instalaciones
> de QGIS traen un `h5py` compilado contra una numpy distinta a la instalada, y
> el `import` revienta con `numpy.dtype size changed`. Por eso el respaldo
> captura cualquier excepción al importar, no sólo `ImportError`.

Un plugin que se cae al abrir el panel porque falta un paquete no es un plugin:
es una nota pidiéndole al usuario que instale cosas.

## Instalación

**Descargá el ZIP de la última versión desde
[Releases](https://github.com/csoto666/qgis-hdfeos-extractor/releases/latest)**
y en QGIS: **Complementos → Instalar a partir de ZIP**.

Ese es el único archivo pensado para instalar. Lo arma el propio repositorio
en cada versión y se revisa antes de publicarlo.

Desde el repositorio oficial de QGIS: **Complementos → Administrar e instalar
complementos**, buscar *HDF-EOS Explorer*.

Desde el código fuente, si preferís armarlo vos:

```sh
./empaquetar.sh
```

### No uses el botón verde «Code → Download ZIP»

Ese ZIP trae una carpeta raíz llamada `qgis-hdfeos-extractor-main`, y QGIS
toma el nombre de la carpeta como nombre del complemento. Como el plugin vive
un nivel más adentro, QGIS arma un nombre de módulo con barra y guiones —que
no es un identificador válido de Python— y la carga falla así:

```
Couldn't load plugin 'qgis-hdfeos-extractor-main/hdfeos_extractor'
ModuleNotFoundError: No module named 'qgis-hdfeos-extractor-main/hdfeos_extractor'
```

Si ya te pasó: borrá la carpeta `qgis-hdfeos-extractor-main` de

```
~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/   (macOS)
~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/                  (Linux)
%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\                     (Windows)
```

y volvé a instalar con el ZIP de
[Releases](https://github.com/csoto666/qgis-hdfeos-extractor/releases/latest).
La otra opción, sin descargar nada,
es copiar a mano la carpeta `hdfeos_extractor/` del repositorio dentro de ese
mismo directorio de plugins —tiene que quedar `.../plugins/hdfeos_extractor/`,
con `__init__.py` y `metadata.txt` directamente adentro— y reiniciar QGIS.

### Requisitos de versión

Probado contra QGIS 3.16 en adelante. El código no usa sintaxis posterior a
Python 3.8, así que funciona en el Python 3.9 que traen las compilaciones de
QGIS para macOS.

## Uso del núcleo sin QGIS

```python
from hdfeos_extractor.core import HyperspectralCube, RGBComposer

with HyperspectralCube.load("escena.h5") as cubo:   # o "escena.hdr"
    print(cubo)                                     # dimensiones y rango
    espectro = cubo.get_spectrum(x=342, y=218)
    rojo = cubo.get_band(wavelength=665)
    columna = cubo.get_transect("x", 80)            # (fila, banda)
    rgb = RGBComposer(842, 665, 560).create_composite(cubo)
```

`load()` elige el lector solo: HDF-EOS5 por la **firma del archivo** —no por la
extensión, porque los productos circulan como `.h5`, `.he5`, `.hdf5` y a veces
sin sufijo útil—, después ENVI, y GDAL como respaldo.

Para verlo funcionando de punta a punta sobre una escena sintética:

```sh
python3 hdfeos_extractor/examples/demo_cube.py
```

## Rendimiento

ENVI se abre por memoria mapeada: el cubo no se carga, el sistema pagina lo que
se toca, y extraer un espectro lee unos pocos kilobytes.

HDF5 está comprimido y por trozos, así que un espectro obliga a descomprimir
los trozos que lo contienen. Con h5py se nota poco; con el respaldo de GDAL se
nota más. **Para una escena que se va a recorrer mucho, sigue conviniendo
extraer a ENVI** —y por eso el botón está en el panel—.

El principio que ordena el resto:

> **La resolución de despliegue y la de análisis están separadas.**

El mapa puede mostrar una imagen reducida mientras la extracción de espectros
sigue yendo al dato original, a resolución completa.

## Pruebas

```sh
./verificar.sh     # pruebas, estilo y demo: lo mismo que corre el CI
python3 -m pytest  # sólo las pruebas
```

Corren también en cada empujón a GitHub, en **Python 3.9 y 3.12**. El 3.9 está
ahí a propósito: es el que traen las compilaciones de QGIS para macOS, y es
donde aparecería cualquier uso de sintaxis o de numpy posterior a esa versión.

Las del núcleo corren sin QGIS ni Qt. Las del gráfico, el cubo y el panel se
saltan solas si no hay enlaces de Qt; las de HDF-EOS5, si no hay `h5py`.

`tests/test_paquete.py` arma el ZIP con el script real y comprueba su forma:
una sola carpeta raíz, con nombre que sea un identificador de Python válido, y
`__init__.py` y `metadata.txt` directamente adentro. Existe porque esa forma se
rompió una vez y el error apareció en la máquina del usuario, que es el peor
lugar para enterarse.

La prueba que sostiene el diseño está en `tests/test_hdf5.py`: extrae un cubo
sintético a ENVI con el mismo código que usa el algoritmo y comprueba que
explorar el `.h5` y explorar el ENVI extraído devuelven **los mismos números,
píxel a píxel**. Si eso no se cumpliera, tener las dos rutas en una sola
herramienta sería peor que no tenerlas.

## Licencia

GNU GPL v2 o posterior. Ver [LICENSE](LICENSE).

## Autor

Carlo Soto Castro — carlo.soto.castro@gmail.com
