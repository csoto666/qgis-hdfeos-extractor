# -*- coding: utf-8 -*-
"""Pruebas del modelo semantico del cubo."""

import numpy as np
import pytest

from conftest import (BANDAS, LINEAS, MUESTRAS, cubo_patron, escribir_envi,
                      longitudes_patron)
from hyperspectral_explorer.core.cube import CubeError, HyperspectralCube


@pytest.fixture
def cubo(escena):
    c = HyperspectralCube.load(escena)
    yield c
    c.close()


@pytest.fixture
def memoria(datos, wl):
    return HyperspectralCube.from_array(datos, wl, name="memoria")


# -- apertura -----------------------------------------------------------------
def test_abre_envi_con_su_eje_espectral(cubo):
    assert (cubo.lines, cubo.samples, cubo.bands) == (LINEAS, MUESTRAS, BANDAS)
    assert cubo.has_wavelengths
    assert np.allclose(cubo.wavelengths, longitudes_patron())
    assert cubo.unidad_espectral == "nm"


def test_sin_longitudes_de_onda_el_eje_pasa_a_ser_el_indice(tmp_path, datos):
    """Un cubo sin eje espectral se abre igual: el grafico queda en numero de
    banda, que es peor que nanometros pero mucho mejor que no abrirlo."""
    hdr = escribir_envi(tmp_path, datos, "bsq", wavelengths=None)
    with HyperspectralCube.load(hdr) as c:
        assert not c.has_wavelengths
        assert np.array_equal(c.wavelengths, np.arange(BANDAS))
        assert c.unidad_espectral == "banda"


def test_abrir_algo_que_no_existe_da_un_error_del_nucleo(tmp_path):
    with pytest.raises(CubeError, match="No existe"):
        HyperspectralCube.load(str(tmp_path / "fantasma.dat"))


# -- eje espectral ------------------------------------------------------------
def test_la_banda_se_busca_por_la_mas_cercana(cubo):
    """Nadie sabe de memoria la longitud de onda exacta de su sensor."""
    wl = longitudes_patron()
    assert cubo.band_index(wl[4]) == 4
    assert cubo.band_index(wl[4] + 20.0) == 4        # un poco arriba
    assert cubo.band_index(wl[4] - 20.0) == 4        # un poco abajo
    assert cubo.band_index(0.0) == 0                 # fuera por abajo
    assert cubo.band_index(99999.0) == BANDAS - 1    # fuera por arriba
    assert cubo.nearest_wavelength(wl[4] + 20.0) == pytest.approx(wl[4])


def test_pedir_una_banda_sin_decir_cual_falla(cubo):
    with pytest.raises(CubeError, match="wavelength o index"):
        cubo.get_band()


def test_indice_de_banda_fuera_de_rango(cubo):
    with pytest.raises(CubeError, match="fuera de rango"):
        cubo.get_band(index=BANDAS)


# -- lecturas -----------------------------------------------------------------
def test_espectro_de_pixel(cubo, datos):
    assert np.array_equal(cubo.get_spectrum(3, 2), datos[2, 3, :])


def test_el_orden_de_get_spectrum_es_x_y_no_y_x(cubo, datos):
    """La confusion mas facil de todo el proyecto.

    El cubo se indexa (y, x) y la interfaz habla en (x, y). Con una imagen
    cuadrada esto nunca falla y con una rectangular falla siempre, asi que la
    prueba usa una rectangular a proposito.
    """
    assert LINEAS != MUESTRAS
    assert np.array_equal(cubo.get_spectrum(x=4, y=6), datos[6, 4, :])


def test_pixel_fuera_de_la_imagen(cubo):
    with pytest.raises(CubeError, match="fuera de la imagen"):
        cubo.get_spectrum(MUESTRAS, 0)
    with pytest.raises(CubeError, match="fuera de la imagen"):
        cubo.get_spectrum(0, -1)


def test_banda_completa(cubo, datos):
    assert np.array_equal(cubo.get_band(index=6), datos[:, :, 6])


def test_transecto_en_x_recorre_las_filas(cubo, datos):
    """x fijo: sale (lineas, bandas)."""
    t = cubo.get_transect("x", 2)
    assert t.shape == (LINEAS, BANDAS)
    assert np.array_equal(t, datos[:, 2, :])


def test_transecto_en_y_recorre_las_columnas(cubo, datos):
    """y fijo: sale (muestras, bandas)."""
    t = cubo.get_transect("y", 5)
    assert t.shape == (MUESTRAS, BANDAS)
    assert np.array_equal(t, datos[5, :, :])


def test_los_atajos_de_perfil_son_el_mismo_transecto(cubo):
    assert np.array_equal(cubo.get_x_profile(1), cubo.get_transect("x", 1))
    assert np.array_equal(cubo.get_y_profile(1), cubo.get_transect("y", 1))


def test_transecto_con_eje_invalido(cubo):
    with pytest.raises(CubeError, match="'x' o 'y'"):
        cubo.get_transect("z", 0)


def test_transecto_fuera_de_rango(cubo):
    with pytest.raises(CubeError, match="Columna"):
        cubo.get_transect("x", MUESTRAS)
    with pytest.raises(CubeError, match="Fila"):
        cubo.get_transect("y", LINEAS)


def test_roi_incluye_los_dos_extremos(cubo, datos):
    roi = cubo.get_roi(1, 2, 3, 4)
    assert roi.shape == (3, 3, BANDAS)      # filas 2..4, columnas 1..3
    assert np.array_equal(roi, datos[2:5, 1:4, :])


def test_roi_arrastrado_al_reves_y_fuera_del_borde(cubo, datos):
    """Un rectangulo dibujado con el raton empieza donde el usuario apreto,
    que puede ser la esquina de abajo, y puede salirse de la imagen."""
    al_reves = cubo.get_roi(3, 4, 1, 2)
    assert np.array_equal(al_reves, datos[2:5, 1:4, :])
    recortado = cubo.get_roi(-5, -5, 1, 1)
    assert np.array_equal(recortado, datos[0:2, 0:2, :])


def test_roi_totalmente_fuera(cubo):
    with pytest.raises(CubeError, match="no toca la imagen"):
        cubo.get_roi(MUESTRAS + 2, LINEAS + 2, MUESTRAS + 5, LINEAS + 5)


def test_varios_pixeles_sueltos(cubo, datos):
    m = cubo.get_pixels([(0, 0), (4, 6), (2, 3)])
    assert m.shape == (3, BANDAS)
    assert np.array_equal(m[1], datos[6, 4, :])


def test_lista_de_pixeles_vacia(cubo):
    with pytest.raises(CubeError, match="vacia"):
        cubo.get_pixels([])


# -- relleno y escala ---------------------------------------------------------
def test_el_valor_de_relleno_sale_como_nan(tmp_path, wl):
    datos = cubo_patron()
    datos[1, 1, :] = -9999.0
    hdr = escribir_envi(tmp_path, datos, "bil", wl,
                        extras={"data ignore value": -9999})
    with HyperspectralCube.load(hdr) as c:
        assert np.all(np.isnan(c.get_spectrum(1, 1)))
        assert np.all(np.isfinite(c.get_spectrum(2, 2)))


def test_la_escala_de_reflectancia_es_un_divisor(tmp_path, wl):
    """ENVI llama "reflectance scale factor" a lo que divide, no a lo que
    multiplica. Invertirlo deja los espectros en decenas de miles."""
    datos = np.full((3, 3, BANDAS), 5000.0, dtype=np.float32)
    hdr = escribir_envi(tmp_path, datos, "bip", wl,
                        extras={"reflectance scale factor": 10000})
    with HyperspectralCube.load(hdr) as c:
        assert np.allclose(c.get_spectrum(0, 0), 0.5)
    with HyperspectralCube.load(hdr, aplicar_escala=False) as c:
        assert np.allclose(c.get_spectrum(0, 0), 5000.0)


# -- cache y despliegue -------------------------------------------------------
def test_la_banda_cacheada_no_es_modificable(cubo):
    """El cache se comparte entre el compositor y quien lo pida. Si alguien
    escribe encima, el siguiente lector recibe datos alterados sin saberlo."""
    banda = cubo.get_band(index=0)
    assert not banda.flags.writeable
    with pytest.raises(ValueError):
        banda[0, 0] = 1.0


def test_la_banda_cacheada_no_sostiene_el_memmap(cubo):
    """El cache tiene que guardar los datos, no una vista del archivo."""
    banda = cubo.get_band(index=0)
    assert banda.base is None or not hasattr(banda.base, "_mmap")


def test_el_cache_no_crece_sin_limite(datos, wl):
    from hyperspectral_explorer.core import cube as mod
    c = HyperspectralCube.from_array(datos, wl)
    for i in range(BANDAS):
        c.get_band(index=i)
    assert len(c._cache) <= mod.BANDAS_EN_CACHE


def test_la_vista_previa_submuestrea_sin_promediar(memoria):
    """Promediar inventaria espectros que no existen en la escena."""
    banda, paso = memoria.preview_band(index=0, max_lado=3)
    assert paso == 3
    assert banda.shape == (3, 2)
    assert np.array_equal(banda, memoria.get_band(index=0)[::3, ::3])


def test_la_vista_previa_de_un_cubo_chico_no_submuestrea(memoria):
    banda, paso = memoria.preview_band(index=0, max_lado=1024)
    assert paso == 1
    assert banda.shape == (LINEAS, MUESTRAS)


# -- interoperabilidad --------------------------------------------------------
def test_from_array_y_dims(memoria, datos):
    assert memoria.dims == ("y", "x", "wavelength")
    assert np.array_equal(memoria.get_spectrum(1, 2), datos[2, 1, :])


def test_to_xarray_avisa_cuando_falta_xarray(memoria):
    pytest.importorskip
    try:
        import xarray                     # noqa: F401
    except ImportError:
        with pytest.raises(CubeError, match="xarray"):
            memoria.to_xarray()
    else:
        da = memoria.to_xarray()
        assert da.dims == ("y", "x", "wavelength")
        assert np.allclose(da.coords["wavelength"], longitudes_patron())


def test_repr_dice_dimensiones_y_rango(cubo):
    texto = repr(cubo)
    assert "7 x 5 x 9" in texto and "nm" in texto
