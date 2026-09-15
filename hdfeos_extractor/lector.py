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
"""Nucleo de lectura HDF-EOS5 y escritura ENVI.

Este modulo no importa nada de QGIS a proposito: se puede ejecutar y probar
desde Python puro. Las clases de Processing son solo la envoltura que lo
expone en la Caja de herramientas.

Dos backends de lectura, en este orden:
  h5py  preferido, da acceso completo a atributos y a los datasets 1D de
        longitud de onda y FWHM.
  GDAL  respaldo. Viene siempre con QGIS, asi que el plugin sirve aunque el
        usuario no tenga h5py.
"""

import os
import re

import numpy as np

# =============================================================================
#  CONFIGURACION - todo lo ajustable vive aca arriba
# =============================================================================

# Raices tipicas de los productos HDF-EOS5 (Planet Tanager y familia)
RAICES = [
    "HDFEOS/SWATHS/HYP",
    "HDFEOS/GRIDS/HYP",
]
# Donde HDF-EOS guarda la descripcion de sus swaths y grids, incluida la
# proyeccion y las esquinas de un GRID. Es la georreferencia de un producto
# ortorectificado: un grid no trae capas de latitud y longitud porque no las
# necesita, le basta con una afin, y esa afin esta aca y en ningun otro lado.
RUTA_ESTRUCTURA = "HDFEOS INFORMATION/StructMetadata.0"
#: GDAL aplana esa ruta en los metadatos de la raiz con este nombre.
CLAVE_ESTRUCTURA_GDAL = "StructMetadata_0"

# Subgrupos: HDF-EOS los nombra con espacio, GDAL los expone con guion bajo
SUBGRUPOS_DATOS = ["Data Fields", "Data_Fields"]
SUBGRUPOS_GEO = ["Geolocation Fields", "Geolocation_Fields"]

# Nombres candidatos del cubo, en orden de preferencia
NOMBRES_CUBO = [
    "surface_reflectance",
    "ortho_surface_reflectance",
    "toa_radiance",
    "ortho_radiance",
]

# Rango de bandas aceptable al buscar un cubo por descarte
BANDAS_MIN, BANDAS_MAX = 60, 800

# De donde salen las longitudes de onda y el FWHM
CLAVES_WL = ("wavelength", "wvl", "lambda", "center_wavelength")
CLAVES_FWHM = ("fwhm", "full_width")
ATRIBUTOS_WL = ("wavelengths", "center_wavelengths", "band_center_wavelengths")
ATRIBUTOS_FWHM = ("fwhm", "full_width_half_max")

# Lista de bandas buenas que el propio productor incluye (Tanager la trae como
# "good_wavelengths"). Cuando existe se respeta y se combina con la heuristica
# de absorcion de abajo: una banda es buena solo si ambas la dan por buena.
CLAVES_BBL = ("good_wavelength", "good_band")
ATRIBUTOS_BBL = ("good_wavelengths", "good_bands")
USAR_HEURISTICA_ABSORCION = True

# Terminos que descalifican una clave al buscar cada vector. Sin esto,
# "good_wavelengths" contiene la subcadena "wavelength" y se lleva la busqueda
# de longitudes de onda: un vector de ceros y unos que luego el codigo toma
# por micrometros y multiplica por mil. Silencioso y desastroso.
EXCLUIR_WL = ("good", "unit", "uncertainty", "flag", "mask")
EXCLUIR_FWHM = ("unit", "uncertainty")
EXCLUIR_BBL = ("unit", "uncertainty")

# Un vector de longitudes de onda real tiene muchos valores distintos. Si trae
# menos que esto es una mascara o una bandera, no un eje espectral.
MIN_VALORES_DISTINTOS_WL = 10

# Atributos de escala y relleno
ATRIB_ESCALA = ("scale_factor", "scale")
ATRIB_DESFASE = ("add_offset", "offset")
ATRIB_RELLENO = ("_FillValue", "FillValue", "missing_value", "fill_value")

# Ventanas de absorcion de vapor de agua, en nanometros. Las bandas que caen
# aca se marcan como malas (bbl = 0): en reflectancia de superficie no llevan
# senal util del terreno, y arrastrarlas ensucia MNF, PPI y el desmezclado.
VENTANAS_ABSORCION = [(1340.0, 1460.0), (1790.0, 1960.0)]
# Extremos del rango espectral fuera de los cuales la senal es ruido
LIMITE_ESPECTRAL = (400.0, 2450.0)

# Lineas por bloque al escribir. Controla el pico de memoria:
#   memoria ~= bandas x LINEAS_BLOQUE x muestras x 4 bytes
LINEAS_BLOQUE = 32

# Sufijos de los archivos de salida
SUF_CUBO = "_cube"
SUF_IGM = "_igm"
SUF_AUX = "_aux"

# Capas 2D agrupadas por categoria, para exponerlas como casillas
CATEGORIAS_AUX = {
    "mascaras": [
        "beta_cloud_mask", "beta_cirrus_mask", "nodata_pixels",
        "cloud_mask", "cirrus_mask",
    ],
    "atmosfera": [
        "aerosol_optical_depth", "column_water_vapour", "column_water_vapor",
    ],
    "geometria": [
        "sun_zenith", "sun_azimuth", "sensor_zenith", "sensor_azimuth",
        "sensor_to_ground_path_length",
    ],
}

# =============================================================================


class ErrorLectura(Exception):
    """Problema al abrir o interpretar el archivo."""


# -----------------------------------------------------------------------------
#  Backends
# -----------------------------------------------------------------------------
class BackendH5(object):
    """Lectura con h5py."""

    nombre = "h5py"

    def __init__(self, ruta):
        import h5py
        self._mod = h5py
        self._h5 = h5py.File(ruta, "r")
        self._ds = {}

        def _visita(nombre, obj):
            if isinstance(obj, h5py.Dataset):
                self._ds[nombre] = obj

        self._h5.visititems(_visita)
        self.error_al_cerrar = None

    def cerrar(self):
        # Se registra en vez de ignorarse: cerrar() se llama desde un finally,
        # y una excepcion aca taparia el error real que provoco la salida.
        try:
            self._h5.close()
        except (OSError, RuntimeError, ValueError) as e:
            self.error_al_cerrar = str(e)

    def datasets(self):
        return {k: (tuple(v.shape), v.dtype) for k, v in self._ds.items()}

    def atributos(self, ruta):
        return dict(self._ds[ruta].attrs.items())

    def atributos_globales(self):
        """Atributos de la raiz y de cada grupo, en un solo diccionario.

        Un HDF5 georreferenciado a la manera de CF no guarda la proyeccion en
        el dataset del cubo: la cuelga de la raiz, de un grupo, o de una
        variable suelta que solo existe para llevarla. Buscarla en un unico
        sitio es no encontrarla.
        """
        salida = {}
        try:
            salida.update(dict(self._h5.attrs.items()))
        except (OSError, RuntimeError, ValueError):
            pass

        def _visita(_nombre, obj):
            try:
                salida.update(dict(obj.attrs.items()))
            except (OSError, RuntimeError, ValueError):
                pass

        try:
            self._h5.visititems(_visita)
        except (OSError, RuntimeError, ValueError):
            pass
        return salida

    def leer_todo(self, ruta):
        return np.asarray(self._ds[ruta][:])

    def texto_estructura(self):
        """El StructMetadata del contenedor, o None si no lo trae.

        Se lee con ``[()]`` y no con ``[:]``: es un dataset escalar -una sola
        cadena larga- y rebanarlo falla.
        """
        d = self._ds.get(RUTA_ESTRUCTURA)
        if d is None:
            return None
        try:
            crudo = d[()]
        except (TypeError, ValueError, OSError):
            return None
        if isinstance(crudo, bytes):
            return crudo.decode("utf-8", "replace")
        return str(crudo)

    def leer_bloque(self, ruta, y0, y1):
        d = self._ds[ruta]
        return np.asarray(d[:, y0:y1, :] if d.ndim == 3 else d[y0:y1, :])

    # -- lectura fina -------------------------------------------------------
    # El extractor recorre el cubo entero por bloques de lineas y no necesita
    # nada mas. El explorador si: un clic pide un solo espectro, y servirlo
    # con leer_bloque leeria una fila completa de todas las bandas -megabytes
    # para devolver unos cientos de valores-.

    def leer_espectro(self, ruta, y, x):
        """Espectro de un pixel: vector de largo bandas."""
        return np.asarray(self._ds[ruta][:, y, x])

    def leer_banda(self, ruta, b):
        """Una banda completa: matriz (lineas, muestras)."""
        return np.asarray(self._ds[ruta][b, :, :])

    def leer_ventana(self, ruta, y0, y1, x0, x1):
        """Sub-cubo (bandas, ny, nx)."""
        return np.asarray(self._ds[ruta][:, y0:y1, x0:x1])


class BackendGdal(object):
    """Respaldo con GDAL, que siempre viene con QGIS."""

    nombre = "GDAL"

    def __init__(self, ruta):
        from osgeo import gdal
        gdal.UseExceptions()
        self._gdal = gdal
        raiz = gdal.Open(ruta)
        if raiz is None:
            raise ErrorLectura("GDAL no pudo abrir el archivo.")
        subs = raiz.GetSubDatasets()
        if not subs:
            raise ErrorLectura("El archivo no expone subdatasets HDF5.")
        self._sub = {}
        for uri, _desc in subs:
            # HDF5:"archivo.h5"://ruta/interna  ->  ruta/interna
            m = re.search(r"://(.+)$", uri)
            if m:
                self._sub[m.group(1).lstrip("/")] = uri
        # GDAL no expone los atributos HDF5 en el subdataset: los aplana todos
        # en los metadatos de la raiz, con la ruta del dataset como prefijo.
        # Ahi viven las longitudes de onda, el FWHM y el valor de relleno.
        self._raiz = dict(raiz.GetMetadata() or {})
        self._cache = {}

    def cerrar(self):
        self._cache.clear()
        self.error_al_cerrar = None

    def _abrir(self, ruta):
        if ruta not in self._cache:
            self._cache[ruta] = self._gdal.Open(self._sub[ruta])
        return self._cache[ruta]

    def datasets(self):
        salida = {}
        for ruta in self._sub:
            d = self._abrir(ruta)
            if d is None:
                continue
            nb = d.RasterCount
            forma = ((nb, d.RasterYSize, d.RasterXSize) if nb > 1
                     else (d.RasterYSize, d.RasterXSize))
            tipo = self._gdal.GetDataTypeName(d.GetRasterBand(1).DataType)
            salida[ruta] = (forma, np.dtype(tipo_gdal_a_numpy(tipo)))
        return salida

    def atributos(self, ruta):
        d = self._abrir(ruta)
        salida = dict(d.GetMetadata() or {}) if d is not None else {}
        prefijo = ruta.replace("/", "_") + "_"
        # Un dataset cuyo nombre extiende al nuestro (surface_reflectance y
        # surface_reflectance_uncertainty) comparte prefijo: sus atributos se
        # descartan explicitamente para no mezclarlos.
        rivales = [o.replace("/", "_") + "_" for o in self._sub
                   if o != ruta
                   and o.replace("/", "_").startswith(ruta.replace("/", "_"))]
        for k, v in self._raiz.items():
            if not k.startswith(prefijo):
                continue
            if any(k.startswith(r) for r in rivales):
                continue
            salida[k[len(prefijo):]] = v
        return salida

    def atributos_globales(self):
        """GDAL ya aplana todos los atributos del archivo en la raiz."""
        return dict(self._raiz)

    def texto_estructura(self):
        """El StructMetadata, si GDAL lo expone entre los metadatos.

        Se busca por nombre exacto y, si no aparece, por coincidencia: cada
        version del driver lo bautiza de una forma -con punto, con guion
        bajo, con o sin el grupo delante- y quedarse en un solo nombre deja
        sin georreferencia a un producto que si la trae. Con el respaldo de
        GDAL puede no estar en absoluto; entonces manda h5py, que lo lee
        siempre porque ahi es un dataset normal.
        """
        for clave in (CLAVE_ESTRUCTURA_GDAL, "StructMetadata.0"):
            if clave in self._raiz:
                return self._raiz[clave]
        for clave, valor in self._raiz.items():
            if "structmetadata" in clave.lower():
                return valor
        return None

    def _leer_crudo(self, ruta, y0, ny, x0=0, nx=None):
        """Lee bloques con ReadRaster + frombuffer, nunca con ReadAsArray.

        ReadAsArray depende del modulo gdal_array, una extension en C
        compilada contra una version concreta de numpy. Cuando la instalacion
        tiene una numpy mas nueva que la que uso GDAL al compilarse, ese
        modulo no carga ("No module named _gdal_array" tras
        "numpy.core.multiarray failed to import") y cualquier lectura falla.
        ReadRaster devuelve bytes crudos en el orden nativo de la maquina y
        no toca numpy, asi que este camino es inmune a ese desajuste."""
        d = self._abrir(ruta)
        if nx is None:
            nx = d.RasterXSize
        nb = d.RasterCount
        tipo = d.GetRasterBand(1).DataType
        npdt = np.dtype(tipo_gdal_a_numpy(self._gdal.GetDataTypeName(tipo)))
        buf = d.ReadRaster(x0, y0, nx, ny)         # todas las bandas, BSQ
        if buf is None:
            raise ErrorLectura("GDAL no devolvio datos para %s" % ruta)
        arr = np.frombuffer(buf, dtype=npdt)
        return arr.reshape(nb, ny, nx) if nb > 1 else arr.reshape(ny, nx)

    def leer_todo(self, ruta):
        return self._leer_crudo(ruta, 0, self._abrir(ruta).RasterYSize)

    def leer_bloque(self, ruta, y0, y1):
        return self._leer_crudo(ruta, y0, y1 - y0)

    # -- lectura fina -------------------------------------------------------
    def leer_espectro(self, ruta, y, x):
        """Espectro de un pixel, en una sola llamada a GDAL.

        Una llamada por banda seria lo natural y seria inservible: con 400
        bandas son 400 viajes al driver HDF5 por cada clic. ReadRaster sobre
        una ventana de 1x1 trae las 400 de una.
        """
        return self._leer_crudo(ruta, y, 1, x, 1)[:, 0, 0]

    def leer_banda(self, ruta, b):
        d = self._abrir(ruta)
        banda = d.GetRasterBand(int(b) + 1)
        npdt = np.dtype(tipo_gdal_a_numpy(
            self._gdal.GetDataTypeName(banda.DataType)))
        buf = banda.ReadRaster(0, 0, d.RasterXSize, d.RasterYSize)
        if buf is None:
            raise ErrorLectura("GDAL no devolvio la banda %s de %s" % (b, ruta))
        return np.frombuffer(buf, dtype=npdt).reshape(d.RasterYSize,
                                                      d.RasterXSize)

    def leer_ventana(self, ruta, y0, y1, x0, x1):
        return self._leer_crudo(ruta, y0, y1 - y0, x0, x1 - x0)


def tipo_gdal_a_numpy(nombre):
    return {
        "Byte": "uint8", "UInt16": "uint16", "Int16": "int16",
        "UInt32": "uint32", "Int32": "int32",
        "Float32": "float32", "Float64": "float64",
    }.get(nombre, "float32")


def abrir_backend(ruta, preferir_h5py=True):
    fallos = []
    orden = ([BackendH5, BackendGdal] if preferir_h5py
             else [BackendGdal, BackendH5])
    for clase in orden:
        try:
            return clase(ruta)
        except ImportError as e:
            fallos.append("%s: no instalado (%s)" % (clase.nombre, e))
        except Exception as e:
            fallos.append("%s: %s" % (clase.nombre, e))
    raise ErrorLectura("No pude abrir el archivo.\n  " + "\n  ".join(fallos))


# -----------------------------------------------------------------------------
#  Utilidades de metadato
# -----------------------------------------------------------------------------
def hoja(ruta):
    return ruta.rsplit("/", 1)[-1].lower()


def a_vector(valor):
    """Convierte un atributo o dataset a vector de flotantes, o None."""
    if isinstance(valor, bytes):
        valor = valor.decode("utf-8", "ignore")
    if isinstance(valor, str):
        piezas = re.split(r"[,\s]+", valor.strip().strip("{}[]"))
        try:
            return np.array([float(p) for p in piezas if p])
        except ValueError:
            return None
    try:
        return np.atleast_1d(np.asarray(valor, dtype=float)).ravel()
    except (TypeError, ValueError):
        return None


def buscar_vector(backend, inventario, n, claves, atributos, ruta_cubo,
                  excluir=()):
    """Busca un vector de longitud n asociado al cubo.

    Tres pasadas, de mas fiable a menos: dataset 1D con nombre coincidente,
    atributo cuyo nombre coincide EXACTO, y por ultimo coincidencia parcial.
    La pasada exacta va antes que la parcial a proposito: sin ese orden, el
    resultado dependeria de como iteren los atributos, y una clave que
    contiene a otra puede robarse la busqueda."""
    for ruta, (forma, _t) in inventario.items():
        h = hoja(ruta)
        if any(x in h for x in excluir):
            continue
        if len(forma) == 1 and forma[0] == n and any(c in h for c in claves):
            v = a_vector(backend.leer_todo(ruta))
            if v is not None and v.size == n:
                return ruta, v

    atr = backend.atributos(ruta_cubo)
    for k, v in atr.items():
        if k.lower() in atributos:
            vec = a_vector(v)
            if vec is not None and vec.size == n:
                return "atributo:" + k, vec
    for k, v in atr.items():
        kl = k.lower()
        if any(x in kl for x in excluir):
            continue
        if any(c in kl for c in claves):
            vec = a_vector(v)
            if vec is not None and vec.size == n:
                return "atributo:" + k, vec
    return None, None


def atributo_escalar(atributos, claves, defecto=None):
    bajas = [c.lower() for c in claves]
    for k, v in atributos.items():
        if k.lower() in bajas:
            vec = a_vector(v)
            if vec is not None and vec.size >= 1:
                return float(vec[0])
    return defecto


def formatear(valores, decimales=4, por_linea=8):
    """Formatea un vector para una cabecera ENVI."""
    if decimales == 0:
        txt = [str(int(v)) for v in valores]
    else:
        txt = ["%.*f" % (decimales, float(v)) for v in valores]
    filas = [", ".join(txt[i:i + por_linea])
             for i in range(0, len(txt), por_linea)]
    return "{\n " + ",\n ".join(filas) + "}"


def escribir_hdr(ruta, campos, listas=None):
    lineas = ["ENVI"]
    for k, v in campos.items():
        lineas.append("%s = %s" % (k, v))
    for k, v in (listas or {}).items():
        lineas.append("%s = %s" % (k, v))
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")


def borrar(ruta):
    """Borra un archivo parcial. Devuelve True si se pudo."""
    try:
        os.remove(ruta)
    except OSError:
        return False
    return True


# -----------------------------------------------------------------------------
#  Escena
# -----------------------------------------------------------------------------
class Escena(object):
    """Un producto HDF-EOS5 abierto, con cubo y metadatos ya resueltos."""

    def __init__(self, ruta, preferir_h5py=True):
        if not os.path.isfile(ruta):
            raise ErrorLectura("No existe: %s" % ruta)
        self.ruta = ruta
        self.backend = abrir_backend(ruta, preferir_h5py)
        self.inventario = self.backend.datasets()
        if not self.inventario:
            raise ErrorLectura("El archivo no contiene datasets legibles.")

        self.ruta_cubo, self.forma = self._hallar_cubo()
        self.bandas, self.lineas, self.muestras = self.forma

        atr = self.backend.atributos(self.ruta_cubo)
        self.escala = atributo_escalar(atr, ATRIB_ESCALA, 1.0) or 1.0
        self.desfase = atributo_escalar(atr, ATRIB_DESFASE, 0.0) or 0.0
        self.relleno = atributo_escalar(atr, ATRIB_RELLENO, None)

        self.origen_wl, self.wavelengths = buscar_vector(
            self.backend, self.inventario, self.bandas,
            CLAVES_WL, ATRIBUTOS_WL, self.ruta_cubo, EXCLUIR_WL)
        # Red de seguridad: si lo hallado no parece un eje espectral, se
        # descarta. Mas vale quedarse sin longitudes de onda que escribir unas
        # falsas, que nadie revisa y contaminan todo el analisis posterior.
        if (self.wavelengths is not None
                and np.unique(self.wavelengths).size < MIN_VALORES_DISTINTOS_WL):
            self.origen_wl = None
            self.wavelengths = None
        self.wl_convertidas = False
        self.unidades = "Unknown"
        if self.wavelengths is not None:
            if np.nanmax(self.wavelengths) < 100:   # venian en micrometros
                self.wavelengths = self.wavelengths * 1000.0
                self.wl_convertidas = True
            self.unidades = "Nanometers"

        self.origen_bbl, self.buenas = buscar_vector(
            self.backend, self.inventario, self.bandas,
            CLAVES_BBL, ATRIBUTOS_BBL, self.ruta_cubo, EXCLUIR_BBL)

        self.origen_fwhm, self.fwhm = buscar_vector(
            self.backend, self.inventario, self.bandas,
            CLAVES_FWHM, ATRIBUTOS_FWHM, self.ruta_cubo, EXCLUIR_FWHM)
        if (self.fwhm is not None and self.unidades == "Nanometers"
                and np.nanmax(self.fwhm) < 1.0):
            self.fwhm = self.fwhm * 1000.0

    # -- descubrimiento -----------------------------------------------------
    def _hallar_cubo(self):
        for raiz in RAICES:
            for grupo in SUBGRUPOS_DATOS:
                for nombre in NOMBRES_CUBO:
                    ruta = "%s/%s/%s" % (raiz, grupo, nombre)
                    if ruta in self.inventario:
                        return ruta, tuple(self.inventario[ruta][0])
        mejor = None
        for ruta, (forma, _t) in self.inventario.items():
            if len(forma) == 3 and BANDAS_MIN <= min(forma) <= BANDAS_MAX:
                if mejor is None or np.prod(forma) > np.prod(mejor[1]):
                    mejor = (ruta, tuple(forma))
        if mejor is None:
            raise ErrorLectura(
                "No encontre un cubo hiperespectral: ningun dataset 3D con "
                "entre %d y %d bandas." % (BANDAS_MIN, BANDAS_MAX))
        return mejor

    def hallar_geolocalizacion(self):
        """Devuelve (ruta_lon, ruta_lat), o (None, None) si no hay."""
        espacial = (self.lineas, self.muestras)
        res = {}
        for raiz in RAICES:
            for grupo in SUBGRUPOS_GEO:
                for eje, nombre in (("lat", "Latitude"), ("lon", "Longitude")):
                    ruta = "%s/%s/%s" % (raiz, grupo, nombre)
                    if ruta in self.inventario:
                        res[eje] = ruta
        if len(res) < 2:
            for ruta, (forma, _t) in self.inventario.items():
                if tuple(forma) != espacial:
                    continue
                h = hoja(ruta)
                if h in ("latitude", "lat"):
                    res.setdefault("lat", ruta)
                elif h in ("longitude", "lon"):
                    res.setdefault("lon", ruta)
        return (res.get("lon"), res.get("lat"))

    def capas_2d(self, categorias=None):
        """Capas 2D del tamano de la escena, filtradas por categoria."""
        espacial = (self.lineas, self.muestras)
        deseadas = None
        if categorias:
            deseadas = set()
            for c in categorias:
                deseadas.update(CATEGORIAS_AUX.get(c, []))
        salida = []
        for ruta in sorted(self.inventario):
            forma = tuple(self.inventario[ruta][0])
            if forma != espacial:
                continue
            h = hoja(ruta)
            if h in ("latitude", "longitude", "lat", "lon"):
                continue
            if deseadas is not None and h not in deseadas:
                continue
            salida.append(ruta)
        return salida

    def lista_bandas_malas(self):
        """bbl de ENVI: 1 = banda utilizable, 0 = descartar.

        Se parte de la lista que trae el productor, si la hay, y se le aplica
        encima la heuristica de absorcion. Una banda sobrevive solo si ambas
        la dan por buena."""
        bbl = np.ones(self.bandas, dtype=int)
        if self.buenas is not None:
            bbl = (np.asarray(self.buenas) != 0).astype(int)
        if not USAR_HEURISTICA_ABSORCION:
            return bbl
        if self.wavelengths is None or self.unidades != "Nanometers":
            return bbl
        wl = self.wavelengths
        for lo, hi in VENTANAS_ABSORCION:
            bbl[(wl >= lo) & (wl <= hi)] = 0
        bbl[(wl < LIMITE_ESPECTRAL[0]) | (wl > LIMITE_ESPECTRAL[1])] = 0
        return bbl

    def resumen(self):
        texto = [
            "Archivo    : %s" % os.path.basename(self.ruta),
            "Backend    : %s" % self.backend.nombre,
            "Cubo       : %s" % self.ruta_cubo,
            "Dimension  : %d bandas x %d lineas x %d muestras"
            % (self.bandas, self.lineas, self.muestras),
        ]
        if self.wavelengths is not None:
            texto.append(
                "Long. onda : %.1f a %.1f nm (de %s)%s"
                % (self.wavelengths.min(), self.wavelengths.max(),
                   self.origen_wl,
                   "  [convertidas de micrometros]" if self.wl_convertidas
                   else ""))
            detalle = ""
            if self.buenas is not None:
                detalle = " (%d marcadas por el productor)" % int(
                    (np.asarray(self.buenas) == 0).sum())
            texto.append("Bandas malas: %d de %d%s"
                         % (int((self.lista_bandas_malas() == 0).sum()),
                            self.bandas, detalle))
        else:
            texto.append("Long. onda : NO ENCONTRADAS (se usaran indices)")
        texto.append("FWHM       : %s"
                     % ("de %s" % self.origen_fwhm if self.fwhm is not None
                        else "no encontrado"))
        if self.relleno is not None:
            texto.append("Relleno    : %s" % self.relleno)
        if self.escala != 1.0 or self.desfase != 0.0:
            texto.append("Escala     : x%s + %s" % (self.escala, self.desfase))
        lon, lat = self.hallar_geolocalizacion()
        texto.append("Geoloc.    : %s" % ("si" if lon and lat else "no"))
        return "\n".join(texto)

    def cerrar(self):
        self.backend.cerrar()

    # -- escritura ----------------------------------------------------------
    def relleno_escalado(self):
        """El valor de relleno en las mismas unidades que el cubo escrito."""
        if self.relleno is None:
            return None
        return self.relleno * self.escala + self.desfase

    def escribir_cubo(self, prefijo, avance=None, cancelado=None,
                      lineas_bloque=LINEAS_BLOQUE):
        """Escribe el cubo en ENVI BIL. Devuelve la ruta del .dat, o None
        si se cancelo."""
        dat = prefijo + SUF_CUBO + ".dat"
        escalar = (self.escala != 1.0 or self.desfase != 0.0)

        with open(dat, "wb") as f:
            for y0 in range(0, self.lineas, lineas_bloque):
                if cancelado is not None and cancelado():
                    break
                y1 = min(y0 + lineas_bloque, self.lineas)
                trozo = np.asarray(
                    self.backend.leer_bloque(self.ruta_cubo, y0, y1),
                    dtype=np.float32)
                if escalar:
                    trozo = trozo * self.escala + self.desfase
                # (bandas, lineas, muestras) -> (lineas, bandas, muestras)=BIL
                np.ascontiguousarray(trozo.transpose(1, 0, 2)).tofile(f)
                if avance is not None:
                    avance(100.0 * y1 / self.lineas)
            else:
                self._hdr_cubo(prefijo)
                return dat
        borrar(dat)
        return None

    def _hdr_cubo(self, prefijo):
        campos = {
            "description": ("{\n  " + os.path.basename(self.ruta) + ",\n  "
                            + self.ruta_cubo + ",\n  HDF-EOS Extractor}"),
            "samples": self.muestras,
            "lines": self.lineas,
            "bands": self.bandas,
            "header offset": 0,
            "file type": "ENVI Standard",
            "data type": 4,
            "interleave": "bil",
            "byte order": 0,
            "wavelength units": self.unidades,
        }
        if self.relleno is not None:
            # El relleno se escala igual que los datos. escribir_cubo aplica
            # "crudo * escala + desfase", asi que anunciar el relleno crudo
            # junto a datos escalados describe un valor que ya no existe en
            # el archivo: los pixeles de relleno dejan de enmascararse y
            # entran en las estadisticas y en el realce como si fueran
            # medidas. Solo se nota cuando escala != 1, que es justo el caso
            # en que el cubo viene en enteros.
            campos["data ignore value"] = self.relleno_escalado()

        campos.update(self.campos_map_info())

        wl = (self.wavelengths if self.wavelengths is not None
              else np.arange(1, self.bandas + 1, dtype=float))
        listas = {"wavelength": formatear(wl, 4)}
        if self.fwhm is not None:
            listas["fwhm"] = formatear(self.fwhm, 4)
        if self.unidades == "Nanometers":
            listas["bbl"] = formatear(self.lista_bandas_malas(), 0, 20)
        escribir_hdr(prefijo + SUF_CUBO + ".hdr", campos, listas)

    def campos_map_info(self):
        """``map info`` para la cabecera ENVI, si el producto es un grid.

        Un producto ortorectificado trae su afin en el StructMetadata, y sin
        esto se perdia al extraer: el cubo ENVI salia sin georreferencia
        aunque el HDF-EOS5 de origen estuviera perfectamente ubicado, y
        cualquier programa que lo abriera despues lo ponia en coordenadas de
        pixel. Un producto en geometria de sensor no tiene afin que escribir
        -para eso esta el IGM- y aqui devuelve un diccionario vacio.
        """
        from .core.georef import EPSG_WGS84, parsear_struct_metadata

        leer = getattr(self.backend, "texto_estructura", None)
        if leer is None:
            return {}
        try:
            rejilla = parsear_struct_metadata(leer())
        except (ErrorLectura, OSError, ValueError):
            return {}
        if rejilla is None:
            return {}
        ulx, uly, lrx, lry, _nx, _ny, epsg, _nota = rejilla
        px = (lrx - ulx) / float(self.muestras)
        py = (uly - lry) / float(self.lineas)
        if not px or not py:
            return {}

        # ENVI numera el pixel de referencia desde 1 y da la coordenada de su
        # esquina superior izquierda, que es justo lo que trae el grid.
        if epsg == EPSG_WGS84:
            cabeza, cola = "Geographic Lat/Lon", "WGS-84, units=Degrees"
        elif epsg and 32600 < epsg < 32661:
            cabeza = "UTM"
            cola = "%d, North, WGS-84, units=Meters" % (epsg - 32600)
        elif epsg and 32700 < epsg < 32761:
            cabeza = "UTM"
            cola = "%d, South, WGS-84, units=Meters" % (epsg - 32700)
        else:
            # Sin proyeccion reconocida no se escribe nada: un map info con
            # un nombre inventado es peor que ninguno, porque quien lo lea le
            # va a creer.
            return {}
        return {"map info": "{%s, 1.0000, 1.0000, %.6f, %.6f, %.10g, %.10g, "
                            "%s}" % (cabeza, ulx, uly, px, py, cola)}

    def escribir_igm(self, prefijo):
        """Escribe la geometria de entrada. Devuelve la ruta o None."""
        ruta_lon, ruta_lat = self.hallar_geolocalizacion()
        if not (ruta_lon and ruta_lat):
            return None
        dat = prefijo + SUF_IGM + ".dat"
        lon = np.asarray(self.backend.leer_todo(ruta_lon), dtype=np.float64)
        lat = np.asarray(self.backend.leer_todo(ruta_lat), dtype=np.float64)
        with open(dat, "wb") as f:      # BSQ: primero X, luego Y
            lon.tofile(f)
            lat.tofile(f)
        escribir_hdr(prefijo + SUF_IGM + ".hdr", {
            "description": "{Geometria de entrada (IGM) - geograficas WGS84}",
            "samples": self.muestras, "lines": self.lineas, "bands": 2,
            "header offset": 0, "file type": "ENVI Standard",
            "data type": 5, "interleave": "bsq", "byte order": 0,
            "band names": "{Longitude (X), Latitude (Y)}",
        })
        return dat

    def escribir_auxiliares(self, prefijo, rutas):
        """Apila capas 2D en un ENVI BSQ float32. Devuelve la ruta o None."""
        if not rutas:
            return None
        dat = prefijo + SUF_AUX + ".dat"
        with open(dat, "wb") as f:
            for r in rutas:
                np.asarray(self.backend.leer_todo(r),
                           dtype=np.float32).tofile(f)
        escribir_hdr(prefijo + SUF_AUX + ".hdr", {
            "description": "{Capas auxiliares 2D - HDF-EOS Extractor}",
            "samples": self.muestras, "lines": self.lineas,
            "bands": len(rutas),
            "header offset": 0, "file type": "ENVI Standard",
            "data type": 4, "interleave": "bsq", "byte order": 0,
            "band names": "{" + ", ".join(hoja(r) for r in rutas) + "}",
        })
        return dat
