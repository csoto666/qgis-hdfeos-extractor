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
"""Pruebas de la georreferencia: de donde sale y cuando no hay que inventarla.

Estas pruebas son casi todas de numeros y no de interfaz, y es a proposito.
El error de proyeccion no se ve: la capa se dibuja igual de bien en el lugar
equivocado. La unica forma de atraparlo es comparar coordenadas contra
valores calculados a mano.
"""

import numpy as np
import pytest

from hdfeos_extractor.core.georef import (
    EPSG_WGS84, Georreferencia, afin_por_minimos_cuadrados,
    geotransformacion_de_referencia, parsear_map_info)


# -- map info de ENVI -------------------------------------------------------
def test_map_info_sin_rotacion():
    """El pixel de referencia de ENVI va en base 1 y apunta a la esquina."""
    gt, epsg, _nota = parsear_map_info(
        "UTM, 1.000, 1.000, 400000.000, 4500000.000, 30.0, 30.0, "
        "18, North, WGS-84, units=Meters")
    assert gt == pytest.approx((400000.0, 30.0, 0.0, 4500000.0, 0.0, -30.0))
    assert epsg == 32618


def test_map_info_hemisferio_sur():
    _gt, epsg, _nota = parsear_map_info(
        "UTM, 1.0, 1.0, 500000.0, 6000000.0, 20.0, 20.0, "
        "19, South, WGS-84, units=Meters")
    assert epsg == 32719


def test_map_info_geograficas():
    gt, epsg, _nota = parsear_map_info(
        "Geographic Lat/Lon, 1.0, 1.0, -75.0, 5.0, 0.0001, 0.0001, "
        "WGS-84, units=Degrees")
    assert epsg == EPSG_WGS84
    assert gt[0] == pytest.approx(-75.0)
    assert gt[5] == pytest.approx(-0.0001)


def test_map_info_pixel_de_referencia_desplazado():
    """Un pixel de referencia que no es el (1,1) corre el origen.

    Es el caso de un recorte: ENVI conserva el pixel de referencia original
    y declara cual es. Tomar la coordenada como si fuera la del pixel (0,0)
    deja la escena corrida tantos pixeles como diga el campo.
    """
    gt, _epsg, _nota = parsear_map_info(
        "UTM, 11.0, 21.0, 400000.0, 4500000.0, 10.0, 10.0, "
        "18, North, WGS-84, units=Meters")
    # El pixel 11 en base 1 es el 10 en base 0: el origen esta 100 m al oeste.
    assert gt[0] == pytest.approx(400000.0 - 100.0)
    assert gt[3] == pytest.approx(4500000.0 + 200.0)


def test_map_info_con_rotacion():
    """La rotacion llena los terminos cruzados y no se puede ignorar."""
    gt, _epsg, _nota = parsear_map_info(
        "UTM, 1.0, 1.0, 0.0, 0.0, 10.0, 10.0, 18, North, WGS-84, "
        "units=Meters, rotation=30.0")
    assert gt[2] != 0.0 and gt[4] != 0.0
    # El tamano de pixel sobrevive a la rotacion: la norma de cada columna
    # de la matriz sigue siendo 10 m.
    assert np.hypot(gt[1], gt[4]) == pytest.approx(10.0)
    assert np.hypot(gt[2], gt[5]) == pytest.approx(10.0)


def test_rotacion_cero_es_la_de_siempre():
    con = geotransformacion_de_referencia(1, 1, 100, 200, 5, 7, rotacion=0.0)
    assert con == pytest.approx((100.0, 5.0, 0.0, 200.0, 0.0, -7.0))


def test_map_info_incompleto_no_inventa():
    assert parsear_map_info("UTM, 1.0, 1.0") is None
    assert parsear_map_info("") is None
    assert parsear_map_info(None) is None


def test_map_info_con_tamano_de_pixel_cero():
    """Un tamano de pixel cero no es georreferencia: es una cabecera rota."""
    assert parsear_map_info(
        "UTM, 1.0, 1.0, 400000.0, 4500000.0, 0.0, 0.0, "
        "18, North, WGS-84, units=Meters") is None


def test_datum_desconocido_deja_el_src_sin_resolver():
    """Un datum que no es WGS-84 no se traduce a EPSG a la ligera.

    Adivinar el codigo corre la escena cientos de metros y el error es
    invisible: la capa se dibuja perfecta, solo que al lado.
    """
    _gt, epsg, nota = parsear_map_info(
        "Geographic Lat/Lon, 1.0, 1.0, -75.0, 5.0, 0.001, 0.001, "
        "Bogota, units=Degrees")
    assert epsg is None
    assert "datum" in nota.lower()


# -- Georreferencia desde cabecera ------------------------------------------
def test_de_envi_prefiere_el_wkt_textual():
    """El WKT de la cabecera es exacto; el nombre de proyeccion hay que
    reconstruirlo."""
    g = Georreferencia.de_envi({
        "map info": ("UTM, 1.0, 1.0, 400000.0, 4500000.0, 30.0, 30.0, "
                     "18, North, WGS-84, units=Meters"),
        "coordinate system string": 'PROJCS["WGS 84 / UTM zone 18N"]',
    })
    assert g.es_afin
    assert g.wkt.startswith('PROJCS["WGS 84')
    assert g.nombre_src == "WGS 84 / UTM zone 18N"


def test_de_envi_sin_map_info_no_tiene_mapa():
    g = Georreferencia.de_envi({"samples": "10"})
    assert not g.tiene_mapa
    assert not g.tiene_src


# -- rejilla de lat/lon -----------------------------------------------------
def rejilla(alto=8, ancho=10, rot=0.0):
    """Lat/lon de una escena inclinada, como la de un sensor de barrido."""
    f, c = np.meshgrid(np.arange(alto), np.arange(ancho), indexing="ij")
    lon = -75.0 + 0.01 * c * np.cos(rot) - 0.01 * f * np.sin(rot)
    lat = 5.0 - 0.01 * f * np.cos(rot) - 0.01 * c * np.sin(rot)
    return lon, lat


def test_de_rejilla_da_puntos_de_control():
    g = Georreferencia.de_rejilla(*rejilla(), por_lado=5)
    assert g.es_gcp and not g.es_afin
    assert g.necesita_remuestreo
    assert g.epsg == EPSG_WGS84
    assert len(g.gcps) == 25


def test_de_rejilla_descarta_el_relleno():
    """-9999 no es una coordenada: esta fuera del planeta y hay que tirarlo."""
    lon, lat = rejilla()
    lon[0, :] = -9999.0
    lat[0, :] = -9999.0
    g = Georreferencia.de_rejilla(lon, lat, por_lado=4)
    assert g.es_gcp
    assert all(abs(x) <= 180.0 and abs(y) <= 90.0 for _c, _f, x, y in g.gcps)


def test_de_rejilla_sin_datos_validos_no_miente():
    lon = np.full((6, 6), np.nan)
    g = Georreferencia.de_rejilla(lon, lon.copy())
    assert not g.tiene_mapa
    assert "validos" in g.nota


def test_ajuste_afin_recupera_una_rejilla_afin():
    """Si la rejilla es afin, el ajuste la recupera exactamente."""
    lon, lat = rejilla(rot=0.3)
    g = Georreferencia.de_rejilla(lon, lat, por_lado=6)
    t = g.transformacion
    x, y = t.to_map(3, 2)          # centro del pixel (col 3, fila 2)
    assert x == pytest.approx(lon[2, 3], abs=1e-9)
    assert y == pytest.approx(lat[2, 3], abs=1e-9)


def test_ajuste_afin_necesita_tres_puntos():
    assert afin_por_minimos_cuadrados([(0, 0, 1, 1)]) is None
    # Tres puntos alineados no definen una afin: el ajuste lo detecta.
    colineales = [(0, 0, 0, 0), (1, 1, 1, 1), (2, 2, 2, 2)]
    assert afin_por_minimos_cuadrados(colineales) is None


# -- recorte ----------------------------------------------------------------
def test_recortada_corre_el_origen_y_escala_el_pixel():
    """Las dos mitades del error clasico, en una sola prueba.

    Olvidar el origen deja la capa corrida; olvidar el paso la deja del
    tamano equivocado. Las dos se ven recien al superponerla con otra capa.
    """
    g = Georreferencia(gt=(400000.0, 10.0, 0.0, 4500000.0, 0.0, -10.0),
                       epsg=32618, origen="archivo")
    r = g.recortada(col0=50, fila0=30, paso=2)
    assert r.gt[0] == pytest.approx(400000.0 + 500.0)
    assert r.gt[3] == pytest.approx(4500000.0 - 300.0)
    assert r.gt[1] == pytest.approx(20.0)
    assert r.gt[5] == pytest.approx(-20.0)
    assert r.epsg == 32618


def test_recortada_conserva_la_rotacion():
    g = Georreferencia(gt=(0.0, 8.66, 5.0, 0.0, 5.0, -8.66), origen="archivo")
    r = g.recortada(10, 10, 1)
    # El origen se corre por las dos vias, no solo por la diagonal.
    assert r.gt[0] == pytest.approx(86.6 + 50.0)
    assert r.gt[3] == pytest.approx(50.0 - 86.6)


def test_recortada_mueve_los_puntos_de_control():
    g = Georreferencia(gcps=[(10.5, 20.5, -75.0, 5.0),
                             (30.5, 40.5, -74.0, 4.0),
                             (50.5, 60.5, -73.0, 3.0)], epsg=4326)
    r = g.recortada(10, 20, 2)
    assert r.gcps[0][0] == pytest.approx(0.25)
    assert r.gcps[1][0] == pytest.approx(10.25)
    assert r.gcps[0][2] == pytest.approx(-75.0)   # el terreno no se mueve


def test_recortar_gcps_deja_los_de_dentro():
    puntos = [(float(c), float(f), c * 0.1, f * 0.1)
              for f in range(0, 100, 10) for c in range(0, 100, 10)]
    g = Georreferencia(gcps=puntos, epsg=4326)
    r = g.recortar_gcps(ancho=30, alto=30)
    assert len(r.gcps) < len(puntos)
    assert all(p[0] <= 30 and p[1] <= 30 for p in r.gcps)


def test_recortar_gcps_no_se_queda_sin_puntos():
    """Con menos de tres puntos no hay ajuste posible: mejor extrapolar."""
    g = Georreferencia(gcps=[(100.0, 100.0, 1.0, 1.0),
                             (200.0, 200.0, 2.0, 2.0),
                             (300.0, 300.0, 3.0, 3.0)], epsg=4326)
    r = g.recortar_gcps(ancho=5, alto=5)
    assert len(r.gcps) == 3


# -- honestidad -------------------------------------------------------------
def test_sin_georreferencia_la_transformacion_es_el_pixel():
    g = Georreferencia.ninguna()
    assert not g.tiene_mapa and not g.tiene_src
    assert g.transformacion.gt == (0.0, 1.0, 0.0, 0.0, 0.0, -1.0)


def test_describir_dice_de_donde_salio():
    g = Georreferencia(gt=(0, 1, 0, 0, 0, -1), epsg=32618, origen="archivo")
    assert "archivo" in g.describir() and "EPSG:32618" in g.describir()
    assert "sin georreferencia" in Georreferencia.ninguna().describir()


def test_una_afin_no_necesita_remuestreo():
    g = Georreferencia(gt=(0, 1, 0, 0, 0, -1), epsg=4326, origen="archivo")
    assert not g.necesita_remuestreo


# -- integracion con las fuentes --------------------------------------------
def test_envi_con_map_info_llega_hasta_el_cubo(tmp_path, datos, wl):
    """La georreferencia del archivo tiene que llegar viva al cubo.

    Este es el camino que estaba roto: el archivo traia ``map info`` y nadie
    lo leia, asi que la unica fuente de coordenadas era la extension de la
    capa de QGIS.
    """
    from conftest import escribir_envi
    from hdfeos_extractor.core.cube import HyperspectralCube

    ruta = escribir_envi(tmp_path, datos, "bil", wl, extras={
        "map info": ("{UTM, 1.000, 1.000, 400000.000, 4500000.000, "
                     "30.0, 30.0, 18, North, WGS-84, units=Meters}"),
    })
    cubo = HyperspectralCube.load(ruta)
    try:
        g = cubo.georreferencia
        assert g.es_afin and g.epsg == 32618
        x, y = g.transformacion.to_map(0, 0)
        assert (x, y) == pytest.approx((400015.0, 4499985.0))
    finally:
        cubo.close()


def test_envi_sin_map_info_no_finge(tmp_path, datos, wl):
    from conftest import escribir_envi
    from hdfeos_extractor.core.cube import HyperspectralCube

    cubo = HyperspectralCube.load(escribir_envi(tmp_path, datos, "bil", wl))
    try:
        assert not cubo.georreferencia.tiene_mapa
    finally:
        cubo.close()


def test_hdf5_saca_los_puntos_de_control_del_producto(tmp_path):
    """El HDF-EOS5 no trae afin: trae dos capas con la coordenada de
    cada pixel."""
    h5py = pytest.importorskip("h5py")
    assert h5py is not None
    from conftest import (escribir_hdfeos, longitudes_h5, reflectancia_patron)
    from hdfeos_extractor.core.cube import HyperspectralCube

    ruta = escribir_hdfeos(tmp_path, reflectancia_patron(), longitudes_h5())
    cubo = HyperspectralCube.load(ruta)
    try:
        g = cubo.georreferencia
        assert g.es_gcp and g.necesita_remuestreo
        assert g.epsg == EPSG_WGS84
        # La rejilla del fixture es afin, asi que el ajuste debe clavarla.
        x, y = g.transformacion.to_map(0, 0)
        assert (x, y) == pytest.approx((-70.0, -33.0), abs=1e-6)
    finally:
        cubo.close()


def test_el_cubo_cerrado_no_inventa_coordenadas(tmp_path, datos, wl):
    from conftest import escribir_envi
    from hdfeos_extractor.core.cube import HyperspectralCube

    cubo = HyperspectralCube.load(escribir_envi(tmp_path, datos, "bil", wl))
    cubo.close()
    assert not cubo.georreferencia.tiene_mapa
