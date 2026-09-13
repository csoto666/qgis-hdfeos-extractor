# HDF-EOS Extractor

Plugin de QGIS que extrae cubos hiperespectrales empaquetados en **HDF-EOS5**
—Planet Tanager y productos similares— al **formato nativo de ENVI**, con las
longitudes de onda, el FWHM y la lista de bandas malas escritas en la
cabecera.

*A QGIS plugin that unpacks hyperspectral cubes stored in HDF-EOS5 files into
ENVI's native format, with centre wavelengths, FWHM and a bad band list
written into the header.*

![icono](icon.png)

---

## El problema

Un producto hiperespectral moderno llega como un solo contenedor HDF-EOS5 con
el cubo, los arreglos de geolocalización por píxel, las máscaras de calidad y
la geometría sol-sensor adentro. Dos cosas se rompen ahí:

- El software anterior al producto no lo abre. ENVI 5.0 es de 2013 y Tanager
  de 2024: no existe opción de menú que entienda ese contenedor.
- Exportarlo como ráster común tira a la basura el metadato espectral, que es
  justamente lo que vuelve utilizable un cubo.

El formato nativo de ENVI —binario crudo más cabecera de texto— no ha cambiado
en décadas y lo lee cualquier paquete hiperespectral. Este plugin hace ese
puente.

## Qué hace

Agrega un algoritmo a la Caja de herramientas de Processing, **HDF-EOS5 to
ENVI**, con cuatro salidas seleccionables:

| Salida | Archivo | Contenido |
|---|---|---|
| Cubo hiperespectral | `<prefijo>_cube.dat` + `.hdr` | El cubo en **BIL**, el intercalado que ENVI espera para procesamiento espectral |
| Geolocalización | `<prefijo>_igm.dat` + `.hdr` | IGM de 2 bandas (longitud, latitud) para *Georeference from Input Geometry* |
| Capas auxiliares | `<prefijo>_aux.dat` + `.hdr` | Máscaras, atmósfera y geometría sol-sensor apiladas, con nombres de banda |

La cabecera del cubo lleva:

- `wavelength` — longitudes de onda centrales, convertidas a nanómetros si
  venían en micrómetros
- `fwhm` — ancho a media altura
- `data ignore value` — el valor de relleno declarado en el archivo
- `bbl` — lista de bandas malas, con las **ventanas de absorción de vapor de
  agua ya marcadas** (1340–1460 y 1790–1960 nm) más los extremos ruidosos del
  rango. Así MNF, PPI y el desmezclado espectral no arrastran esas bandas.

## Por qué un algoritmo de Processing y no un diálogo

Porque sale gratis lo que de otro modo hay que programar: procesamiento por
lotes sobre una carpeta de escenas, uso dentro del modelador gráfico, y
llamada desde la consola de Python.

```python
import processing
processing.run("hdfeos_extractor:extraer_hdfeos_a_envi", {
    'ENTRADA': '/ruta/escena.h5',
    'CUBO': True,
    'IGM': True,
    'MASCARAS': True,
    'ATMOSFERA': False,
    'GEOMETRIA': False,
    'CARPETA': '/ruta/salida',
    'PREFIJO': '',
})
```

## Instalación

Desde el repositorio oficial: **Complementos → Administrar e instalar
complementos**, buscar *HDF-EOS Extractor*.

Desde el código fuente:

```sh
./empaquetar.sh
```

y en QGIS: **Complementos → Instalar a partir de ZIP**.

> No uses el botón «Download ZIP» de GitHub. Ese genera una carpeta raíz
> llamada `qgis-hdfeos-extractor-main`, y QGIS toma el nombre de esa carpeta
> como nombre del complemento. `empaquetar.sh` arma el ZIP con el nombre
> correcto, `hdfeos_extractor`.

## Dependencias

**Ninguna obligatoria más allá de lo que trae QGIS.** Lee mediante GDAL y
numpy, ambos incluidos.

Si `h5py` está instalado se usa en su lugar, porque da acceso más completo a
los atributos HDF5 y a los datasets 1D de longitud de onda y FWHM. Cuando no
está —o cuando está pero no carga— el plugin cae a GDAL solo, sin avisar ni
fallar.

> Ese segundo caso es más común de lo que parece. Varias instalaciones de QGIS
> traen un `h5py` compilado contra una versión de numpy distinta a la que
> terminó instalada, y el `import` revienta con
> `numpy.dtype size changed, may indicate binary incompatibility`. Por eso el
> respaldo captura cualquier excepción al importar, no solo `ImportError`.

No descarga nada ni consulta ningún servicio remoto.

## Uso de la memoria

El cubo se escribe por bloques de líneas, no de una sola vez. El pico de
memoria es:

```
bandas × líneas_por_bloque × muestras × 4 bytes
```

Con los 32 predeterminados y una escena Tanager típica son unos 33 MB, sobre
un cubo de más de 500 MB. El parámetro está en la sección avanzada por si
querés subirlo o bajarlo.

## Flujo con ENVI

1. Correr el algoritmo con **Cubo** e **IGM** activados.
2. En ENVI, abrir el `_cube.hdr`.
3. Para georreferenciar un producto `basic`, que viene en geometría de
   sensor: **Map → Georeference from Input Geometry → Build GLT**, y pasarle
   el `_igm.hdr` (banda 1 = longitud, banda 2 = latitud, geográficas WGS84).

Los productos `ortho` ya vienen proyectados y no necesitan el IGM.

## Licencia

GNU GPL v2 o posterior. Ver [LICENSE](LICENSE).

## Autor

Carlo Soto Castro — carlo.soto.castro@gmail.com
