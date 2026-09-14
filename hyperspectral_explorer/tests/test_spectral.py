# -*- coding: utf-8 -*-
"""Pruebas de firmas espectrales, estadisticas y angulo espectral."""

import numpy as np
import pytest

from conftest import BANDAS, cubo_patron, longitudes_patron
from hyperspectral_explorer.core.cube import HyperspectralCube
from hyperspectral_explorer.core.spectral import (Signature, SpectralProfile,
                                                  signature_from_pixel,
                                                  signature_from_pixels,
                                                  signature_from_roi,
                                                  spectral_angle, statistics)


@pytest.fixture
def cubo():
    return HyperspectralCube.from_array(cubo_patron(), longitudes_patron(),
                                        name="prueba")


def firma(valores, nombre="f", wl=None):
    valores = np.asarray(valores, dtype=np.float32)
    if wl is None:
        wl = np.arange(valores.size, dtype=np.float64)
    return Signature(nombre, wl, valores)


# -- Signature ----------------------------------------------------------------
def test_una_firma_guarda_su_procedencia(cubo):
    f = signature_from_pixel(cubo, 3, 2, notes="vegetacion")
    assert f.pixels == [(3, 2)]
    assert f.source == "prueba"
    assert f.notes == "vegetacion"
    assert f.created                       # fecha y hora automatica
    assert not f.is_area and f.count == 1


def test_no_se_puede_construir_una_firma_descuadrada():
    with pytest.raises(ValueError, match="longitudes de onda y"):
        Signature("mala", [400.0, 500.0], [0.1, 0.2, 0.3])


def test_ida_y_vuelta_por_diccionario(cubo):
    f = signature_from_pixel(cubo, 1, 1, name="agua", notes="lago")
    g = Signature.from_dict(f.to_dict())
    assert g.name == "agua" and g.notes == "lago" and g.pixels == f.pixels
    assert np.array_equal(g.values, f.values)
    assert np.array_equal(g.wavelengths, f.wavelengths)


def test_los_nan_sobreviven_a_la_serializacion():
    """JSON no tiene NaN. Se escriben como null y tienen que volver como NaN,
    no como cero: un cero es una medicion y un NaN es la ausencia de una."""
    f = firma([0.1, np.nan, 0.3])
    d = f.to_dict()
    assert d["values"][1] is None
    assert np.isnan(Signature.from_dict(d).values[1])


# -- extraccion ---------------------------------------------------------------
def test_firma_de_pixel_es_el_espectro_del_cubo(cubo):
    f = signature_from_pixel(cubo, 4, 6)
    assert np.array_equal(f.values, cubo.get_spectrum(4, 6))
    assert np.array_equal(f.wavelengths, longitudes_patron())


def test_firma_de_area_promedia_y_guarda_la_desviacion(cubo):
    f = signature_from_roi(cubo, 0, 0, 1, 1)
    assert f.is_area and f.count == 4
    assert f.std is not None and f.std.size == BANDAS
    esperado = cubo.get_roi(0, 0, 1, 1).reshape(4, BANDAS).mean(axis=0)
    assert np.allclose(f.values, esperado)


def test_firma_de_area_ignora_el_relleno_por_banda():
    """Una sola banda invalida en un solo pixel no debe anular esa banda para
    todo el poligono: por eso nanmean y no mean."""
    datos = np.ones((2, 2, 3), dtype=np.float32)
    datos[0, 0, 1] = np.nan
    cubo = HyperspectralCube.from_array(datos, [400.0, 500.0, 600.0])
    f = signature_from_roi(cubo, 0, 0, 1, 1)
    assert np.allclose(f.values, [1.0, 1.0, 1.0])


def test_un_area_toda_relleno_falla_con_un_mensaje_util():
    datos = np.full((2, 2, 3), np.nan, dtype=np.float32)
    cubo = HyperspectralCube.from_array(datos, [400.0, 500.0, 600.0])
    with pytest.raises(ValueError, match="toda relleno"):
        signature_from_roi(cubo, 0, 0, 1, 1)


def test_firma_de_pixeles_sueltos(cubo):
    f = signature_from_pixels(cubo, [(0, 0), (4, 6)])
    assert f.count == 2 and f.pixels == [(0, 0), (4, 6)]
    esperado = np.vstack([cubo.get_spectrum(0, 0),
                          cubo.get_spectrum(4, 6)]).mean(axis=0)
    assert np.allclose(f.values, esperado)


# -- estadisticas -------------------------------------------------------------
def test_estadisticas_por_banda():
    e = statistics([[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]])
    assert e["n"] == 2
    assert np.allclose(e["mean"], [2.0, 3.0, 4.0])
    assert np.allclose(e["min"], [1.0, 2.0, 3.0])
    assert np.allclose(e["max"], [3.0, 4.0, 5.0])
    assert np.allclose(e["std"], [1.0, 1.0, 1.0])


def test_estadisticas_de_un_solo_espectro():
    e = statistics([0.1, 0.2, 0.3])
    assert e["n"] == 1 and np.allclose(e["std"], 0.0)


# -- angulo espectral ---------------------------------------------------------
def test_dos_firmas_identicas_dan_angulo_cero():
    """Sin el clip del coseno, el redondeo saca el valor de [-1, 1] y arccos
    devuelve NaN justo en el caso mas facil."""
    a = firma([0.1, 0.4, 0.3, 0.9])
    assert spectral_angle(a, a) == pytest.approx(0.0, abs=1e-9)


def test_el_angulo_ignora_la_magnitud():
    """Es toda la gracia del SAM: la misma cubierta en sombra y al sol da dos
    curvas a alturas distintas y con la misma forma."""
    a = firma([0.1, 0.4, 0.3, 0.9])
    b = firma(a.values * 0.35)
    assert spectral_angle(a, b) == pytest.approx(0.0, abs=1e-4)


def test_firmas_ortogonales_dan_noventa_grados():
    a = firma([1.0, 0.0])
    b = firma([0.0, 1.0])
    assert spectral_angle(a, b) == pytest.approx(90.0)
    assert spectral_angle(a, b, en_grados=False) == pytest.approx(np.pi / 2)


def test_las_bandas_invalidas_se_excluyen_de_la_comparacion():
    a = firma([1.0, np.nan, 1.0])
    b = firma([1.0, 5.0, 1.0])
    assert spectral_angle(a, b) == pytest.approx(0.0, abs=1e-5)


def test_no_se_comparan_firmas_de_distinto_largo():
    with pytest.raises(ValueError, match="remuestrearlas"):
        spectral_angle(firma([1.0, 2.0]), firma([1.0, 2.0, 3.0]))


def test_no_se_comparan_firmas_sin_bandas_validas_en_comun():
    a = firma([1.0, np.nan])
    b = firma([np.nan, 1.0])
    with pytest.raises(ValueError, match="comparten bandas validas"):
        spectral_angle(a, b)


def test_una_firma_de_ceros_no_tiene_angulo():
    with pytest.raises(ValueError, match="toda ceros"):
        spectral_angle(firma([0.0, 0.0]), firma([1.0, 2.0]))


# -- SpectralProfile ----------------------------------------------------------
def test_el_perfil_extrae_sin_agregar(cubo):
    p = SpectralProfile(cubo)
    f = p.get_signature(2, 3)
    assert len(p) == 0
    p.add_signature(f)
    assert len(p) == 1


def test_un_nombre_repetido_se_numera_no_se_pisa(cubo):
    """Quien hace clic en dos pixeles de vegetacion quiere las dos curvas."""
    p = SpectralProfile(cubo)
    p.add_signature(Signature("Vegetacion", cubo.wavelengths,
                              cubo.get_spectrum(0, 0)))
    p.add_signature(Signature("Vegetacion", cubo.wavelengths,
                              cubo.get_spectrum(1, 1)))
    p.add_signature(Signature("Vegetacion", cubo.wavelengths,
                              cubo.get_spectrum(2, 2)))
    assert [f.name for f in p] == ["Vegetacion", "Vegetacion (2)",
                                   "Vegetacion (3)"]


def test_quitar_por_nombre_y_por_referencia(cubo):
    p = SpectralProfile(cubo)
    a = p.add_signature(Signature("a", cubo.wavelengths,
                                  cubo.get_spectrum(0, 0)))
    p.add_signature(Signature("b", cubo.wavelengths, cubo.get_spectrum(1, 0)))
    assert p.remove_signature(a) is True
    assert p.remove_signature("b") is True
    assert p.remove_signature("fantasma") is False
    assert len(p) == 0


def test_solo_cuentan_las_visibles(cubo):
    p = SpectralProfile(cubo)
    p.add_signature(Signature("a", cubo.wavelengths,
                              np.ones(BANDAS, dtype=np.float32)))
    oculta = p.add_signature(Signature("b", cubo.wavelengths,
                                       np.full(BANDAS, 3.0, np.float32)))
    oculta.visible = False
    assert len(p.visible) == 1
    assert np.allclose(p.statistics()["mean"], 1.0)
    assert np.allclose(p.statistics(solo_visibles=False)["mean"], 2.0)


def test_estadisticas_de_un_perfil_vacio(cubo):
    assert SpectralProfile(cubo).statistics() is None


def test_no_se_promedian_firmas_de_ejes_distintos(cubo):
    """Dar un numero aca seria peor que no darlo: promediar bandas de
    sensores distintos produce una curva que no describe nada."""
    p = SpectralProfile(cubo)
    p.add_signature(firma([0.1, 0.2, 0.3], "corta"))
    p.add_signature(firma([0.1, 0.2, 0.3, 0.4], "larga"))
    assert p.statistics() is None


def test_un_perfil_sin_cubo_no_puede_extraer():
    with pytest.raises(ValueError, match="no tiene cubo"):
        SpectralProfile().get_signature(0, 0)
