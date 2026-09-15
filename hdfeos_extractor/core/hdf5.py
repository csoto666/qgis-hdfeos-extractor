# -*- coding: utf-8 -*-
#
# HDF-EOS Extractor - plugin de QGIS para extraer cubos hiperespectrales
# HDF-EOS5 al formato nativo de ENVI
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
"""El cubo HDF-EOS5 leido directo, sin pasar por ENVI.

Es la razon de que el extractor y el explorador sean un solo plugin: quien
extrae un cubo lo hace para mirarlo, y obligarlo a escribir medio gigabyte en
disco antes de poder hacer clic en un pixel era un paso de mas.

Se apoya entero en ``lector.Escena``, que ya resuelve lo dificil: encontrar el
cubo dentro del contenedor, las longitudes de onda, el FWHM, la lista de
bandas buenas, la escala y el relleno. Aca solo se traduce eso al contrato de
fuente que usa el explorador.

Una advertencia honesta sobre el rendimiento: ENVI se abre por memoria
mapeada y un espectro son unos pocos kilobytes leidos del disco. HDF5 esta
comprimido y por trozos, asi que un espectro obliga a descomprimir los trozos
que lo contienen. Con h5py se nota poco; con el respaldo de GDAL se nota mas.
Por eso el panel ofrece extraer a ENVI: para una escena que se va a recorrer
mucho, sigue conviniendo.
"""

import numpy as np

from ..lector import ErrorLectura, Escena

#: Los ocho bytes con que empieza todo archivo HDF5.
FIRMA_HDF5 = b"\x89HDF\r\n\x1a\n"


class Hdf5Source(object):
    """Acceso por pixel, banda y ventana a un cubo HDF-EOS5.

    Devuelve siempre ejes ``(y, x, banda)`` y valores ya convertidos a
    reflectancia, con el relleno como NaN. Nadie fuera de esta clase tiene
    que saber que el cubo esta guardado como ``(banda, y, x)`` ni que hay que
    aplicarle una escala.
    """

    def __init__(self, ruta, preferir_h5py=True):
        self.escena = Escena(ruta, preferir_h5py)
        self.ruta = ruta
        self.backend = self.escena.backend

        # La escala y el relleno se aplican aca y no en el modelo del cubo, y
        # es deliberado. HDF5 usa "crudo * escala + desfase" y ENVI usa un
        # divisor sin desfase: son dos convenciones distintas, y la unica
        # forma de que explorar el .h5 y explorar el ENVI extraido den los
        # mismos numeros es que cada fuente aplique la suya y entregue
        # reflectancia. Por eso mas abajo se declaran nulos: el modelo del
        # cubo no tiene nada mas que hacerles.
        self._escala = float(self.escena.escala)
        self._desfase = float(self.escena.desfase)
        self._relleno_crudo = self.escena.relleno
        self.relleno = None
        self.escala_reflectancia = None

        self.wavelengths = self.escena.wavelengths
        self.fwhm = self.escena.fwhm
        # Escena guarda las bandas BUENAS; el contrato pide la misma
        # convencion que la bbl de ENVI, que tambien es 1 = buena.
        self.bbl = (None if self.escena.buenas is None
                    else np.asarray(self.escena.buenas).astype(bool))
        self.nombres_banda = None
        self._georref = None

    @property
    def shape(self):
        """(lineas, muestras, bandas). El HDF5 las guarda al reves."""
        return (self.escena.lineas, self.escena.muestras, self.escena.bandas)

    @property
    def georreferencia(self):
        """Puntos de control desde las capas de latitud y longitud.

        Un producto en geometria de sensor no tiene geotransformacion y no
        se le puede inventar una: la relacion entre pixel y terreno cambia a
        lo ancho de la franja. Lo que si tiene son dos capas del tamano de
        la escena con la coordenada de cada pixel, y de ahi sale una rejilla
        de puntos de control con la que se puede remuestrear de verdad.

        Se lee una sola vez y se guarda: son dos arrays del tamano de la
        escena y en HDF5 vienen comprimidos, asi que no conviene releerlos
        cada vez que alguien pregunte donde esta la escena.
        """
        if self._georref is None:
            self._georref = self._leer_georreferencia()
        return self._georref

    def _leer_georreferencia(self):
        from .georef import Georreferencia
        if self.escena is None:
            return Georreferencia.ninguna(nota="el cubo ya esta cerrado")
        try:
            ruta_lon, ruta_lat = self.escena.hallar_geolocalizacion()
            if not (ruta_lon and ruta_lat):
                return Georreferencia.ninguna(
                    nota="el producto no trae capas de latitud y longitud")
            lon = self.backend.leer_todo(ruta_lon)
            lat = self.backend.leer_todo(ruta_lat)
        except (ErrorLectura, OSError, KeyError, ValueError) as exc:
            return Georreferencia.ninguna(
                nota="no se pudieron leer las capas de lat/lon: %s" % exc)
        return Georreferencia.de_rejilla(lon, lat)

    # -- lecturas -----------------------------------------------------------
    def _convertir(self, crudo):
        """Crudo -> reflectancia float32, con el relleno como NaN.

        El enmascarado va ANTES de escalar. Al reves no funciona: el relleno
        declarado esta en unidades crudas, y compararlo contra datos ya
        escalados no acierta ningun pixel.
        """
        crudo = np.asarray(crudo)
        if self._relleno_crudo is not None:
            vacio = np.isclose(crudo.astype(np.float64), self._relleno_crudo)
        else:
            vacio = None
        salida = crudo.astype(np.float32)
        if self._escala != 1.0 or self._desfase != 0.0:
            salida = salida * np.float32(self._escala) \
                + np.float32(self._desfase)
        if vacio is not None and vacio.any():
            salida = np.where(vacio, np.float32(np.nan), salida)
        return salida

    def read_pixel(self, y, x):
        return self._convertir(
            self.backend.leer_espectro(self.escena.ruta_cubo, int(y), int(x)))

    def read_band(self, b):
        return self._convertir(
            self.backend.leer_banda(self.escena.ruta_cubo, int(b)))

    def read_window(self, y0, y1, x0, x1):
        # El backend entrega (banda, y, x); el contrato pide (y, x, banda).
        crudo = self.backend.leer_ventana(
            self.escena.ruta_cubo, int(y0), int(y1), int(x0), int(x1))
        return self._convertir(np.asarray(crudo).transpose(1, 2, 0))

    def close(self):
        if self.escena is not None:
            self.escena.backend.cerrar()
            self.escena = None
            self.backend = None

    def __repr__(self):
        return ("<Hdf5Source %s  %s  backend=%s>"
                % (self.escena.ruta_cubo if self.escena else "cerrado",
                   self.shape if self.escena else "-",
                   self.backend.nombre if self.backend else "-"))


def es_hdf5(ruta):
    """True si el archivo empieza con la firma de HDF5.

    Se mira el contenido y no la extension: los productos circulan como .h5,
    .he5, .hdf5 y a veces sin extension util, y una firma de ocho bytes es
    mas confiable que una lista de sufijos que siempre queda corta.
    """
    try:
        with open(ruta, "rb") as f:
            return f.read(8) == FIRMA_HDF5
    except OSError:
        return False


__all__ = ["Hdf5Source", "es_hdf5", "ErrorLectura"]
