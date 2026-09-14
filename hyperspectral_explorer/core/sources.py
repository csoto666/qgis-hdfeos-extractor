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
"""Fuentes de datos alternas al ENVI nativo.

Una *fuente* es cualquier objeto con ``shape``, ``wavelengths`` y los cuatro
metodos de lectura ``read_pixel``, ``read_band``, ``read_window`` y
``close``. ``EnviSource`` define el contrato; aca estan las otras dos
implementaciones.

No se usa rasterio aunque sea la opcion comoda: QGIS trae GDAL y no trae
rasterio, y este plugin sigue la misma regla que el resto del repositorio
-nada obligatorio mas alla de lo que QGIS ya instala-. GDAL expone lo mismo
con mas ceremonia.
"""

import re

import numpy as np

from .envi import to_nanometers

try:
    from osgeo import gdal
    gdal.UseExceptions()
except Exception:      # pragma: no cover - depende de la instalacion
    gdal = None


class MemorySource(object):
    """Un cubo que ya esta en un array de numpy, con ejes ``(y, x, banda)``.

    Sirve para las pruebas, para los ejemplos y para cualquier cubo que venga
    de un calculo en vez de un archivo. Es la implementacion de referencia
    del contrato: si algo funciona contra esta fuente, funciona contra todas.
    """

    def __init__(self, datos, wavelengths=None, nombres_banda=None):
        datos = np.asarray(datos)
        if datos.ndim != 3:
            raise ValueError(
                "Un cubo necesita 3 ejes (y, x, banda); llegaron %d"
                % datos.ndim)
        self.datos = datos
        self.nombres_banda = nombres_banda
        self.wavelengths = (None if wavelengths is None else
                            np.asarray(wavelengths, dtype=np.float64))
        if (self.wavelengths is not None
                and self.wavelengths.size != datos.shape[2]):
            raise ValueError(
                "Hay %d longitudes de onda para %d bandas"
                % (self.wavelengths.size, datos.shape[2]))
        self.relleno = None
        self.escala_reflectancia = None
        self.fwhm = None
        self.bbl = None

    @property
    def shape(self):
        return self.datos.shape

    def read_pixel(self, y, x):
        return self.datos[y, x, :]

    def read_band(self, b):
        return self.datos[:, :, b]

    def read_window(self, y0, y1, x0, x1):
        return self.datos[y0:y1, x0:x1, :]

    def close(self):
        pass


class GdalSource(object):
    """Cubo leido por GDAL: GeoTIFF multibanda y cualquier cosa que GDAL abra.

    Se lee con ``ReadRaster`` y no con ``ReadAsArray`` a proposito. El segundo
    vive en el modulo ``gdal_array``, que no carga cuando la numpy instalada
    es mas nueva que la que uso GDAL al compilarse -un caso comun en las
    instalaciones de QGIS-. ``ReadRaster`` devuelve bytes crudos y numpy los
    interpreta sin intermediarios.
    """

    # Nombre GDAL del tipo -> dtype de numpy.
    TIPOS = {
        "Byte": "u1", "Int8": "i1", "UInt16": "u2", "Int16": "i2",
        "UInt32": "u4", "Int32": "i4", "UInt64": "u8", "Int64": "i8",
        "Float32": "f4", "Float64": "f8",
    }

    def __init__(self, ruta):
        if gdal is None:
            raise RuntimeError("GDAL no esta disponible en este interprete")
        self.ds = gdal.Open(ruta, gdal.GA_ReadOnly)
        if self.ds is None:
            raise RuntimeError("GDAL no pudo abrir: %s" % ruta)
        self.ruta = ruta
        self.bandas = self.ds.RasterCount
        nombre_tipo = gdal.GetDataTypeName(
            self.ds.GetRasterBand(1).DataType)
        if nombre_tipo not in self.TIPOS:
            raise RuntimeError("Tipo GDAL no soportado: %s" % nombre_tipo)
        self.dtype = np.dtype(self.TIPOS[nombre_tipo])

        b1 = self.ds.GetRasterBand(1)
        self.relleno = b1.GetNoDataValue()
        self.escala_reflectancia = None
        self.fwhm = None
        self.bbl = None
        self.wavelengths, self.nombres_banda = self._metadatos_espectrales()

    def _metadatos_espectrales(self):
        """Recupera longitudes de onda y nombres de banda de los metadatos.

        GeoTIFF no tiene un lugar estandar para el eje espectral. Se prueban,
        en orden, los dos sitios donde de hecho aparece: el metadato
        ``wavelength`` por banda -que es lo que escribe GDAL al convertir
        desde ENVI- y la descripcion de la banda, donde suele quedar algo
        como ``Band 42 (665.3 nm)``. Si ninguno da, se devuelve None y el
        eje espectral pasa a ser el indice de banda.
        """
        wl, nombres = [], []
        for i in range(1, self.bandas + 1):
            banda = self.ds.GetRasterBand(i)
            meta = banda.GetMetadata() or {}
            nombres.append(banda.GetDescription() or "banda %d" % i)
            valor = None
            for clave in ("wavelength", "WAVELENGTH", "Wavelength"):
                if clave in meta:
                    valor = meta[clave]
                    break
            if valor is None:
                m = re.search(r"([\d.]+)\s*(nm|um|micrometers?)",
                              nombres[-1], re.IGNORECASE)
                valor = m.group(0) if m else None
            if valor is None:
                wl.append(np.nan)
                continue
            m = re.search(r"[-+]?[\d.]+", str(valor))
            wl.append(float(m.group(0)) if m else np.nan)

        vector = np.asarray(wl, dtype=np.float64)
        if np.all(np.isnan(vector)):
            return None, nombres
        return to_nanometers(vector), nombres

    @property
    def shape(self):
        return (self.ds.RasterYSize, self.ds.RasterXSize, self.bandas)

    def _leer(self, banda, x0, y0, ancho, alto):
        crudo = self.ds.GetRasterBand(banda).ReadRaster(
            x0, y0, ancho, alto, ancho, alto,
            self.ds.GetRasterBand(banda).DataType)
        return np.frombuffer(crudo, dtype=self.dtype).reshape(alto, ancho)

    def read_pixel(self, y, x):
        return np.asarray(
            [self._leer(b, int(x), int(y), 1, 1)[0, 0]
             for b in range(1, self.bandas + 1)], dtype=self.dtype)

    def read_band(self, b):
        alto, ancho, _ = self.shape
        return self._leer(int(b) + 1, 0, 0, ancho, alto)

    def read_window(self, y0, y1, x0, x1):
        ancho, alto = int(x1 - x0), int(y1 - y0)
        salida = np.empty((alto, ancho, self.bandas), dtype=self.dtype)
        for b in range(self.bandas):
            salida[:, :, b] = self._leer(b + 1, int(x0), int(y0), ancho, alto)
        return salida

    def close(self):
        self.ds = None
