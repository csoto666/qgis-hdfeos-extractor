# -*- coding: utf-8 -*-
"""Utilidades compartidas por las pruebas.

Todo el nucleo se prueba contra cubos ENVI sinteticos escritos en el momento.
No hay archivos de datos en el repositorio a proposito: un cubo hiperespectral
de prueba pesa mas que todo el codigo, y uno recortado hasta que quepa deja de
ejercitar justamente lo que importa -los tres intercalados, el orden de bytes,
el relleno-.
"""

import collections
import os
import sys

import numpy as np
import pytest

# El paquete se importa desde la raiz del repositorio, como lo hace QGIS.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

LINEAS, MUESTRAS, BANDAS = 7, 5, 9

# Codigo de tipo ENVI para cada dtype de numpy que usan las pruebas.
CODIGOS = {"uint8": 1, "int16": 2, "int32": 3, "float32": 4, "float64": 5,
           "uint16": 12}


def cubo_patron(lineas=LINEAS, muestras=MUESTRAS, bandas=BANDAS):
    """Cubo ``(y, x, banda)`` donde cada valor codifica su propia posicion.

    ``valor = y*10000 + x*100 + banda``. Asi cualquier confusion de ejes
    -leer la fila por la columna, el intercalado cambiado- salta a la vista en
    el numero mismo, en vez de esconderse detras de un array que "parece"
    razonable.
    """
    y = np.arange(lineas).reshape(lineas, 1, 1)
    x = np.arange(muestras).reshape(1, muestras, 1)
    b = np.arange(bandas).reshape(1, 1, bandas)
    return (y * 10000 + x * 100 + b).astype(np.float32)


def longitudes_patron(bandas=BANDAS):
    """Eje espectral regular de 450 a 2450 nm."""
    return np.linspace(450.0, 2450.0, bandas)


def escribir_envi(carpeta, datos, intercalado="bil", wavelengths=None,
                  dtype="float32", byte_order=0, extras=None,
                  nombre="escena", ext=".dat", hdr_pegado=False):
    """Escribe un cubo ``(y, x, banda)`` como ENVI y devuelve la ruta del .hdr.

    ``hdr_pegado`` escribe ``escena.dat.hdr`` en vez de ``escena.hdr``, que es
    la otra convencion que hay en circulacion.
    """
    lineas, muestras, bandas = datos.shape
    arr = datos.astype(dtype)
    if intercalado == "bsq":
        binario = arr.transpose(2, 0, 1)
    elif intercalado == "bil":
        binario = arr.transpose(0, 2, 1)
    elif intercalado == "bip":
        binario = arr
    else:
        raise ValueError(intercalado)

    orden = ">" if byte_order else "<"
    ruta_datos = os.path.join(str(carpeta), nombre + ext)
    np.ascontiguousarray(binario).astype(orden + np.dtype(dtype).str[1:]) \
        .tofile(ruta_datos)

    ruta_hdr = (ruta_datos + ".hdr" if hdr_pegado
                else os.path.join(str(carpeta), nombre + ".hdr"))
    # Un diccionario y no una lista: asi ``extras`` reemplaza un valor por
    # defecto en vez de agregar una segunda linea con la misma clave, que es
    # una cabecera que ningun productor escribe y que la prueba no deberia
    # inventar.
    campos = collections.OrderedDict([
        ("description", "{cubo sintetico de prueba}"),
        ("samples", muestras),
        ("lines", lineas),
        ("bands", bandas),
        ("header offset", 0),
        ("file type", "ENVI Standard"),
        ("data type", CODIGOS[dtype]),
        ("interleave", intercalado),
        ("byte order", byte_order),
    ])
    if wavelengths is not None:
        # A proposito partido en varias lineas: es como salen las cabeceras
        # reales y es el caso que rompe a los lectores linea a linea.
        txt = ["%.4f" % v for v in wavelengths]
        filas = [", ".join(txt[i:i + 4]) for i in range(0, len(txt), 4)]
        campos["wavelength"] = "{\n " + ",\n ".join(filas) + "}"
    campos.update(extras or {})

    with open(ruta_hdr, "w", encoding="utf-8") as f:
        f.write("ENVI\n")
        f.write("\n".join("%s = %s" % kv for kv in campos.items()) + "\n")
    return ruta_hdr


@pytest.fixture
def datos():
    return cubo_patron()


@pytest.fixture
def wl():
    return longitudes_patron()


@pytest.fixture
def escena(tmp_path, datos, wl):
    """Un cubo ENVI BIL en float32 con longitudes de onda."""
    return escribir_envi(tmp_path, datos, "bil", wl)
