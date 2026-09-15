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
    """Eje espectral de 450 a 1300 nm.

    Se queda corto a proposito: asi no toca las ventanas de absorcion de vapor
    de agua ni los extremos del rango, y la mascara de bandas malas no
    descarta nada. Las pruebas que usan este eje son sobre los lectores y la
    geometria, y con bandas enmascaradas de por medio estarian midiendo dos
    cosas a la vez. La mascara tiene sus propias pruebas, con un eje que si
    cruza esas ventanas.
    """
    return np.linspace(450.0, 1300.0, bandas)


def longitudes_con_absorcion(bandas=40):
    """Eje de 400 a 2500 nm: cruza las dos ventanas y los dos extremos."""
    return np.linspace(400.0, 2500.0, bandas)


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


# -----------------------------------------------------------------------------
#  HDF-EOS5 sintetico
# -----------------------------------------------------------------------------
# El cubo se guarda en enteros con escala, que es como vienen los productos de
# verdad y es el caso donde la conversion se puede equivocar sin que se note.
ESCALA_H5 = 0.0001
RELLENO_H5 = -9999
RUTA_CUBO_H5 = "HDFEOS/SWATHS/HYP/Data Fields/surface_reflectance"


#: StructMetadata de un grid UTM, como el de un producto ortorectificado.
#: Abreviado -el real trae ademas las dimensiones y los campos- pero con los
#: mismos campos que se leen, y con las tabulaciones que usa HDF-EOS.
ESTRUCTURA_GRID = """GROUP=GridStructure
\tGROUP=GRID_1
\t\tGridName="HYP"
\t\tXDim=%(nx)d
\t\tYDim=%(ny)d
\t\tUpperLeftPointMtrs=(%(ulx).6f,%(uly).6f)
\t\tLowerRightMtrs=(%(lrx).6f,%(lry).6f)
\t\tProjection=HE5_GCTP_UTM
\t\tZoneCode=%(zona)d
\t\tSphereCode=12
\t\tGridOrigin=HE5_HDFE_GD_UL
\tEND_GROUP=GRID_1
END_GROUP=GridStructure
END
"""


def estructura_grid(nx, ny, ulx=400000.0, uly=4500000.0, pixel=30.0, zona=18):
    return ESTRUCTURA_GRID % {
        "nx": nx, "ny": ny, "ulx": ulx, "uly": uly,
        "lrx": ulx + nx * pixel, "lry": uly - ny * pixel, "zona": zona}


def escribir_hdfeos(carpeta, reflectancia, wavelengths, fwhm=None,
                    buenas=None, relleno_en=(), nombre="escena",
                    geolocalizacion=True, estructura=None,
                    ejes=None, atributos=None, capas_2d=()):
    """Escribe un HDF-EOS5 con la estructura de los productos reales.

    ``reflectancia`` llega en ejes (y, x, banda) y en reflectancia; se guarda
    como entero escalado y transpuesta a (banda, y, x), que es como la
    almacena el contenedor.

    ``relleno_en`` es una lista de (y, x) que se marcan como relleno.
    """
    import h5py

    ruta = os.path.join(str(carpeta), nombre + ".h5")
    datos = np.asarray(reflectancia, dtype=np.float64)
    crudo = np.rint(datos / ESCALA_H5).astype(np.int16)
    for y, x in relleno_en:
        crudo[y, x, :] = RELLENO_H5
    cubo = np.ascontiguousarray(crudo.transpose(2, 0, 1))   # (banda, y, x)

    with h5py.File(ruta, "w") as f:
        d = f.create_dataset(RUTA_CUBO_H5, data=cubo)
        d.attrs["scale_factor"] = ESCALA_H5
        d.attrs["add_offset"] = 0.0
        d.attrs["_FillValue"] = np.int16(RELLENO_H5)
        base = "HDFEOS/SWATHS/HYP/Data Fields/"
        f.create_dataset(base + "wavelength",
                         data=np.asarray(wavelengths, dtype=np.float32))
        if fwhm is not None:
            f.create_dataset(base + "fwhm",
                             data=np.asarray(fwhm, dtype=np.float32))
        if buenas is not None:
            # El nombre lleva "good" a proposito: es el que usa Tanager y el
            # que no debe robarse la busqueda de longitudes de onda.
            f.create_dataset(base + "good_wavelengths",
                             data=np.asarray(buenas, dtype=np.uint8))
        # Un producto ortorectificado se guarda como GRID y NO trae estas dos
        # capas: su georreferencia es la afin del StructMetadata. Por eso se
        # pueden apagar, que es el caso que hay que poder probar.
        if geolocalizacion:
            geo = "HDFEOS/SWATHS/HYP/Geolocation Fields/"
            alto, ancho = datos.shape[:2]
            yy, xx = np.mgrid[0:alto, 0:ancho]
            f.create_dataset(geo + "Longitude",
                             data=(-70.0 + xx * 0.001).astype(np.float32))
            f.create_dataset(geo + "Latitude",
                             data=(-33.0 - yy * 0.001).astype(np.float32))
        if estructura:
            f.create_dataset("HDFEOS INFORMATION/StructMetadata.0",
                             data=np.bytes_(estructura.encode("utf-8")))
        # La otra forma de georreferenciar un ortho: ejes de coordenadas al
        # estilo CF, con el sistema de referencia en un atributo.
        if ejes is not None:
            x, y = ejes
            base = "HDFEOS/GRIDS/HYP/"
            f.create_dataset(base + "x", data=np.asarray(x, dtype=np.float64))
            f.create_dataset(base + "y", data=np.asarray(y, dtype=np.float64))
        # Capas auxiliares del tamano de la escena, como las del producto
        # real. Ademas de ser realistas hacen falta: con un solo array, GDAL
        # abre el archivo con el driver HDF5Image en vez de listar
        # subdatasets, y el respaldo de GDAL no tiene por donde entrar.
        for nombre_capa in capas_2d:
            f.create_dataset(base + nombre_capa,
                             data=np.zeros(datos.shape[:2], dtype=np.float32))
        for clave, valor in (atributos or {}).items():
            f.attrs[clave] = valor
    return ruta


#: Bandas del cubo HDF5 de prueba. Mas que las del cubo ENVI a proposito:
#: Escena descarta un eje espectral con menos de MIN_VALORES_DISTINTOS_WL
#: valores distintos, por sospechoso, y con nueve bandas esa red de seguridad
#: se dispara y la prueba mediria otra cosa.
BANDAS_H5 = 24


def longitudes_h5(bandas=BANDAS_H5):
    """Igual que longitudes_patron: fuera de las ventanas de absorcion."""
    return np.linspace(450.0, 1300.0, bandas)


def reflectancia_patron(lineas=LINEAS, muestras=MUESTRAS, bandas=BANDAS_H5):
    """Cubo de reflectancia cuyo valor codifica su posicion.

    Los multiplicadores son 160 y 32 y no 10000 y 100: el cubo se guarda como
    int16 con escala 0.0001, asi que el valor crudo no puede pasar de 32767.
    Con los multiplicadores grandes el patron desbordaba y las posiciones
    dejaban de ser unicas justo donde la prueba las necesita.
    """
    y = np.arange(lineas).reshape(lineas, 1, 1)
    x = np.arange(muestras).reshape(1, muestras, 1)
    b = np.arange(bandas).reshape(1, 1, bandas)
    crudo = y * 160 + x * 32 + b
    assert crudo.max() < 32767, "el patron desborda int16"
    return (crudo * ESCALA_H5).astype(np.float64)
