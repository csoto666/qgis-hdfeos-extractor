# HDF-EOS Explorer

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

Desde el repositorio oficial: **Complementos → Administrar e instalar
complementos**, buscar *HDF-EOS Explorer*.

Desde el código fuente:

```sh
./empaquetar.sh
```

y en QGIS: **Complementos → Instalar a partir de ZIP**.

> No uses el botón «Download ZIP» de GitHub: genera una carpeta raíz con el
> nombre del repositorio y QGIS toma ese nombre como nombre del complemento.

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
python3 -m pytest
```

Las del núcleo corren sin QGIS ni Qt. Las del gráfico, el cubo y el panel se
saltan solas si no hay enlaces de Qt; las de HDF-EOS5, si no hay `h5py`.

La prueba que sostiene el diseño está en `tests/test_hdf5.py`: extrae un cubo
sintético a ENVI con el mismo código que usa el algoritmo y comprueba que
explorar el `.h5` y explorar el ENVI extraído devuelven **los mismos números,
píxel a píxel**. Si eso no se cumpliera, tener las dos rutas en una sola
herramienta sería peor que no tenerlas.

## Licencia

GNU GPL v2 o posterior. Ver [LICENSE](LICENSE).

## Autor

Carlo Soto Castro — carlo.soto.castro@gmail.com
