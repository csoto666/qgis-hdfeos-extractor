# -*- coding: utf-8 -*-
"""Pruebas de la mascara de bandas malas."""

import numpy as np
import pytest

from conftest import longitudes_con_absorcion
from hdfeos_extractor.core.bandas import (MascaraBandas, formatear_rangos,
                                          parsear_rangos)
from hdfeos_extractor.lector import LIMITE_ESPECTRAL, VENTANAS_ABSORCION


@pytest.fixture
def wl():
    return longitudes_con_absorcion()


def sin_heuristica(wl, **kw):
    opciones = dict(usar_absorcion=False, usar_extremos=False)
    opciones.update(kw)
    return MascaraBandas(wl, **opciones)


# -- criterios por separado ---------------------------------------------------
def test_sin_ningun_criterio_no_descarta_nada(wl):
    m = sin_heuristica(wl)
    assert m.n_malas == 0 and not m.activa
    assert m.buenas.all()


def test_las_ventanas_de_vapor_de_agua(wl):
    """Es el caso que motiva todo: ahi el vapor absorbe casi todo y lo que
    vuelve es ruido dividido por una radiancia casi nula."""
    m = MascaraBandas(wl, usar_absorcion=True, usar_extremos=False)
    for lo, hi in VENTANAS_ABSORCION:
        dentro = (wl >= lo) & (wl <= hi)
        assert dentro.any(), "el eje de prueba tiene que cruzar la ventana"
        assert not m.buenas[dentro].any()
    fuera = wl < VENTANAS_ABSORCION[0][0]
    assert m.buenas[fuera].all()


def test_los_extremos_del_rango(wl):
    m = MascaraBandas(wl, usar_absorcion=False, usar_extremos=True)
    lo, hi = LIMITE_ESPECTRAL
    assert not m.buenas[(wl < lo) | (wl > hi)].any()
    assert m.buenas[(wl >= lo) & (wl <= hi)].all()


def test_la_lista_del_archivo_se_respeta_y_se_puede_apagar(wl):
    bbl = np.ones(wl.size, dtype=bool)
    bbl[[3, 4, 5]] = False
    con = sin_heuristica(wl, bbl=bbl)
    assert con.hay_bbl
    assert list(np.flatnonzero(con.malas)) == [3, 4, 5]
    sin = con.copia(usar_bbl=False)
    assert sin.n_malas == 0
    assert sin.hay_bbl          # sigue estando, solo no se usa


def test_una_bbl_de_otro_largo_se_ignora(wl):
    """No es una bbl parcial: es otra cosa mal etiquetada, y usarla
    descartaria bandas al azar."""
    m = sin_heuristica(wl, bbl=np.zeros(wl.size + 5, dtype=bool))
    assert not m.hay_bbl and m.n_malas == 0


def test_rangos_elegidos_a_mano(wl):
    m = sin_heuristica(wl, rangos=[(900.0, 1100.0)])
    dentro = (wl >= 900.0) & (wl <= 1100.0)
    assert dentro.any()
    assert not m.buenas[dentro].any()
    assert m.buenas[~dentro].all()


def test_un_rango_de_un_solo_valor_descarta_su_banda(wl):
    objetivo = float(wl[10])
    m = sin_heuristica(wl, rangos=[(objetivo, objetivo)])
    assert not m.buenas[10]
    assert m.n_malas == 1


# -- combinacion --------------------------------------------------------------
def test_los_criterios_se_combinan_por_and(wl):
    """Una banda sobrevive solo si ninguno la descarta. En la duda, fuera."""
    bbl = np.ones(wl.size, dtype=bool)
    bbl[0] = False
    m = MascaraBandas(wl, bbl=bbl, usar_absorcion=True, usar_extremos=True,
                      rangos=[(1000.0, 1050.0)])
    assert not m.buenas[0]                              # por la bbl
    for lo, hi in VENTANAS_ABSORCION:                   # por absorcion
        assert not m.buenas[(wl >= lo) & (wl <= hi)].any()
    assert not m.buenas[(wl >= 1000.0) & (wl <= 1050.0)].any()


def test_describir_dice_cuantas_y_por_que(wl):
    m = MascaraBandas(wl, usar_absorcion=True, usar_extremos=True)
    texto = m.describir()
    assert "descartadas" in texto and "vapor de agua" in texto
    assert str(m.n_malas) in texto
    assert "ninguna descartada" in sin_heuristica(wl).describir()


def test_los_tramos_malos_salen_agrupados(wl):
    """Para sombrearlos en el grafico: se ve donde falta el dato, en vez de
    solo ver un hueco."""
    m = MascaraBandas(wl, usar_absorcion=True, usar_extremos=False)
    tramos = m.tramos_malos()
    assert len(tramos) == len(VENTANAS_ABSORCION)
    for (desde, hasta), (lo, hi) in zip(tramos, VENTANAS_ABSORCION):
        assert lo <= desde <= hasta <= hi


# -- aplicar ------------------------------------------------------------------
def test_aplicar_pone_nan_en_las_malas(wl):
    m = MascaraBandas(wl, usar_absorcion=True, usar_extremos=False)
    espectro = np.ones(wl.size, dtype=np.float32)
    salida = m.aplicar(espectro)
    assert np.all(np.isnan(salida[m.malas]))
    assert np.all(salida[m.buenas] == 1.0)


def test_aplicar_sobre_transectos_y_ventanas(wl):
    """El eje espectral es el ultimo en las tres formas que devuelve el
    cubo: (banda,), (posicion, banda) y (y, x, banda)."""
    m = MascaraBandas(wl, usar_absorcion=True, usar_extremos=False)
    for forma in ((wl.size,), (7, wl.size), (3, 4, wl.size)):
        salida = m.aplicar(np.ones(forma, dtype=np.float32))
        assert salida.shape == forma
        assert np.all(np.isnan(salida[..., m.malas]))
        assert np.all(salida[..., m.buenas] == 1.0)


def test_aplicar_sobre_un_eje_que_no_es_el_ultimo(wl):
    m = MascaraBandas(wl, usar_absorcion=True, usar_extremos=False)
    salida = m.aplicar(np.ones((wl.size, 5), dtype=np.float32), eje=0)
    assert np.all(np.isnan(salida[m.malas, :]))


def test_aplicar_sobre_un_largo_equivocado_falla(wl):
    m = MascaraBandas(wl, usar_absorcion=True, usar_extremos=False)
    with pytest.raises(ValueError, match="mascara es de"):
        m.aplicar(np.ones(wl.size + 1, dtype=np.float32))


def test_una_mascara_que_no_descarta_nada_devuelve_los_datos(wl):
    m = sin_heuristica(wl)
    datos = np.arange(wl.size, dtype=np.float32)
    assert np.array_equal(m.aplicar(datos), datos)


# -- banda buena mas cercana --------------------------------------------------
def test_se_salta_las_bandas_malas(wl):
    """Un preset que cae en una ventana de absorcion devolveria ruido puro, y
    la imagen saldria con textura que no existe en el terreno."""
    m = MascaraBandas(wl, usar_absorcion=True, usar_extremos=False)
    centro = sum(VENTANAS_ABSORCION[0]) / 2.0
    i = m.indice_bueno_mas_cercano(centro)
    assert m.buenas[i]
    assert not (VENTANAS_ABSORCION[0][0] <= wl[i] <= VENTANAS_ABSORCION[0][1])


def test_si_todo_es_malo_igual_devuelve_algo(wl):
    """Negarse a componer una imagen es peor que componerla mal."""
    m = sin_heuristica(wl, bbl=np.zeros(wl.size, dtype=bool))
    assert 0 <= m.indice_bueno_mas_cercano(float(wl[3])) < wl.size


# -- rangos escritos a mano ---------------------------------------------------
def test_parsear_las_formas_que_la_gente_escribe():
    assert parsear_rangos("1340-1460") == [(1340.0, 1460.0)]
    assert parsear_rangos("1340-1460, 1790-1960") == [(1340.0, 1460.0),
                                                      (1790.0, 1960.0)]
    assert parsear_rangos("1340:1460") == [(1340.0, 1460.0)]
    assert parsear_rangos("1340 a 1460") == [(1340.0, 1460.0)]
    assert parsear_rangos("900") == [(900.0, 900.0)]
    assert parsear_rangos("1460-1340") == [(1340.0, 1460.0)]   # se ordena


def test_parsear_no_se_atraganta_con_lo_incompleto():
    """El campo se escribe mientras se mira el grafico. Detener al usuario a
    media palabra es peor que no aplicar todavia el rango."""
    assert parsear_rangos("") == []
    assert parsear_rangos("   ") == []
    assert parsear_rangos("hola") == []
    assert parsear_rangos("1340-") == [(1340.0, 1340.0)]
    assert parsear_rangos("1340-1460, basura") == [(1340.0, 1460.0)]


def test_ida_y_vuelta_del_texto():
    for texto in ("1340-1460", "1340-1460, 1790-1960", "900"):
        assert formatear_rangos(parsear_rangos(texto)) == texto
