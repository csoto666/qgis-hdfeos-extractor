# -*- coding: utf-8 -*-
"""Pruebas del lector ENVI."""

import os

import numpy as np
import pytest

from conftest import (BANDAS, LINEAS, MUESTRAS, cubo_patron, escribir_envi,
                      longitudes_patron)
from hyperspectral_explorer.core.envi import (EnviError, EnviHeader,
                                              EnviSource, find_hdr, read_hdr,
                                              to_nanometers)


# -- cabecera -----------------------------------------------------------------
def test_lee_claves_de_una_linea_y_bloques_multilinea(escena):
    campos = read_hdr(escena)
    assert campos["samples"] == str(MUESTRAS)
    assert campos["interleave"] == "bil"
    # El bloque de wavelength ocupa varias lineas: tiene que llegar entero.
    assert len(campos["wavelength"].split(",")) == BANDAS


def test_rechaza_un_archivo_que_no_es_cabecera_envi(tmp_path):
    falso = tmp_path / "otro.hdr"
    falso.write_text("samples = 10\nlines = 10\n")
    with pytest.raises(EnviError, match="No parece una cabecera ENVI"):
        read_hdr(str(falso))


def test_encuentra_la_cabecera_en_las_dos_convenciones(tmp_path, datos, wl):
    suelta = escribir_envi(tmp_path, datos, "bil", wl, nombre="a")
    assert find_hdr(suelta.replace(".hdr", ".dat")) == suelta
    pegada = escribir_envi(tmp_path, datos, "bil", wl, nombre="b",
                           hdr_pegado=True)
    assert find_hdr(str(tmp_path / "b.dat")) == pegada


def test_falla_claro_cuando_no_hay_cabecera(tmp_path):
    (tmp_path / "huerfano.dat").write_bytes(b"\x00" * 16)
    with pytest.raises(EnviError, match="No se encontro la cabecera"):
        find_hdr(str(tmp_path / "huerfano.dat"))


def test_falla_cuando_la_cabecera_no_declara_dimensiones(tmp_path):
    hdr = tmp_path / "corta.hdr"
    hdr.write_text("ENVI\nsamples = 10\ninterleave = bsq\n")
    with pytest.raises(EnviError, match="samples/lines/bands"):
        EnviHeader(str(hdr))


def test_micrometros_se_convierten_a_nanometros():
    um = np.array([0.45, 1.65, 2.45])
    assert np.allclose(to_nanometers(um), [450.0, 1650.0, 2450.0])
    # Ya en nanometros no se toca.
    nm = np.array([450.0, 1650.0, 2450.0])
    assert np.allclose(to_nanometers(nm), nm)


def test_la_unidad_declarada_manda_sobre_la_magnitud():
    """Una cabecera que dice micrometros se le cree aunque los numeros sean
    grandes: la declaracion del productor pesa mas que la heuristica."""
    v = np.array([450.0, 900.0])
    assert np.allclose(to_nanometers(v, "Micrometers"), [450000.0, 900000.0])
    assert np.allclose(to_nanometers(v, "nm"), v)


def test_un_eje_espectral_de_largo_distinto_se_descarta(tmp_path, datos):
    """Mas vale sin longitudes de onda que con un eje que no es el del cubo."""
    hdr = escribir_envi(tmp_path, datos, "bil",
                        wavelengths=np.arange(BANDAS + 3) * 100.0 + 400.0)
    assert EnviHeader(hdr).wavelengths is None


def test_bbl_se_lee_como_booleanos(tmp_path, datos, wl):
    bbl = np.ones(BANDAS, dtype=int)
    bbl[3] = bbl[4] = 0
    hdr = escribir_envi(tmp_path, datos, "bil", wl, extras={
        "bbl": "{" + ", ".join(str(v) for v in bbl) + "}"})
    leida = EnviHeader(hdr).bbl
    assert leida.dtype == bool
    assert list(np.flatnonzero(~leida)) == [3, 4]


# -- binario ------------------------------------------------------------------
@pytest.mark.parametrize("intercalado", ["bsq", "bil", "bip"])
def test_los_tres_intercalados_devuelven_lo_mismo(tmp_path, intercalado):
    """El intercalado es como esta escrito el archivo, no que dice.

    Es la prueba central del lector: si el reordenamiento de ejes esta mal en
    uno de los tres, el cubo se abre igual y los espectros salen mezclados sin
    ningun error.
    """
    esperado = cubo_patron()
    hdr = escribir_envi(tmp_path, esperado, intercalado, longitudes_patron(),
                        nombre=intercalado)
    fuente = EnviSource(hdr)
    try:
        assert fuente.shape == (LINEAS, MUESTRAS, BANDAS)
        assert np.array_equal(fuente.read_pixel(3, 2), esperado[3, 2, :])
        assert np.array_equal(fuente.read_band(5), esperado[:, :, 5])
        assert np.array_equal(fuente.read_window(1, 4, 2, 5),
                              esperado[1:4, 2:5, :])
    finally:
        fuente.close()


@pytest.mark.parametrize("dtype", ["uint8", "int16", "uint16", "int32",
                                   "float32", "float64"])
def test_todos_los_tipos_de_dato(tmp_path, dtype):
    # uint8 no alcanza para el patron de posicion; se prueba con datos chicos.
    datos = (cubo_patron(3, 3, 4) % 200).astype(dtype)
    hdr = escribir_envi(tmp_path, datos, "bip", dtype=dtype, nombre=dtype)
    fuente = EnviSource(hdr)
    try:
        assert np.array_equal(fuente.read_pixel(1, 2), datos[1, 2, :])
    finally:
        fuente.close()


def test_big_endian(tmp_path):
    """byte order = 1. Sin el prefijo de orden los enteros salen permutados."""
    datos = cubo_patron().astype("int32")
    hdr = escribir_envi(tmp_path, datos, "bsq", dtype="int32", byte_order=1)
    fuente = EnviSource(hdr)
    try:
        assert np.array_equal(fuente.read_pixel(4, 1), datos[4, 1, :])
    finally:
        fuente.close()


def test_header_offset(tmp_path, datos, wl):
    """Un desplazamiento declarado se salta al mapear."""
    hdr = escribir_envi(tmp_path, datos, "bip", wl, extras={
        "header offset": 64})
    ruta_datos = hdr.replace(".hdr", ".dat")
    with open(ruta_datos, "rb") as f:
        cuerpo = f.read()
    with open(ruta_datos, "wb") as f:
        f.write(b"\xAB" * 64 + cuerpo)
    fuente = EnviSource(hdr)
    try:
        assert np.array_equal(fuente.read_pixel(2, 3), datos[2, 3, :])
    finally:
        fuente.close()


def test_binario_mas_corto_que_la_cabecera_falla_al_abrir(tmp_path, datos, wl):
    """Es el unico momento en que se puede avisar.

    Con el memmap ya hecho sobre un archivo corto, el error aparece mucho mas
    tarde y como una falla de pagina del sistema operativo, no como un
    mensaje.
    """
    hdr = escribir_envi(tmp_path, datos, "bil", wl)
    ruta_datos = hdr.replace(".hdr", ".dat")
    with open(ruta_datos, "r+b") as f:
        f.truncate(os.path.getsize(ruta_datos) // 2)
    with pytest.raises(EnviError, match="no corresponden"):
        EnviSource(hdr)
