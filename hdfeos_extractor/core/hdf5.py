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
        """El grid primero, las capas de lat/lon despues.

        Ese orden es el importante. Un producto ortorectificado se guarda
        como GRID de HDF-EOS: ya esta puesto sobre una proyeccion, trae una
        geotransformacion exacta en el StructMetadata y NO trae capas de
        latitud y longitud, porque no le hacen falta. Buscandole lat/lon no
        se encuentra nada y la escena quedaba sin georreferencia aunque el
        producto viniera perfectamente ubicado.

        Un producto en geometria de sensor es al reves: no hay afin que lo
        describa y lo que trae son las dos capas. Por eso se prueban los dos
        caminos, y no uno.
        """
        from .georef import Georreferencia
        if self.escena is None:
            return Georreferencia.ninguna(nota="el cubo ya esta cerrado")
        lineas, muestras = self.escena.lineas, self.escena.muestras

        # En orden de autoridad: primero lo que el productor declara de forma
        # explicita, al final lo que hay que deducir.
        for buscar in (self._georreferencia_de_encuadre,
                       self._georreferencia_del_grid,
                       self._georreferencia_proyectada,
                       self._georreferencia_de_gdal):
            hallada = buscar(lineas, muestras)
            if hallada is not None and hallada.tiene_mapa:
                return hallada

        try:
            ruta_lon, ruta_lat = self.escena.hallar_geolocalizacion()
            if not (ruta_lon and ruta_lat):
                return Georreferencia.ninguna(nota=self._por_que_no_hay())
            lon = self.backend.leer_todo(ruta_lon)
            lat = self.backend.leer_todo(ruta_lat)
        except (ErrorLectura, OSError, KeyError, ValueError) as exc:
            return Georreferencia.ninguna(
                nota="no se pudieron leer las capas de lat/lon: %s" % exc)
        return Georreferencia.de_rejilla(lon, lat, lineas=lineas,
                                         muestras=muestras)

    def _georreferencia_proyectada(self, lineas, muestras):
        """La afin de un producto ya proyectado que no es un GRID clasico.

        Un ortho puede llevar su georreferencia de dos formas mas, y las dos
        son habituales fuera de HDF-EOS puro: una geotransformacion escrita
        como atributo -lo que hace rioxarray-, o dos vectores con la
        coordenada del centro de cada columna y cada fila, que es la
        convencion CF. Ninguna de las dos incluye capas de latitud y
        longitud, porque un producto proyectado no las necesita.
        """
        from .georef import (Georreferencia, geotransformacion_de_atributos,
                             src_de_atributos)
        atributos = self._atributos_globales()
        wkt, epsg = src_de_atributos(atributos)

        gt = geotransformacion_de_atributos(atributos)
        if gt is not None:
            return Georreferencia(gt=gt, wkt=wkt, epsg=epsg,
                                  origen="atributos del producto")

        ejes = self._ejes_de_coordenadas(lineas, muestras)
        if ejes is None:
            return None
        x, y = ejes
        georref = Georreferencia.de_ejes(x, y, wkt=wkt, epsg=epsg)
        if georref.tiene_mapa and not georref.tiene_src:
            georref.nota = ("el producto trae ejes de coordenadas pero no "
                            "dice en que sistema: hay que asignarle el SRC "
                            "a mano")
        return georref

    def _georreferencia_de_gdal(self, lineas=None, muestras=None):
        """Ultimo recurso: preguntarle al driver de GDAL.

        GDAL lleva anos leyendo dialectos de HDF5 georreferenciado, y a veces
        reconoce uno que este modulo no. No se pone primero porque abre el
        archivo por segunda vez y porque cuando los caminos anteriores dan
        algo, ese algo viene del producto y no de la interpretacion de un
        driver. Pero antes de rendirse, vale la pena preguntar.
        """
        from .georef import Georreferencia
        del lineas, muestras               # GDAL ya sabe el tamano
        try:
            from osgeo import gdal
        except ImportError:                # pragma: no cover - QGIS trae GDAL
            return None
        if self.escena is None:
            return None
        candidatas = ['HDF5:"%s"://%s' % (self.ruta, self.escena.ruta_cubo),
                      self.ruta]
        for uri in candidatas:
            ds = None
            try:
                ds = gdal.Open(uri)
                if ds is None:
                    continue
                georref = Georreferencia.de_gdal(ds)
            except Exception:              # pragma: no cover - driver raro
                continue
            finally:
                ds = None
            if georref.tiene_mapa:
                georref.origen = "driver de GDAL"
                return georref
        return None

    def _ejes_de_coordenadas(self, lineas, muestras):
        """Los vectores x/y del producto, si su largo cuadra con la escena.

        El largo es lo que los identifica. Un archivo puede tener varias
        variables llamadas "x"; la que georreferencia el cubo es la que mide
        exactamente lo que mide el cubo.
        """
        from .georef import EJES_X, EJES_Y
        if self.escena is None:
            return None
        candidatos = {}
        for ruta, (forma, _t) in self.escena.inventario.items():
            if len(forma) != 1:
                continue
            hoja = ruta.rsplit("/", 1)[-1].strip().lower()
            if forma[0] == muestras and hoja in EJES_X:
                candidatos.setdefault("x", ruta)
            elif forma[0] == lineas and hoja in EJES_Y:
                candidatos.setdefault("y", ruta)
        if "x" not in candidatos or "y" not in candidatos:
            return None
        try:
            return (self.backend.leer_todo(candidatos["x"]),
                    self.backend.leer_todo(candidatos["y"]))
        except (ErrorLectura, OSError, KeyError, ValueError):
            return None

    def _atributos_globales(self):
        leer = getattr(self.backend, "atributos_globales", None)
        if leer is None:
            return {}
        try:
            return leer() or {}
        except Exception:                  # pragma: no cover - backend raro
            return {}

    def _por_que_no_hay(self):
        """Que se busco y que habia, para poder diagnosticar sin el archivo.

        "No hay georreferencia" no se puede depurar: no dice si falta el
        grid, si las capas se llaman de otro modo o si estan en otra
        resolucion. Esto enumera lo que el contenedor si trae, que es lo que
        de verdad distingue esos tres casos.
        """
        partes = ["el producto no trae ni un grid georreferenciado ni capas "
                  "de latitud y longitud"]
        leer = getattr(self.backend, "texto_estructura", None)
        try:
            hay_estructura = bool(leer and leer())
        except Exception:                  # pragma: no cover - backend raro
            hay_estructura = False
        partes.append("StructMetadata: %s"
                      % ("si, pero sin grid" if hay_estructura else "no"))
        atributos = self._atributos_globales()
        con_gt = sorted({str(k).rsplit("/", 1)[-1]
                         for k, v in atributos.items()
                         if "geotransform" in (str(v) or "").lower()})[:4]
        partes.append("atributos con geotransformacion: %s"
                      % (", ".join(con_gt) if con_gt else "ninguno"))
        try:
            candidatas = sorted(
                {r.rsplit("/", 1)[-1]
                 for r, (forma, _t) in self.escena.inventario.items()
                 if len(forma) == 2})[:12]
        except (AttributeError, TypeError):    # pragma: no cover
            candidatas = []
        if candidatas:
            partes.append("capas 2D en el archivo: " + ", ".join(candidatas))
        try:
            unidim = sorted(
                {r.rsplit("/", 1)[-1]
                 for r, (forma, _t) in self.escena.inventario.items()
                 if len(forma) == 1})[:12]
        except (AttributeError, TypeError):    # pragma: no cover
            unidim = []
        if unidim:
            partes.append("vectores 1D: " + ", ".join(unidim))
        return ". ".join(partes)

    def _georreferencia_de_encuadre(self, lineas, muestras):
        """El bloque de encuadre que el productor escribe como JSON.

        Es como Planet georreferencia los Tanager ortho: un atributo con el
        codigo EPSG, la geotransformacion y el tamano de la imagen. Va el
        primero de todos porque es lo mas explicito que puede haber -el
        productor diciendo literalmente donde esta la escena- y porque GDAL
        no lo aplica, asi que nadie mas lo va a hacer.

        Se comprueba que el encuadre describa ESTA imagen. Un producto puede
        traer el encuadre de otra version del mismo dato, y usarlo cuando las
        dimensiones no cuadran pondria la escena con la escala de la otra:
        aterrizaria cerca, que es la peor clase de error porque parece bien.
        """
        from .georef import Georreferencia, georreferencia_de_json
        hallado = georreferencia_de_json(self._atributos_globales())
        if hallado is None:
            return None
        gt, epsg, cols, filas = hallado
        if (cols and muestras and cols != muestras) or \
                (filas and lineas and filas != lineas):
            return Georreferencia.ninguna(
                nota="el encuadre del producto describe una imagen de %sx%s y "
                     "el cubo es de %sx%s: no son el mismo dato"
                     % (cols, filas, muestras, lineas))
        return Georreferencia(gt=gt, epsg=epsg,
                              origen="encuadre del producto")

    def _georreferencia_del_grid(self, lineas, muestras):
        """La afin del StructMetadata, o None si el backend no lo sirve."""
        from .georef import Georreferencia
        leer = getattr(self.backend, "texto_estructura", None)
        if leer is None:
            return None
        try:
            texto = leer()
        except (ErrorLectura, OSError, KeyError, ValueError):
            return None
        if not texto:
            return None
        georref = Georreferencia.de_estructura(texto, lineas, muestras)
        if georref.tiene_mapa and not georref.tiene_src:
            # El grid ubica la escena pero su proyeccion no se supo traducir.
            # El producto suele declarar el codigo aparte -Tanager lo pone en
            # un atributo epsg_code del grupo-, y con las coordenadas ya en la
            # mano ese codigo es lo unico que falta.
            from .georef import src_de_atributos
            wkt, epsg = src_de_atributos(self._atributos_globales())
            if wkt or epsg:
                georref.wkt, georref.epsg = wkt, epsg
                georref.nota = ""
        return georref

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
