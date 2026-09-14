# Hyperspectral Explorer

Plugin de QGIS para explorar cubos hiperespectrales enlazando, en tiempo
real, **dónde está un píxel, cómo se ve y cómo responde espectralmente**.

*A QGIS plugin for interactive exploration of hyperspectral data cubes: it
links spatial position, image and spectral response in real time.*

![icono](icon.png)

> **Un píxel no es un píxel. Es un espectro.**

---

## El problema

Un cubo hiperespectral es tres cosas a la vez —un lugar, una imagen y un
espectro— y casi todos los visores muestran solo la imagen. El usuario ve
una composición en falso color, reconoce que *ahí* hay algo distinto, y no
tiene manera de preguntarle a ese píxel por qué.

Al revés pasa lo mismo: quien trabaja con firmas espectrales las mira en un
gráfico que no sabe de qué parte del terreno salieron.

Este plugin no pretende ser otro visor 3D de cubos. El objetivo es que la
relación entre las tres representaciones sea **inmediata y navegable**:

```
posición (X,Y) → imagen/composición → respuesta espectral (λ, Z)
```

## Qué hace

Agrega un panel acoplable. El lienzo de QGIS sigue siendo la vista espacial;
el panel aporta el eje que al lienzo le falta.

| Interacción | Resultado |
|---|---|
| Clic en un píxel | Se extrae y dibuja su firma espectral completa, y el píxel queda resaltado en el mapa |
| Arrastrar la **línea X** | Fija una columna y resume toda la columna: media, mínimo y máximo por banda, actualizándose mientras se mueve |
| Arrastrar la **línea Y** | Lo mismo fijando una fila |
| Arrastrar un **rectángulo** | Firma media del área, con la desviación por banda dibujada como envolvente sombreada |
| Cambiar **R/G/B** | La capa se recompone al instante, y el gráfico marca sobre el eje espectral dónde caen esas tres bandas |
| Arrastrar sobre el **cubo** | La cruz recorre la escena y las dos caras laterales cambian con ella |
| Clic en un **costado del cubo** | Esa banda pasa a la cara frontal |

## El cubo no es una ilustración

La vista clásica del cubo hiperespectral —la imagen al frente y el espectro
en los costados— aquí no es un adorno: **las caras laterales son los mismos
transectos que alimentan el gráfico**.

```
cara superior  = get_transect("y", fila)     → (x, λ)
cara derecha   = get_transect("x", columna)  → (y, λ)
```

La diferencia con el cubo de ENVI es que aquel es estático —sus caras son el
borde de la escena— y este no: **las caras son el corte que pasa por la
cruz**. Mover la cruz recorre el cubo de verdad. Es la diferencia entre mirar
un cubo y explorarlo.

Dos cosas más que salen de ahí:

- Las tres bandas que arman la imagen frontal se dibujan **dentro** de las
  caras, así que se ve de qué rebanadas está hecho lo que se está mirando.
- Un clic en un costado lleva esa banda al frente. Es el gesto natural
  frente a un cubo —se ve una franja rara y uno quiere ver esa banda— y en
  ENVI hay que ir a otro diálogo, elegir el número y abrir otra ventana.

No hay OpenGL ni biblioteca 3D. La proyección es oblicua y se dibuja con
QPainter aplicando una transformación afín a cada cara. Para tres caras
alcanza de sobra, y mantiene la regla del proyecto.

Las bandas malas salen como franjas negras, igual que en ENVI: un hueco
tiene que parecer un hueco.

### La composición RGB se elige por longitud de onda

No por número de banda. Es lo que vuelve portables los presets: `rojo = 665
nm` significa lo mismo en Tanager, en PRISMA y en EMIT; `rojo = banda 29` no
significa nada fuera del sensor donde se escribió.

Los presets que el sensor no alcanza no se ofrecen. Un preset SWIR sobre un
cubo que llega a 900 nm no falla: resuelve las tres bandas a la última y
devuelve una imagen gris que el usuario no sabe interpretar.

### Biblioteca espectral

Las firmas se guardan con **procedencia**: de qué escena, de qué píxeles,
cuándo, y con qué notas. El vector de reflectancia solo no sirve para nada
seis meses después.

Se pueden renombrar, ocultar, borrar, comparar por **ángulo espectral**
(SAM) y exportar a CSV. El ángulo es la medida correcta entre espectros
porque compara la forma y no la magnitud: la misma cubierta en sombra y al
sol da dos curvas a alturas distintas y con el mismo ángulo.

## Arquitectura

El núcleo está deliberadamente separado del frontend.

```
core/     numpy puro. No importa QGIS ni Qt.
   ↓
vista/    widgets de Qt. No importa QGIS.
   ↓
qgis_ui/  lo que habla con QGIS.
```

Esa separación no es prolijidad: es lo que permite que el mismo núcleo sirva
después desde Jupyter, desde un script suelto o desde otra interfaz, y —más
inmediato— es lo que hace que se pueda **probar sin tener QGIS instalado**.

`qgis_ui/controller.py` es la excepción intencional: usa Qt para sus señales
pero no importa QGIS, porque es donde de verdad se esconden los errores de
enlace y conviene poder probarlo.

```
core/
  envi.py      cabecera ENVI y lectura por memoria mapeada
  sources.py   las otras fuentes: memoria y GDAL
  cube.py      HyperspectralCube: la API con dimensiones nombradas
  geo.py       conversión mapa ↔ píxel
  rgb.py       composición y realce
  colormap.py  paletas para pintar un plano del cubo
  spectral.py  firmas, estadísticas, ángulo espectral
  library.py   biblioteca persistente
```

### El modelo de datos no asume tres dimensiones

Hacia afuera no se ofrece `cubo[y, x, banda]` sino operaciones con nombre:

```python
cube.get_spectrum(x, y)
cube.get_band(wavelength=665)
cube.get_transect(axis="x", position=80)
cube.get_roi(x0, y0, x1, y1)
```

Hoy el cubo es `C(y, x, λ)`. Mañana puede ser `C(tiempo, λ, y, x)`. La API
con nombre es lo que deja esa puerta abierta sin reescribir a los
consumidores.

## Dependencias

**Ninguna obligatoria más allá de lo que trae QGIS.** Usa numpy y GDAL, los
dos incluidos.

| Paquete | Para qué | Si falta |
|---|---|---|
| `pyqtgraph` | Gráfico espectral con zoom y desplazamiento | Un lienzo propio dibuja lo mismo con QPainter |
| — | La vista del cubo | No necesita nada: QPainter y numpy |
| `xarray` | `cube.to_xarray()` | Solo falla esa función; el resto no lo usa |
| `rasterio` | — | No se usa. GDAL hace lo mismo y sí viene con QGIS |

Un plugin que se cae al abrir el panel porque falta un paquete no es un
plugin: es una nota pidiéndole al usuario que instale cosas.

## Instalación

```sh
./empaquetar.sh
```

y en QGIS: **Complementos → Instalar a partir de ZIP**.

> No uses el botón «Download ZIP» de GitHub: genera una carpeta raíz con el
> nombre del repositorio y QGIS toma ese nombre como nombre del complemento.

## Uso del núcleo sin QGIS

```python
from hyperspectral_explorer.core import HyperspectralCube, RGBComposer

with HyperspectralCube.load("escena.hdr") as cubo:
    print(cubo)                                  # dimensiones y rango espectral
    espectro = cubo.get_spectrum(x=342, y=218)
    rojo = cubo.get_band(wavelength=665)
    columna = cubo.get_transect("x", 80)         # (fila, banda)
    rgb = RGBComposer(842, 665, 560).create_composite(cubo)
```

Para verlo funcionando de punta a punta sobre una escena sintética:

```sh
python3 examples/demo_cube.py
```

Genera tres cubiertas de firma conocida —vegetación, suelo y agua— con un
gradiente de iluminación encima, y comprueba que el ángulo espectral las
reconoce pese a ese gradiente.

## Rendimiento

El cubo no se carga en memoria: se abre por memoria mapeada y el sistema
pagina lo que se toca. Un cubo de 500 MB se abre en microsegundos y extraer
un espectro lee unos pocos kilobytes.

El principio que ordena el resto:

> **La resolución de despliegue y la resolución de análisis están separadas.**

El mapa puede mostrar una imagen reducida mientras la extracción de espectros
sigue yendo al dato original, a resolución completa.

## Estado

Versión experimental. Lo que funciona es el hito que valida el concepto:
abrir un cubo, componer, hacer clic, ver el espectro, recorrer X e Y, y
guardar firmas.

El cubo llegó después del enlace 2D/1D y no antes, que es el orden que el
documento de diseño pide: una vez que la relación X/Y ↔ espectro funciona, el
cubo es una extensión de ese enlace y no su fundamento.

Queda para después, en este orden: índices espectrales, remoción del
continuo, PCA, endmembers, clasificación, y después la exploración N-D —tiempo
como cuarta dimensión, que es para lo que el modelo de datos ya está
preparado—.

## Pruebas

```sh
python3 -m pytest
```

Las del núcleo corren sin QGIS ni Qt. Las del gráfico y el controlador se
saltan solas si no hay enlaces de Qt.

## Licencia

GNU GPL v2 o posterior. Ver [LICENSE](../LICENSE).

## Autor

Carlo Soto Castro — carlo.soto.castro@gmail.com
