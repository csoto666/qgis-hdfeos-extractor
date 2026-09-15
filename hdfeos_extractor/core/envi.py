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
"""Lectura del formato nativo de ENVI: cabecera de texto mas binario crudo.

Este modulo no importa QGIS ni Qt. Se puede ejecutar y probar desde Python
puro, que es justamente el punto: el mismo nucleo tiene que servir despues
para Jupyter o para una aplicacion independiente.

Por que ENVI primero y no GeoTIFF: es el formato en el que salen los cubos
del flujo hiperespectral habitual -y el que escribe HDF-EOS Extractor, el
otro plugin de este autor-, y su cabecera es el unico de los formatos
comunes que trae las longitudes de onda, el FWHM y la lista de bandas malas
sin inventar convenciones.

El cubo NO se carga en memoria. Se abre por memoria mapeada (numpy.memmap):
el sistema operativo pagina lo que se toca y nada mas. Un cubo de 500 MB se
"abre" en microsegundos y extraer un espectro lee unos pocos kilobytes.
"""

import os
import re

import numpy as np


class EnviError(Exception):
    """Cabecera ausente, ilegible o incoherente con el binario."""


# Codigo de tipo de dato de ENVI -> dtype de numpy. Los codigos son los de
# IDL, de ahi los huecos (7, 8, 10, 11 no se usan).
TIPOS = {
    1: "u1", 2: "i2", 3: "i4", 4: "f4", 5: "f8",
    6: "c8", 9: "c16", 12: "u2", 13: "u4", 14: "i8", 15: "u8",
}

# Intercalados validos y la forma en que ordenan el binario.
FORMAS = {
    "bsq": ("bandas", "lineas", "muestras"),
    "bil": ("lineas", "bandas", "muestras"),
    "bip": ("lineas", "muestras", "bandas"),
}

# Claves de la cabecera que son listas aunque traigan un solo elemento.
CLAVES_LISTA = (
    "wavelength", "fwhm", "bbl", "band names", "data gain values",
    "data offset values", "default stretch", "z plot range",
)

# Las longitudes de onda pueden venir en micrometros. Si el maximo del vector
# cae por debajo de esto se asume um y se multiplica por mil. 100 es seguro:
# ningun sensor optico util tiene bandas por debajo de 100 nm, y 100 um son
# 100000 nm, muy por encima de cualquier hiperespectral de reflectancia.
UMBRAL_MICROMETROS = 100.0


def find_hdr(ruta):
    """Devuelve la ruta de la cabecera que acompana a ``ruta``.

    ENVI no fija una sola convencion: junto a ``escena.dat`` la cabecera
    puede llamarse ``escena.hdr`` o ``escena.dat.hdr``, y hay productos que
    entregan solo el .hdr esperando que el binario se deduzca. Se prueban
    las tres formas antes de rendirse.
    """
    if ruta.lower().endswith(".hdr"):
        return ruta
    base, _ = os.path.splitext(ruta)
    for candidata in (base + ".hdr", ruta + ".hdr"):
        if os.path.isfile(candidata):
            return candidata
    raise EnviError("No se encontro la cabecera .hdr de: %s" % ruta)


def find_binary(ruta_hdr):
    """Devuelve la ruta del binario que describe ``ruta_hdr``."""
    base, _ = os.path.splitext(ruta_hdr)
    # escena.dat.hdr -> escena.dat
    if os.path.isfile(base) and not base.lower().endswith(".hdr"):
        return base
    for ext in ("", ".dat", ".img", ".bin", ".bil", ".bsq", ".bip", ".raw"):
        candidata = base + ext
        if os.path.isfile(candidata):
            return candidata
    raise EnviError("No se encontro el binario de: %s" % ruta_hdr)


def read_hdr(ruta_hdr):
    """Analiza una cabecera ENVI y devuelve un diccionario de claves crudas.

    Los valores entre llaves pueden ocupar varias lineas, asi que no sirve
    leer linea por linea: se lee el archivo entero y se buscan los bloques
    ``clave = {...}`` antes que los ``clave = valor`` de una sola linea.
    """
    with open(ruta_hdr, "r", encoding="utf-8", errors="replace") as f:
        texto = f.read()

    if not texto.lstrip().upper().startswith("ENVI"):
        raise EnviError("No parece una cabecera ENVI: %s" % ruta_hdr)

    campos = {}
    # (1) bloques entre llaves, posiblemente multilinea
    patron_bloque = re.compile(r"^\s*([\w ./]+?)\s*=\s*\{(.*?)\}",
                               re.MULTILINE | re.DOTALL)
    for m in patron_bloque.finditer(texto):
        campos[m.group(1).strip().lower()] = m.group(2).strip()
    # (2) el resto, una linea cada uno. Se saltan las que ya se tomaron.
    for linea in texto.splitlines():
        if "=" not in linea or "{" in linea:
            continue
        clave, _, valor = linea.partition("=")
        clave = clave.strip().lower()
        if clave and clave not in campos:
            campos[clave] = valor.strip()
    return campos


def _a_lista(valor):
    """Parte un valor de cabecera en sus elementos, sin convertir tipos."""
    return [t.strip() for t in re.split(r"[,\n]", valor) if t.strip()]


def _a_numeros(valor):
    """Convierte un valor de cabecera en un vector float.

    Los elementos no numericos se descartan en silencio: hay productores que
    dejan unidades sueltas dentro de la lista de longitudes de onda.
    """
    numeros = []
    for t in _a_lista(valor):
        try:
            numeros.append(float(t))
        except ValueError:
            continue
    return np.asarray(numeros, dtype=np.float64)


def to_nanometers(wl, unidad=None):
    """Devuelve las longitudes de onda en nanometros.

    Se respeta ``wavelength units`` cuando la cabecera la declara; cuando no,
    se decide por la magnitud del vector. Equivocarse aca es caro y
    silencioso: un cubo en micrometros leido como nanometros pone todas las
    bandas entre 0.4 y 2.5 nm y cualquier busqueda por longitud de onda
    devuelve siempre la banda 0.
    """
    if wl is None or wl.size == 0:
        return wl
    if unidad:
        u = unidad.strip().lower()
        if u in ("micrometers", "micrometer", "um", "microns", "micron"):
            return wl * 1000.0
        if u in ("nanometers", "nanometer", "nm"):
            return wl
    if float(np.nanmax(wl)) < UMBRAL_MICROMETROS:
        return wl * 1000.0
    return wl


class EnviHeader(object):
    """Los campos de una cabecera ENVI ya convertidos a tipos de Python."""

    def __init__(self, ruta_hdr):
        self.ruta = ruta_hdr
        self.campos = read_hdr(ruta_hdr)
        c = self.campos

        try:
            self.lineas = int(c["lines"])
            self.muestras = int(c["samples"])
            self.bandas = int(c["bands"])
        except (KeyError, ValueError):
            raise EnviError(
                "La cabecera no declara samples/lines/bands: %s" % ruta_hdr)

        codigo = int(c.get("data type", 4))
        if codigo not in TIPOS:
            raise EnviError("Tipo de dato ENVI no soportado: %s" % codigo)
        # byte order 1 = big endian. numpy lo expresa con el prefijo.
        orden = ">" if str(c.get("byte order", "0")).strip() == "1" else "<"
        self.dtype = np.dtype(orden + TIPOS[codigo])

        self.intercalado = str(c.get("interleave", "bsq")).strip().lower()
        if self.intercalado not in FORMAS:
            raise EnviError("Intercalado desconocido: %s" % self.intercalado)

        self.desplazamiento = int(c.get("header offset", 0))
        self.descripcion = c.get("description", "")

        self.wavelengths = to_nanometers(
            _a_numeros(c["wavelength"]) if "wavelength" in c else None,
            c.get("wavelength units"))
        self.fwhm = _a_numeros(c["fwhm"]) if "fwhm" in c else None
        self.nombres_banda = (_a_lista(c["band names"])
                              if "band names" in c else None)

        # bbl: 1 = banda buena. Se guarda como booleano porque asi se usa.
        self.bbl = None
        if "bbl" in c:
            crudo = _a_numeros(c["bbl"])
            if crudo.size == self.bandas:
                self.bbl = crudo.astype(bool)

        self.relleno = _escalar(c, ("data ignore value",))
        # ENVI llama "reflectance scale factor" a un divisor, no a un factor.
        self.escala_reflectancia = _escalar(
            c, ("reflectance scale factor", "scale factor"))

        self._validar_vectores()

    def _validar_vectores(self):
        """Descarta los vectores espectrales cuyo largo no es el de bandas.

        Un vector de longitudes de onda de largo distinto no es un eje
        espectral parcial: es otra cosa mal etiquetada. Usarlo produce
        graficos que parecen correctos y no lo son, asi que se tira.
        """
        for nombre in ("wavelengths", "fwhm"):
            v = getattr(self, nombre)
            if v is not None and v.size != self.bandas:
                setattr(self, nombre, None)
        if (self.nombres_banda is not None
                and len(self.nombres_banda) != self.bandas):
            self.nombres_banda = None

    @property
    def forma_binaria(self):
        """Forma del array tal como esta escrito en disco."""
        dim = {"lineas": self.lineas, "muestras": self.muestras,
               "bandas": self.bandas}
        return tuple(dim[e] for e in FORMAS[self.intercalado])

    def bytes_esperados(self):
        return (self.lineas * self.muestras * self.bandas
                * self.dtype.itemsize + self.desplazamiento)


def _escalar(campos, claves, defecto=None):
    for k in claves:
        if k in campos:
            try:
                return float(campos[k])
            except (TypeError, ValueError):
                continue
    return defecto


class EnviSource(object):
    """Acceso por memoria mapeada a un cubo ENVI.

    Expone las cuatro lecturas que el resto del programa necesita -pixel,
    banda, transecto y ventana- y se encarga de que las tres formas de
    intercalado devuelvan siempre ejes ``(y, x, banda)``. Nadie fuera de
    esta clase deberia saber si el archivo es BIL, BSQ o BIP.
    """

    def __init__(self, ruta, solo_lectura=True):
        self.ruta_hdr = find_hdr(ruta)
        self.cabecera = EnviHeader(self.ruta_hdr)
        self.ruta_datos = find_binary(self.ruta_hdr)

        tamano = os.path.getsize(self.ruta_datos)
        esperado = self.cabecera.bytes_esperados()
        if tamano < esperado:
            raise EnviError(
                "El binario mide %d bytes y la cabecera declara %d. "
                "Cabecera y datos no corresponden." % (tamano, esperado))

        self.datos = np.memmap(
            self.ruta_datos, dtype=self.cabecera.dtype,
            mode="r" if solo_lectura else "r+",
            offset=self.cabecera.desplazamiento,
            shape=self.cabecera.forma_binaria)

    # -- metadatos ----------------------------------------------------------
    @property
    def shape(self):
        """(lineas, muestras, bandas), siempre en ese orden."""
        c = self.cabecera
        return (c.lineas, c.muestras, c.bandas)

    # El contrato de fuente pide estos cinco campos al lado de los datos. En
    # ENVI viven en la cabecera, asi que se reenvian en vez de copiarse: una
    # copia se desincroniza en cuanto alguien toque la cabecera.
    @property
    def wavelengths(self):
        return self.cabecera.wavelengths

    @property
    def fwhm(self):
        return self.cabecera.fwhm

    @property
    def bbl(self):
        return self.cabecera.bbl

    @property
    def nombres_banda(self):
        return self.cabecera.nombres_banda

    @property
    def relleno(self):
        return self.cabecera.relleno

    @property
    def escala_reflectancia(self):
        return self.cabecera.escala_reflectancia

    @property
    def georreferencia(self):
        """Lo que la cabecera diga de ``map info``; nunca una suposicion.

        Se resuelve cada vez en vez de guardarse en el constructor porque es
        barato -son siete numeros de un campo de texto- y porque asi una
        cabecera corregida en disco se refleja al reabrir sin caches raros
        de por medio.
        """
        from .georef import Georreferencia
        return Georreferencia.de_envi(self.cabecera.campos)

    # -- lecturas -----------------------------------------------------------
    def read_pixel(self, y, x):
        """Espectro completo de un pixel: vector de largo ``bandas``."""
        i = self.cabecera.intercalado
        if i == "bil":
            v = self.datos[y, :, x]
        elif i == "bsq":
            v = self.datos[:, y, x]
        else:
            v = self.datos[y, x, :]
        return np.asarray(v)

    def read_band(self, b):
        """Una banda completa: matriz ``(lineas, muestras)``."""
        i = self.cabecera.intercalado
        if i == "bil":
            m = self.datos[:, b, :]
        elif i == "bsq":
            m = self.datos[b, :, :]
        else:
            m = self.datos[:, :, b]
        return np.asarray(m)

    def read_window(self, y0, y1, x0, x1):
        """Sub-cubo ``(dy, dx, bandas)`` con los ejes ya ordenados."""
        i = self.cabecera.intercalado
        if i == "bil":
            v = self.datos[y0:y1, :, x0:x1].transpose(0, 2, 1)
        elif i == "bsq":
            v = self.datos[:, y0:y1, x0:x1].transpose(1, 2, 0)
        else:
            v = self.datos[y0:y1, x0:x1, :]
        return np.asarray(v)

    def close(self):
        """Suelta la memoria mapeada.

        En Windows el archivo queda bloqueado mientras el memmap viva, y el
        usuario no puede mover ni reescribir el cubo desde QGIS. Por eso hay
        cierre explicito y no solo recoleccion de basura.
        """
        datos = getattr(self, "datos", None)
        if datos is not None:
            if hasattr(datos, "_mmap") and datos._mmap is not None:
                datos._mmap.close()
            self.datos = None
