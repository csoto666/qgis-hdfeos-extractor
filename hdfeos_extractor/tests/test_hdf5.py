# -*- coding: utf-8 -*-
"""Pruebas de la lectura directa de HDF-EOS5.

La prueba que da sentido a todo el archivo es la ultima del segundo bloque:
que explorar el .h5 y explorar el ENVI extraido de ese mismo .h5 devuelvan
exactamente los mismos numeros. Si eso no se cumple, tener las dos rutas en
una sola herramienta es peor que no tenerlas, porque el usuario compara sin
saber que esta comparando dos cosas distintas.
"""

import numpy as np
import pytest

pytest.importorskip("h5py", reason="hace falta h5py para escribir el cubo")

from conftest import (BANDAS_H5, ESCALA_H5, LINEAS, MUESTRAS, RELLENO_H5,
                      escribir_hdfeos, longitudes_h5,
                      reflectancia_patron)
from hdfeos_extractor.core.cube import HyperspectralCube
from hdfeos_extractor.core.hdf5 import FIRMA_HDF5, Hdf5Source, es_hdf5
from hdfeos_extractor.lector import ErrorLectura


@pytest.fixture
def reflectancia():
    return reflectancia_patron()


@pytest.fixture
def escena_h5(tmp_path, reflectancia):
    return escribir_hdfeos(tmp_path, reflectancia, longitudes_h5())


@pytest.fixture
def fuente(escena_h5):
    f = Hdf5Source(escena_h5)
    yield f
    f.close()


# -- deteccion ----------------------------------------------------------------
def test_se_reconoce_por_la_firma_y_no_por_la_extension(tmp_path,
                                                        reflectancia):
    """Los productos circulan como .h5, .he5, .hdf5 y a veces sin sufijo
    util; ocho bytes son mas confiables que una lista de extensiones."""
    ruta = escribir_hdfeos(tmp_path, reflectancia, longitudes_h5(),
                           nombre="sin_extension_util")
    disfrazado = str(tmp_path / "escena.datos")
    import shutil
    shutil.copy(ruta, disfrazado)
    assert es_hdf5(disfrazado)
    assert FIRMA_HDF5 == b"\x89HDF\r\n\x1a\n"


def test_no_confunde_otros_archivos(tmp_path):
    otro = tmp_path / "cualquiera.bin"
    otro.write_bytes(b"esto no es HDF5")
    assert not es_hdf5(str(otro))
    assert not es_hdf5(str(tmp_path / "no_existe"))


# -- metadatos ----------------------------------------------------------------
def test_la_forma_se_da_vuelta_para_el_explorador(fuente):
    """El HDF5 guarda (banda, y, x) y el contrato pide (y, x, banda)."""
    assert fuente.shape == (LINEAS, MUESTRAS, BANDAS_H5)


def test_las_longitudes_de_onda_salen_del_dataset(fuente):
    assert np.allclose(fuente.wavelengths, longitudes_h5())


def test_good_wavelengths_no_se_roba_las_longitudes_de_onda(tmp_path,
                                                            reflectancia):
    """El nombre contiene "wavelength" y es un vector de ceros y unos. Sin la
    exclusion, el explorador tomaria esa mascara por el eje espectral."""
    buenas = np.ones(BANDAS_H5, dtype=np.uint8)
    buenas[2] = buenas[5] = 0
    ruta = escribir_hdfeos(tmp_path, reflectancia, longitudes_h5(),
                           buenas=buenas)
    f = Hdf5Source(ruta)
    try:
        assert np.allclose(f.wavelengths, longitudes_h5())
        assert f.bbl is not None and f.bbl.dtype == bool
        assert list(np.flatnonzero(~f.bbl)) == [2, 5]
    finally:
        f.close()


def test_el_fwhm_se_lee_cuando_esta(tmp_path, reflectancia):
    fwhm = np.full(BANDAS_H5, 7.5)
    ruta = escribir_hdfeos(tmp_path, reflectancia, longitudes_h5(),
                           fwhm=fwhm)
    f = Hdf5Source(ruta)
    try:
        assert np.allclose(f.fwhm, 7.5)
    finally:
        f.close()


def test_la_escala_y_el_relleno_no_se_delegan_al_modelo(fuente):
    """HDF5 multiplica y ENVI divide: son dos convenciones. Cada fuente
    aplica la suya y entrega reflectancia, y por eso estas quedan nulas."""
    assert fuente.relleno is None
    assert fuente.escala_reflectancia is None


def test_un_archivo_que_no_es_una_escena_falla_claro(tmp_path):
    import h5py
    ruta = str(tmp_path / "vacio.h5")
    with h5py.File(ruta, "w") as f:
        f.create_dataset("cualquier_cosa", data=np.zeros((3, 3)))
    with pytest.raises(ErrorLectura):
        Hdf5Source(ruta)


# -- lecturas -----------------------------------------------------------------
def test_espectro_banda_y_ventana(fuente, reflectancia):
    assert np.allclose(fuente.read_pixel(2, 3), reflectancia[2, 3, :],
                       atol=1e-6)
    assert np.allclose(fuente.read_band(4), reflectancia[:, :, 4], atol=1e-6)
    assert np.allclose(fuente.read_window(1, 4, 2, 5),
                       reflectancia[1:4, 2:5, :], atol=1e-6)


def test_el_orden_de_los_ejes_en_una_imagen_rectangular(fuente,
                                                        reflectancia):
    """Con una escena cuadrada un eje cambiado nunca se nota."""
    assert LINEAS != MUESTRAS
    ventana = fuente.read_window(0, LINEAS, 0, MUESTRAS)
    assert ventana.shape == (LINEAS, MUESTRAS, BANDAS_H5)
    assert np.allclose(ventana, reflectancia, atol=1e-6)


def test_la_escala_se_aplica_de_verdad(tmp_path, reflectancia):
    """Sin aplicarla, los valores saldrian en decenas de miles de cuentas."""
    ruta = escribir_hdfeos(tmp_path, reflectancia, longitudes_h5())
    f = Hdf5Source(ruta)
    try:
        crudo = f.backend.leer_espectro(f.escena.ruta_cubo, 2, 3)
        assert np.max(np.abs(crudo)) > 100          # cuentas, no reflectancia
        assert np.allclose(f.read_pixel(2, 3), crudo * ESCALA_H5, atol=1e-6)
    finally:
        f.close()


def test_el_relleno_sale_como_nan(tmp_path, reflectancia):
    """El enmascarado va antes de escalar: el relleno declarado esta en
    unidades crudas y no acierta ningun pixel si se compara ya escalado."""
    ruta = escribir_hdfeos(tmp_path, reflectancia, longitudes_h5(),
                           relleno_en=[(1, 1)])
    f = Hdf5Source(ruta)
    try:
        assert np.all(np.isnan(f.read_pixel(1, 1)))
        assert np.all(np.isfinite(f.read_pixel(2, 2)))
        assert RELLENO_H5 * ESCALA_H5 != RELLENO_H5     # no coincidirian
    finally:
        f.close()


def test_cerrar_suelta_el_archivo(escena_h5):
    """En Windows el .h5 queda bloqueado mientras el backend viva."""
    f = Hdf5Source(escena_h5)
    f.close()
    assert f.escena is None
    f.close()                                   # cerrar dos veces no revienta


# -- integrado con el modelo del cubo -----------------------------------------
def test_el_cubo_abre_el_h5_directo(escena_h5, reflectancia):
    with HyperspectralCube.load(escena_h5) as cubo:
        assert (cubo.lines, cubo.samples, cubo.bands) == (LINEAS, MUESTRAS,
                                                          BANDAS_H5)
        assert cubo.has_wavelengths
        assert np.allclose(cubo.get_spectrum(3, 2), reflectancia[2, 3, :],
                           atol=1e-6)


def test_los_transectos_funcionan_igual_que_en_envi(escena_h5, reflectancia):
    with HyperspectralCube.load(escena_h5) as cubo:
        assert np.allclose(cubo.get_transect("x", 2), reflectancia[:, 2, :],
                           atol=1e-6)
        assert np.allclose(cubo.get_transect("y", 4), reflectancia[4, :, :],
                           atol=1e-6)


def test_el_h5_y_el_envi_extraido_dan_los_mismos_numeros(tmp_path,
                                                         reflectancia):
    """La prueba que justifica tener las dos rutas en una sola herramienta.

    Se extrae el cubo con el mismo codigo que usa el algoritmo de Processing
    y se comparan las dos lecturas pixel a pixel. Si difirieran, el usuario
    estaria comparando dos cosas distintas sin saberlo.
    """
    import os
    from hdfeos_extractor.lector import Escena

    ruta = escribir_hdfeos(tmp_path, reflectancia, longitudes_h5(),
                           relleno_en=[(0, 0)])
    escena = Escena(ruta)
    try:
        prefijo = os.path.join(str(tmp_path), "extraido")
        escena.escribir_cubo(prefijo)
    finally:
        escena.backend.cerrar()

    with HyperspectralCube.load(ruta) as desde_h5, \
            HyperspectralCube.load(prefijo + "_cube.hdr") as desde_envi:
        assert desde_h5.bands == desde_envi.bands
        assert np.allclose(desde_h5.wavelengths, desde_envi.wavelengths,
                           atol=1e-3)
        for y in range(LINEAS):
            for x in range(MUESTRAS):
                a = desde_h5.get_spectrum(x, y)
                b = desde_envi.get_spectrum(x, y)
                assert np.array_equal(np.isnan(a), np.isnan(b)), (x, y)
                bueno = np.isfinite(a)
                assert np.allclose(a[bueno], b[bueno], atol=1e-6), (x, y)


def test_el_relleno_llega_enmascarado_por_las_dos_rutas(tmp_path,
                                                        reflectancia):
    """El extractor anunciaba el relleno crudo junto a datos ya escalados, y
    esos pixeles no se enmascaraban nunca del lado ENVI."""
    import os
    from hdfeos_extractor.lector import Escena

    ruta = escribir_hdfeos(tmp_path, reflectancia, longitudes_h5(),
                           relleno_en=[(1, 2)])
    escena = Escena(ruta)
    try:
        prefijo = os.path.join(str(tmp_path), "extraido")
        escena.escribir_cubo(prefijo)
    finally:
        escena.backend.cerrar()

    with HyperspectralCube.load(prefijo + "_cube.hdr") as cubo:
        assert np.all(np.isnan(cubo.get_spectrum(2, 1)))
        assert np.all(np.isfinite(cubo.get_spectrum(0, 0)))
