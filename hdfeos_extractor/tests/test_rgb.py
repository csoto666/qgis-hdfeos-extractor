# -*- coding: utf-8 -*-
"""Pruebas del compositor RGB."""

import numpy as np
import pytest

from conftest import BANDAS, LINEAS, MUESTRAS, cubo_patron, longitudes_patron
from hdfeos_extractor.core.cube import HyperspectralCube
from hdfeos_extractor.core.rgb import PRESETS, RGBComposer, estirar


@pytest.fixture
def cubo():
    return HyperspectralCube.from_array(cubo_patron(), longitudes_patron())


# -- realce -------------------------------------------------------------------
def test_minmax_lleva_los_extremos_a_cero_y_uno():
    banda = np.arange(100, dtype=np.float32).reshape(10, 10)
    salida = estirar(banda, "minmax")
    assert salida.min() == 0.0 and salida.max() == 1.0


def test_percentil_recorta_las_colas():
    """Un pixel saturado -una nube, un techo metalico- no debe dejar el resto
    de la escena en negro."""
    banda = np.linspace(0.0, 1.0, 100, dtype=np.float32).reshape(10, 10)
    banda[9, 9] = 1000.0
    # Con minmax, los 1000 se llevan todo el rango y la escena desaparece.
    assert estirar(banda, "minmax")[5, 5] < 0.01
    # Con percentil, la escena conserva el contraste que tendria sin el pixel
    # raro, y el pixel raro satura.
    limpia = banda.copy()
    limpia[9, 9] = np.nan
    con_outlier = estirar(banda, "percentil")
    sin_outlier = estirar(limpia, "percentil")
    assert con_outlier[5, 5] == pytest.approx(sin_outlier[5, 5], abs=0.05)
    assert con_outlier[9, 9] == 1.0


def test_reflectancia_no_mira_los_datos():
    """Es el unico modo con el que dos escenas se pueden comparar a ojo."""
    a = estirar(np.full((4, 4), 0.25, dtype=np.float32), "reflectancia")
    b = estirar(np.full((4, 4), 0.75, dtype=np.float32), "reflectancia")
    assert np.allclose(a, 0.25) and np.allclose(b, 0.75)


def test_desviacion_centra_en_la_media():
    rng = np.random.default_rng(0)
    banda = rng.normal(0.3, 0.05, (50, 50)).astype(np.float32)
    salida = estirar(banda, "desviacion", sigmas=2.0)
    assert 0.0 <= salida.min() and salida.max() <= 1.0
    assert np.median(salida) == pytest.approx(0.5, abs=0.05)


def test_una_banda_constante_sale_gris_medio():
    """Ni negra ni blanca: las dos sugieren una estructura que no hay."""
    salida = estirar(np.full((5, 5), 7.0, dtype=np.float32))
    assert np.allclose(salida, 0.5)


def test_los_nan_no_entran_en_el_calculo_y_salen_en_cero():
    banda = np.arange(100, dtype=np.float32).reshape(10, 10)
    banda[0, :] = np.nan
    salida = estirar(banda, "minmax")
    assert np.all(salida[0, :] == 0.0)
    assert np.isfinite(salida).all()
    # El maximo sigue siendo el maximo de los datos validos.
    assert salida.max() == 1.0


def test_una_banda_toda_nan_no_revienta():
    salida = estirar(np.full((4, 4), np.nan, dtype=np.float32))
    assert salida.shape == (4, 4) and np.all(salida == 0.0)


def test_el_realce_se_queda_dentro_de_cero_uno():
    rng = np.random.default_rng(1)
    banda = rng.normal(0.4, 0.3, (40, 40)).astype(np.float32)
    for modo in ("percentil", "minmax", "reflectancia", "desviacion"):
        salida = estirar(banda, modo)
        assert salida.min() >= 0.0 and salida.max() <= 1.0, modo


# -- composicion --------------------------------------------------------------
def test_la_composicion_tiene_la_forma_y_el_tipo_de_una_imagen(cubo):
    rgb = RGBComposer().create_composite(cubo)
    assert rgb.shape == (LINEAS, MUESTRAS, 3)
    assert rgb.dtype == np.uint8


def test_en_float_se_queda_entre_cero_y_uno(cubo):
    rgb = RGBComposer().create_composite(cubo, as_uint8=False)
    assert rgb.dtype == np.float32
    assert rgb.min() >= 0.0 and rgb.max() <= 1.0


def test_el_compositor_no_toca_el_cubo(cubo):
    """La regla que no se negocia: esto es una capa de visualizacion.

    El espectro medido tiene que ser identico antes y despues de cambiar
    cualquier control de la pantalla.
    """
    antes = cubo.get_spectrum(2, 3).copy()
    for modo in ("percentil", "minmax", "reflectancia", "desviacion"):
        RGBComposer(modo=modo).create_composite(cubo)
    RGBComposer(660, 550, 470).create_composite(cubo, as_uint8=False)
    assert np.array_equal(cubo.get_spectrum(2, 3), antes)


def test_cada_canal_sale_de_la_banda_que_se_pidio():
    """Tres bandas distintas tienen que dar tres canales distintos; si el
    compositor usara siempre la misma, la imagen saldria gris y nadie lo
    notaria.

    El cubo patron no sirve aca: sus bandas se diferencian por una constante,
    y un realce correcto normaliza justamente eso. Hace falta un cubo cuyas
    bandas tengan estructura espacial distinta, que es lo que pasa de verdad.
    """
    rng = np.random.default_rng(7)
    datos = rng.random((LINEAS, MUESTRAS, BANDAS)).astype(np.float32)
    cubo = HyperspectralCube.from_array(datos, longitudes_patron())
    wl = longitudes_patron()
    c = RGBComposer(wl[8], wl[4], wl[0])
    assert c.bands_of(cubo) == (8, 4, 0)
    rgb = c.create_composite(cubo, as_uint8=False)
    assert not np.array_equal(rgb[:, :, 0], rgb[:, :, 1])
    assert not np.array_equal(rgb[:, :, 1], rgb[:, :, 2])


def test_las_bandas_se_eligen_por_longitud_de_onda_no_por_indice(cubo):
    """Es lo que hace portables a los presets entre sensores distintos."""
    c = RGBComposer(660.0, 550.0, 470.0)
    assert c.bands_of(cubo) == tuple(cubo.band_index(w)
                                     for w in (660.0, 550.0, 470.0))
    reales = c.wavelengths_of(cubo)
    assert all(r in list(cubo.wavelengths) for r in reales)


def test_set_bands_deja_intactas_las_que_no_se_pasan():
    c = RGBComposer(800.0, 600.0, 400.0)
    c.set_bands(red=850.0)
    assert (c.red, c.green, c.blue) == (850.0, 600.0, 400.0)


def test_los_presets_existen_y_se_aplican():
    c = RGBComposer()
    assert "Color natural" in c.presets()
    c.set_preset("Falso color IR")
    assert (c.red, c.green, c.blue) == PRESETS["Falso color IR"]


def test_un_preset_inexistente_falla_de_una():
    with pytest.raises(KeyError):
        RGBComposer().set_preset("Ultravioleta")


def test_solo_se_ofrecen_los_presets_que_el_sensor_alcanza():
    """Un preset SWIR sobre un cubo que llega a 900 nm no falla: devuelve la
    ultima banda tres veces y el usuario ve gris sin entender por que."""
    vnir = HyperspectralCube.from_array(
        cubo_patron(4, 4, 6), np.linspace(450.0, 900.0, 6))
    aplicables = RGBComposer.presets_aplicables(vnir)
    assert "Color natural" in aplicables
    assert "Falso color IR" in aplicables
    assert "Suelos y geologia" not in aplicables     # pide 2200 nm
    completo = HyperspectralCube.from_array(
        cubo_patron(4, 4, 20), np.linspace(400.0, 2500.0, 20))
    assert set(RGBComposer.presets_aplicables(completo)) == set(PRESETS)


def test_la_vista_previa_sale_mas_chica_pero_igual_de_valida():
    grande = HyperspectralCube.from_array(
        cubo_patron(60, 40, BANDAS), longitudes_patron())
    c = RGBComposer(longitudes_patron()[0], longitudes_patron()[1],
                    longitudes_patron()[2])
    completa = c.create_composite(grande)
    previa = c.create_composite(grande, preview=True, max_lado=20)
    assert completa.shape == (60, 40, 3)
    assert max(previa.shape[:2]) <= 20
    assert previa.dtype == np.uint8


# -- limites compartidos con QGIS ---------------------------------------------
def test_los_limites_son_los_que_usa_el_estiramiento():
    """QGIS realza la capa con su propio motor; para que el mapa y el grafico
    coincidan tienen que partir del mismo par (lo, hi)."""
    from hdfeos_extractor.core.rgb import limites
    rng = np.random.default_rng(3)
    banda = rng.normal(0.3, 0.1, (30, 30)).astype(np.float32)
    for modo in ("percentil", "minmax", "reflectancia", "desviacion"):
        lo, hi = limites(banda, modo)
        estirada = estirar(banda, modo)
        centro = (lo + hi) / 2.0
        esperado = np.clip((centro - lo) / (hi - lo), 0.0, 1.0)
        # El punto medio del rango tiene que caer en 0.5 del estiramiento.
        i = int(np.argmin(np.abs(banda - centro)))
        y, x = np.unravel_index(i, banda.shape)
        real = (banda[y, x] - lo) / (hi - lo)
        assert estirada[y, x] == pytest.approx(np.clip(real, 0, 1), abs=1e-5)
        assert esperado == pytest.approx(0.5)


def test_los_limites_de_una_banda_toda_nan_son_neutros():
    from hdfeos_extractor.core.rgb import limites
    assert limites(np.full((3, 3), np.nan, dtype=np.float32)) == (0.0, 1.0)
