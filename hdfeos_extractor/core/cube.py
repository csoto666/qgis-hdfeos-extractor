# -*- coding: utf-8 -*-
#
# Hyperspectral Explorer - plugin de QGIS para exploracion espacial-espectral
# de cubos hiperespectrales
# Copyright (C) 2026 Carlo Soto Castro
#
# Este programa es software libre: usted puede redistribuirlo y/o modificarlo
# bajo los terminos de la Licencia Publica General GNU publicada por la Free
# Software Foundation, ya sea la version 2 de la Licencia o (a su eleccion)
# cualquier version posterior.
#
# Este programa se distribuye con la esperanza de que sea util, pero SIN
# NINGUNA GARANTIA; ni siquiera la garantia implicita de COMERCIABILIDAD o
# APTITUD PARA UN PROPOSITO DETERMINADO. Vea la Licencia Publica General GNU
# para mas detalles.
#
# Usted deberia haber recibido una copia de la Licencia Publica General GNU
# junto con este programa (archivo LICENSE). Si no, vea
# <https://www.gnu.org/licenses/>.
#
"""El modelo semantico del cubo: dimensiones con nombre, no ejes numerados.

La regla que ordena este archivo esta en el documento de diseno: el modelo de
datos no debe asumir que "hiperespectral" significa exactamente tres
dimensiones. Hoy el cubo es C(y, x, longitud_de_onda); manana puede ser
C(tiempo, longitud_de_onda, y, x). Por eso hacia afuera no se ofrece
``cubo[y, x, banda]`` sino operaciones con nombre -``get_spectrum``,
``get_band``, ``get_transect``- y las dimensiones viven en ``dims``.

xarray haria esto solo, y el documento lo recomienda. No se usa como
dependencia obligatoria porque QGIS no lo trae: obligar a instalarlo cambia
el plugin de "se instala y anda" a "se instala, falla, y el usuario averigua
como meter paquetes en el Python de QGIS". La API con nombre esta
implementada a mano sobre numpy, que si viene con QGIS, y ``to_xarray()``
entrega el objeto xarray a quien lo tenga.
"""

import collections
import os

import numpy as np

from .bandas import MascaraBandas
from .envi import EnviError, EnviSource
from .hdf5 import Hdf5Source, es_hdf5
from .sources import GdalSource, MemorySource

# Cuantas bandas completas se guardan en memoria. Cada banda de una escena
# Tanager son unos 4 MB, asi que 12 son ~50 MB: suficiente para que mover los
# tres selectores del compositor RGB no vuelva a tocar el disco, y poco como
# para no incomodar a QGIS.
BANDAS_EN_CACHE = 12

# Extensiones que se mandan derecho a GDAL en vez de intentar ENVI.
EXT_GDAL = (".tif", ".tiff", ".jp2", ".vrt", ".nc", ".hdf", ".h5")


class CubeError(Exception):
    """El cubo no se pudo abrir o la operacion pedida no aplica."""


class HyperspectralCube(object):
    """Un cubo hiperespectral abierto, con eje espectral resuelto.

    Envuelve una *fuente* -ENVI, GDAL o memoria- y le agrega lo que la fuente
    no sabe: como se llaman las dimensiones, que hacer con el valor de
    relleno, como convertir de cuentas a reflectancia y como encontrar una
    banda a partir de una longitud de onda.
    """

    #: Orden de las dimensiones tal como las devuelve ``get_roi``.
    dims = ("y", "x", "wavelength")

    def __init__(self, source, name=None, aplicar_escala=True):
        self.source = source
        self.name = name or getattr(source, "ruta", None) or "cubo"
        self.aplicar_escala = aplicar_escala
        self.lines, self.samples, self.bands = source.shape

        self._cache = collections.OrderedDict()
        self._wavelengths = self._resolver_eje_espectral()

        self.fill_value = getattr(source, "relleno", None)
        self.scale = getattr(source, "escala_reflectancia", None)
        self.fwhm = getattr(source, "fwhm", None)
        self.bbl = getattr(source, "bbl", None)
        self.band_names = getattr(source, "nombres_banda", None)

        # Las ventanas de absorcion y los extremos estan en nanometros, asi
        # que solo se encienden si el cubo trae eje espectral. Sobre un eje
        # que es el indice de banda, "descartar por debajo de 400" borraria
        # casi todo el cubo sin que nadie entienda por que.
        self.mask = MascaraBandas(
            self._wavelengths, bbl=self.bbl,
            usar_absorcion=self.has_wavelengths,
            usar_extremos=self.has_wavelengths)

    # -- apertura -----------------------------------------------------------
    @classmethod
    def load(cls, path, **kwargs):
        """Abre un cubo eligiendo el lector solo.

        El orden no es arbitrario:

        HDF-EOS5 primero, y por la firma del archivo y no por la extension:
        los productos circulan como .h5, .he5, .hdf5 y a veces sin sufijo
        util. Se abre con el mismo nucleo que usa el extractor, que es lo que
        permite mirar la escena sin extraer nada antes.

        ENVI despues, para todo lo que no sea claramente de GDAL: un ``.dat``
        con su ``.hdr`` al lado es el caso comun del flujo hiperespectral, y
        GDAL tambien lo abre pero perdiendo el FWHM y la bbl, que su driver
        ENVI no expone.

        GDAL al final, como respaldo para GeoTIFF y lo demas.
        """
        if not os.path.exists(path):
            raise CubeError("No existe: %s" % path)
        nombre = os.path.basename(path)

        if es_hdf5(path):
            try:
                return cls(Hdf5Source(path), name=nombre, **kwargs)
            except Exception:
                # Un netCDF4 tiene la misma firma que un HDF5 y no es una
                # escena hiperespectral. Que siga el camino normal en vez de
                # fallar aca.
                pass

        ext = os.path.splitext(path)[1].lower()
        if ext not in EXT_GDAL:
            try:
                return cls(EnviSource(path), name=nombre, **kwargs)
            except EnviError:
                pass          # no era ENVI; que lo intente GDAL
        try:
            return cls(GdalSource(path), name=nombre, **kwargs)
        except Exception as exc:
            raise CubeError("No se pudo abrir %s: %s" % (path, exc))

    @classmethod
    def from_array(cls, datos, wavelengths=None, name="cubo", **kwargs):
        """Crea un cubo sobre un array ``(y, x, banda)`` ya en memoria."""
        return cls(MemorySource(datos, wavelengths), name=name, **kwargs)

    def _resolver_eje_espectral(self):
        """Devuelve el eje espectral, o los indices de banda si no hay.

        Un cubo sin longitudes de onda sigue siendo explorable: el grafico
        pasa a estar en numero de banda. Es preferible a negarse a abrirlo,
        porque los GeoTIFF multibanda casi nunca las traen.
        """
        wl = getattr(self.source, "wavelengths", None)
        if wl is None or len(wl) != self.bands:
            self.has_wavelengths = False
            return np.arange(self.bands, dtype=np.float64)
        self.has_wavelengths = True
        return np.asarray(wl, dtype=np.float64)

    # -- eje espectral ------------------------------------------------------
    @property
    def wavelengths(self):
        """Eje espectral en nanometros, o indices de banda si no los hay."""
        return self._wavelengths

    @property
    def unidad_espectral(self):
        return "nm" if self.has_wavelengths else "banda"

    def band_index(self, wavelength, solo_buenas=False):
        """Indice de la banda mas cercana a ``wavelength``.

        Se usa la mas cercana y no una coincidencia exacta a proposito: nadie
        conoce de memoria que la banda del rojo de este sensor cae en 664.7 y
        no en 665, y exigir el valor exacto convertiria cada preset en una
        tabla por sensor.

        Con ``solo_buenas`` se salta las bandas descartadas. Lo usa el
        compositor RGB: un preset que cae dentro de una ventana de absorcion
        devolveria una banda de puro ruido, y la imagen saldria con textura
        que no existe en el terreno.
        """
        if solo_buenas:
            return self.mask.indice_bueno_mas_cercano(wavelength)
        return int(np.argmin(np.abs(self._wavelengths - float(wavelength))))

    def nearest_wavelength(self, wavelength):
        """La longitud de onda real de la banda que se usaria."""
        return float(self._wavelengths[self.band_index(wavelength)])

    def _resolver_banda(self, wavelength=None, index=None):
        if index is not None:
            if not 0 <= index < self.bands:
                raise CubeError("Banda %s fuera de rango (0..%d)"
                                % (index, self.bands - 1))
            return int(index)
        if wavelength is None:
            raise CubeError("Hay que dar wavelength o index")
        return self.band_index(wavelength)

    # -- limpieza de valores ------------------------------------------------
    def _limpiar(self, datos):
        """Aplica relleno y escala. Devuelve siempre float32.

        float32 y no el tipo original porque el relleno se marca con NaN, y
        NaN no existe en los enteros. Convertir aca -una sola vez, en el
        unico camino por el que salen los datos- evita que cada consumidor
        tenga que acordarse de hacerlo.

        La copia es deliberada: sin ella numpy devolveria una vista del
        memmap cuando el cubo ya viene en float32, y el cache terminaria
        guardando el mapeo en vez de los datos -sin acelerar nada y
        sosteniendo el archivo abierto-.
        """
        salida = np.array(datos, dtype=np.float32)   # copia, no vista
        if self.fill_value is not None:
            salida = np.where(np.isclose(salida, self.fill_value),
                              np.float32(np.nan), salida)
        if self.aplicar_escala and self.scale:
            salida = salida / np.float32(self.scale)
        return salida

    # -- lecturas con nombre ------------------------------------------------
    def get_spectrum(self, x, y):
        """Espectro de un pixel: vector de largo ``bands``.

        Esta es la operacion central del plugin. Un pixel no es un pixel: es
        un espectro.
        """
        x, y = int(x), int(y)
        if not (0 <= x < self.samples and 0 <= y < self.lines):
            raise CubeError("Pixel (%d, %d) fuera de la imagen %dx%d"
                            % (x, y, self.samples, self.lines))
        return self.mask.aplicar(self._limpiar(self.source.read_pixel(y, x)))

    def get_band(self, wavelength=None, index=None):
        """Una banda completa como matriz ``(y, x)``, con cache.

        Esta es la unica lectura que NO aplica la mascara de bandas malas, y
        es deliberado: la mascara existe para limpiar el analisis espectral,
        no para impedir mirar una banda. Quien quiere ver como se ve la banda
        de 1400 nm tiene derecho a verla -en ruido, pero verla-. Lo que no
        debe pasar es que ese ruido entre en una firma o en una media.

        El cache es lo que hace que mover los selectores R/G/B se sienta
        instantaneo: volver a una banda ya vista no toca el disco.
        """
        b = self._resolver_banda(wavelength, index)
        if b in self._cache:
            self._cache.move_to_end(b)
            return self._cache[b]
        datos = self._limpiar(self.source.read_band(b))
        datos.flags.writeable = False     # el cache no se modifica desde fuera
        self._cache[b] = datos
        while len(self._cache) > BANDAS_EN_CACHE:
            self._cache.popitem(last=False)
        return datos

    def get_transect(self, axis, position):
        """Corta el cubo con una linea y devuelve el plano espectral.

        ``axis="x"`` fija una columna y recorre las filas; ``axis="y"`` fija
        una fila y recorre las columnas. En los dos casos el resultado es
        ``(a_lo_largo_de_la_linea, banda)``, listo para dibujarse como imagen
        o para recorrerse espectro a espectro.

        Este es el corte que da al plugin su razon de ser: mover la linea por
        la imagen y ver como responde el espectro es la relacion que el
        usuario no puede ver en un visor comun.
        """
        eje = str(axis).lower()
        p = int(position)
        if eje == "x":
            if not 0 <= p < self.samples:
                raise CubeError("Columna %d fuera de 0..%d"
                                % (p, self.samples - 1))
            bruto = self.source.read_window(0, self.lines, p, p + 1)
            return self.mask.aplicar(self._limpiar(bruto[:, 0, :]))
        if eje == "y":
            if not 0 <= p < self.lines:
                raise CubeError("Fila %d fuera de 0..%d" % (p, self.lines - 1))
            bruto = self.source.read_window(p, p + 1, 0, self.samples)
            return self.mask.aplicar(self._limpiar(bruto[0, :, :]))
        raise CubeError("axis tiene que ser 'x' o 'y', llego %r" % axis)

    def get_x_profile(self, x):
        """Transecto de columna fija. Atajo de ``get_transect("x", x)``."""
        return self.get_transect("x", x)

    def get_y_profile(self, y):
        """Transecto de fila fija. Atajo de ``get_transect("y", y)``."""
        return self.get_transect("y", y)

    def get_roi(self, x0, y0, x1, y1):
        """Sub-cubo ``(y, x, banda)`` del rectangulo dado, extremos incluidos.

        Las coordenadas se ordenan y se recortan a la imagen en vez de fallar:
        un rectangulo arrastrado con el raton empieza donde el usuario apreto
        el boton, que puede ser la esquina inferior derecha, y puede salirse
        del borde.
        """
        x0, x1 = sorted((int(x0), int(x1)))
        y0, y1 = sorted((int(y0), int(y1)))
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(self.samples - 1, x1)
        y1 = min(self.lines - 1, y1)
        if x1 < x0 or y1 < y0:
            raise CubeError("El area seleccionada no toca la imagen")
        return self.mask.aplicar(self._limpiar(
            self.source.read_window(y0, y1 + 1, x0, x1 + 1)))

    def get_pixels(self, coords):
        """Espectros de una lista de ``(x, y)``: matriz ``(n_pixeles, banda)``.

        Se lee pixel por pixel y no con indexado avanzado porque los pixeles
        de una seleccion manual estan dispersos: leer la ventana que los
        contiene a todos podria traer el cubo entero para tres puntos.
        """
        if not coords:
            raise CubeError("La lista de pixeles esta vacia")
        return np.vstack([self.get_spectrum(x, y) for x, y in coords])

    def set_mask(self, mask):
        """Cambia la mascara de bandas malas.

        El cache de bandas no se toca: guarda lecturas sin enmascarar, que es
        justamente lo que ``get_band`` sigue devolviendo.
        """
        self.mask = mask
        return self.mask

    # -- resolucion de despliegue vs resolucion de analisis ------------------
    def preview_band(self, wavelength=None, index=None, max_lado=1024):
        """Una banda submuestreada para dibujar, no para medir.

        El principio del documento de diseno: separar la resolucion de
        despliegue de la resolucion de analisis. El mapa puede mostrar una
        imagen reducida mientras la extraccion de espectros sigue yendo al
        dato original. El submuestreo es por salto y no por promedio, que es
        lo correcto aca: promediar inventaria espectros que no existen en la
        escena.
        """
        banda = self.get_band(wavelength, index)
        paso = max(1, int(np.ceil(max(banda.shape) / float(max_lado))))
        return banda[::paso, ::paso], paso

    # -- interoperabilidad --------------------------------------------------
    def to_xarray(self, roi=None):
        """Devuelve el cubo como ``xarray.DataArray`` con ejes con nombre.

        Carga los datos en memoria, asi que para un cubo entero conviene
        pasar ``roi``. Existe para el uso desde Jupyter, donde xarray si
        suele estar instalado; el plugin no lo necesita para funcionar.
        """
        try:
            import xarray as xr
        except ImportError:
            raise CubeError(
                "to_xarray() necesita xarray, que no esta instalado. "
                "El resto del nucleo funciona sin el.")
        if roi is None:
            datos = self.get_roi(0, 0, self.samples - 1, self.lines - 1)
            y0, x0 = 0, 0
        else:
            x0, y0, x1, y1 = roi
            datos = self.get_roi(x0, y0, x1, y1)
        alto, ancho, _ = datos.shape
        return xr.DataArray(
            datos, dims=self.dims,
            coords={"y": np.arange(y0, y0 + alto),
                    "x": np.arange(x0, x0 + ancho),
                    "wavelength": self._wavelengths},
            name=self.name,
            attrs={"units": self.unidad_espectral, "source": self.name})

    def close(self):
        self._cache.clear()
        if self.source is not None:
            self.source.close()
            self.source = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __repr__(self):
        return ("<HyperspectralCube %s  %d x %d x %d  %.1f-%.1f %s>"
                % (self.name, self.lines, self.samples, self.bands,
                   self._wavelengths[0], self._wavelengths[-1],
                   self.unidad_espectral))
