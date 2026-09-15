# -*- coding: utf-8 -*-
"""Pruebas del envio de la vista al mapa de QGIS.

La mitad de estas pruebas son sobre coordenadas y no sobre pixeles, y es a
proposito: una vista mal proyectada se dibuja igual de bien, solo que en el
lugar equivocado, y eso no lo atrapa mirar la imagen.
"""

import os

import numpy as np
import pytest

from conftest import cubo_patron, longitudes_patron
from hdfeos_extractor.core.cube import HyperspectralCube
from hdfeos_extractor.core.georef import Georreferencia
from hdfeos_extractor.core.rgb import RGBComposer
from hdfeos_extractor.qgis_ui.exportar import (componer_visible,
                                               georreferencia_del_recorte,
                                               ruta_temporal, wkt_de)

GT = (500000.0, 30.0, 0.0, 4600000.0, 0.0, -30.0)


def utm18():
    return Georreferencia(gt=GT, epsg=32618, origen="archivo")


@pytest.fixture
def cubo():
    return HyperspectralCube.from_array(cubo_patron(40, 60, 9),
                                        longitudes_patron(9), name="escena.h5")


@pytest.fixture
def composer():
    return RGBComposer(600.0, 550.0, 500.0)


# -- composicion ------------------------------------------------------------
def test_se_compone_solo_lo_visible(cubo, composer):
    """El punto de todo esto: al mapa va la vista, no el cubo."""
    rgba, col0, fila0, paso = componer_visible(cubo, composer, (10, 5, 29, 20))
    assert rgba.dtype == np.uint8
    assert rgba.shape == (16, 20, 4)
    assert (col0, fila0, paso) == (10, 5, 1)


def test_la_cuarta_banda_es_la_mascara_de_validez(composer):
    """El relleno tiene que salir transparente y no negro.

    Negro tapa lo que haya debajo en el mapa, y en una escena de sensor el
    relleno es el triangulo de cada esquina: media capa de negro sobre el
    mosaico de fondo.
    """
    datos = cubo_patron(10, 10, 9)
    datos[0, 0, :] = np.nan
    c = HyperspectralCube.from_array(datos, longitudes_patron(9))
    rgba, _c0, _f0, _p = componer_visible(c, composer, (0, 0, 9, 9))
    assert rgba[0, 0, 3] == 0
    assert rgba[5, 5, 3] == 255


def test_el_origen_del_recorte_es_el_real_y_no_el_pedido(composer):
    """Con submuestreo el recorte cae en multiplos del paso.

    Si se escribe la geotransformacion con la esquina *pedida* y se recorta
    por la esquina *posible*, la capa sale corrida hasta un paso entero. Con
    paso 1 no se nota; con paso 8 son ocho pixeles.
    """
    c = HyperspectralCube.from_array(cubo_patron(400, 400, 9),
                                     longitudes_patron(9))
    rgba, col0, fila0, paso = componer_visible(c, composer, (101, 53, 300, 300),
                                               max_lado=100)
    assert paso == 4
    assert (col0, fila0) == (100, 52)          # 101//4*4, 53//4*4
    assert rgba.shape[1] == 300 // 4 - 101 // 4 + 1


# -- georreferencia del recorte ---------------------------------------------
def test_el_recorte_se_corre_al_origen_de_la_ventana():
    """Olvidarlo pone la capa en el lugar equivocado, y eso se ve recien
    cuando se compara con otra capa."""
    g = georreferencia_del_recorte(utm18(), 10, 5, 1, ancho=20, alto=16)
    assert g.gt[0] == 500000.0 + 10 * 30.0
    assert g.gt[3] == 4600000.0 - 5 * 30.0
    assert g.gt[1] == 30.0 and g.gt[5] == -30.0
    assert g.epsg == 32618


def test_el_submuestreo_agranda_el_pixel():
    """Con el paso olvidado la capa sale con la escala equivocada."""
    g = georreferencia_del_recorte(utm18(), 0, 0, 4, ancho=25, alto=25)
    assert g.gt[1] == 120.0 and g.gt[5] == -120.0
    assert g.gt[0] == 500000.0                   # el origen no cambia


def test_la_rotacion_llega_entera_al_archivo():
    """El caso que el metodo viejo perdia: una escena sin ortorectificar.

    Deducir la geotransformacion de la extension de la capa borra los
    terminos cruzados, y con ellos la inclinacion de la escena. La capa sale
    del tamano de la caja envolvente en vez del de la escena.
    """
    rotada = Georreferencia(gt=(0.0, 26.0, 15.0, 0.0, 15.0, -26.0),
                            epsg=32618, origen="archivo")
    g = georreferencia_del_recorte(rotada, 10, 0, 1, ancho=10, alto=10)
    assert g.gt[2] == 15.0 and g.gt[4] == 15.0
    assert g.gt[0] == 260.0 and g.gt[3] == 150.0


def test_una_escena_sin_georreferencia_no_inventa_una():
    g = georreferencia_del_recorte(Georreferencia.ninguna(), 3, 7, 1, 10, 10)
    assert g.gt is None and not g.tiene_mapa


def test_los_puntos_de_control_se_recortan_a_la_vista():
    """Los de la otra punta de la escena no ajustan nada local y deforman."""
    puntos = [(float(c), float(f), -70.0 + c * 0.001, -33.0 - f * 0.001)
              for f in range(0, 400, 20) for c in range(0, 400, 20)]
    georref = Georreferencia(gcps=puntos, epsg=4326, origen="lat/lon")
    g = georreferencia_del_recorte(georref, 100, 100, 1, ancho=40, alto=40)
    assert g.es_gcp and len(g.gcps) < len(puntos)
    # Siguen valiendo las mismas coordenadas de terreno, en pixeles del
    # recorte: el punto (100, 100) del cubo es el (0, 0) de la vista.
    en_cero = [p for p in g.gcps if p[0] == 0.0 and p[1] == 0.0]
    assert en_cero and en_cero[0][2] == pytest.approx(-70.0 + 100 * 0.001)


# -- sistema de referencia ---------------------------------------------------
def test_el_wkt_del_archivo_gana_sobre_el_epsg():
    g = Georreferencia(gt=GT, wkt='PROJCS["lo que diga el archivo"]',
                       epsg=4326)
    assert wkt_de(g) == 'PROJCS["lo que diga el archivo"]'


def test_sin_src_no_se_inventa_ninguno():
    assert wkt_de(Georreferencia(gt=GT)) is None
    assert wkt_de(None) is None


def test_el_epsg_se_resuelve_a_wkt_cuando_hay_osr():
    pytest.importorskip("osgeo.osr", reason="hace falta GDAL")
    wkt = wkt_de(Georreferencia(gt=GT, epsg=32618))
    assert wkt and "32618" in wkt or "UTM zone 18N" in wkt


# -- nombre de la capa -------------------------------------------------------
def test_el_nombre_dice_de_que_escena_y_de_que_bandas():
    """Despues de media hora de trabajo el mapa tiene cuatro de estas capas y
    "salida_1.tif" no distingue ninguna."""
    ruta = ruta_temporal("20250223_165546_basic_sr.h5", 842.3, 665.1, 559.8)
    assert ruta.endswith("_rgb_842-665-560.tif")
    assert "20250223_165546_basic_sr" in ruta


def test_el_nombre_sobrevive_a_caracteres_raros():
    ruta = ruta_temporal("escena con espacios/y barras.dat", 800, 600, 400)
    assert "/y barras" not in ruta.split("_rgb_")[0].split("/")[-1]


# -- escritura, solo si hay GDAL ---------------------------------------------
def test_se_escribe_un_geotiff_legible(tmp_path, cubo, composer):
    gdal = pytest.importorskip("osgeo.gdal", reason="hace falta GDAL")
    from hdfeos_extractor.qgis_ui.exportar import enviar_vista

    ruta = str(tmp_path / "vista.tif")
    salida, nombre = enviar_vista(cubo, composer, (10, 5, 29, 20), utm18(),
                                  ruta=ruta)
    assert os.path.isfile(salida) and "RGB" in nombre
    ds = gdal.Open(salida)
    assert ds.RasterCount == 4                   # RGB + transparencia
    assert (ds.RasterXSize, ds.RasterYSize) == (20, 16)
    assert ds.GetGeoTransform()[0] == 500000.0 + 10 * 30.0
    assert "32618" in ds.GetProjection() or "18N" in ds.GetProjection()


def test_la_escena_de_sensor_se_reproyecta(tmp_path, cubo, composer):
    """El caso que motivo todo esto: sin remuestrear, la capa cae en (0,0).

    Una escena en geometria de sensor no tiene geotransformacion. Escribirla
    como si la tuviera la deja en coordenadas de pixel, es decir en el golfo
    de Guinea. Con los puntos de control tiene que salir donde dicen la
    latitud y la longitud del producto.
    """
    gdal = pytest.importorskip("osgeo.gdal", reason="hace falta GDAL")
    from hdfeos_extractor.qgis_ui.exportar import enviar_vista

    alto, ancho = cubo.lines, cubo.samples
    f, c = np.meshgrid(np.arange(alto), np.arange(ancho), indexing="ij")
    # Inclinada a proposito: es lo que ninguna afin al norte describe.
    lon = -70.0 + 0.001 * c - 0.0003 * f
    lat = -33.0 - 0.001 * f - 0.0003 * c
    georref = Georreferencia.de_rejilla(lon, lat, por_lado=8)

    ruta = str(tmp_path / "sensor.tif")
    salida, _nombre = enviar_vista(cubo, composer, (0, 0, ancho - 1, alto - 1),
                                   georref, ruta=ruta)
    ds = gdal.Open(salida)
    gt = ds.GetGeoTransform()
    assert gt[0] == pytest.approx(-70.0, abs=0.02)
    assert gt[3] == pytest.approx(-33.0, abs=0.02)
    assert gt[1] > 0 and gt[5] < 0               # ya esta al norte
    assert "4326" in ds.GetProjection() or "WGS 84" in ds.GetProjection()
    assert ds.RasterCount >= 4


def test_sin_src_una_escena_de_sensor_se_niega(tmp_path, cubo, composer):
    """No hay a donde reproyectar si no se sabe en que sistema estan los
    puntos de control. Decirlo es mejor que escribir cualquier cosa."""
    pytest.importorskip("osgeo.gdal", reason="hace falta GDAL")
    from hdfeos_extractor.qgis_ui.exportar import ErrorExportar, enviar_vista

    georref = Georreferencia(gcps=[(0.0, 0.0, 1.0, 1.0), (5.0, 0.0, 2.0, 1.0),
                                   (0.0, 5.0, 1.0, 2.0)])
    with pytest.raises(ErrorExportar):
        enviar_vista(cubo, composer, (0, 0, 9, 9), georref,
                     ruta=str(tmp_path / "x.tif"))


def test_un_pixel_marcado_cae_en_su_coordenada(tmp_path):
    """La prueba de punta a punta del problema de proyeccion.

    Se pinta un cuadrado brillante en un pixel conocido de una escena
    inclinada, se exporta, y se busca ese cuadrado en el GeoTIFF resultante.
    Tiene que aparecer en la coordenada que dicen las capas de latitud y
    longitud del producto. Todas las formas de equivocarse -ignorar los
    puntos de control, deducir una afin de la caja envolvente, olvidar el
    origen del recorte- ponen el cuadrado en otra parte, y ninguna se ve
    mirando la imagen.
    """
    gdal = pytest.importorskip("osgeo.gdal", reason="hace falta GDAL")
    from hdfeos_extractor.qgis_ui.exportar import enviar_vista

    alto, ancho, bandas = 120, 160, 9
    datos = np.full((alto, ancho, bandas), 0.05, dtype=np.float32)
    marca_f, marca_c = 30, 100
    datos[marca_f:marca_f + 4, marca_c:marca_c + 4, :] = 0.9
    cubo = HyperspectralCube.from_array(
        datos, np.linspace(450.0, 900.0, bandas), name="sensor.h5")

    # Franja inclinada 20 grados: ninguna afin al norte la describe.
    a = np.radians(20.0)
    f, c = np.meshgrid(np.arange(alto), np.arange(ancho), indexing="ij")
    tam = 0.0005                                 # ~55 m
    lon = -70.0 + tam * (c * np.cos(a) - f * np.sin(a))
    lat = -33.0 - tam * (f * np.cos(a) + c * np.sin(a))
    georref = Georreferencia.de_rejilla(lon, lat, por_lado=15)

    ruta = str(tmp_path / "sensor.tif")
    # Minimo-maximo y no percentil: el cuadrado es el 0.08% de la escena, y
    # el realce por percentiles -que es lo correcto para mirar- se lo come.
    enviar_vista(cubo, RGBComposer(660.0, 550.0, 470.0, modo="minmax"),
                 (0, 0, ancho - 1, alto - 1), georref, ruta=ruta)

    ds = gdal.Open(ruta)
    gt = ds.GetGeoTransform()
    rojo = ds.GetRasterBand(1).ReadAsArray()
    fs, cs = np.where(rojo > 200)
    assert fs.size, "el cuadrado brillante no aparece en la capa exportada"
    x = gt[0] + (cs.mean() + 0.5) * gt[1] + (fs.mean() + 0.5) * gt[2]
    y = gt[3] + (cs.mean() + 0.5) * gt[4] + (fs.mean() + 0.5) * gt[5]

    trozo = (slice(marca_f, marca_f + 4), slice(marca_c, marca_c + 4))
    assert x == pytest.approx(lon[trozo].mean(), abs=tam)
    assert y == pytest.approx(lat[trozo].mean(), abs=tam)
    # La franja inclinada no llena su caja envolvente: las esquinas quedan
    # transparentes en vez de negras.
    alfa = ds.GetRasterBand(4).ReadAsArray()
    assert 0.2 < (alfa == 0).mean() < 0.6


def test_un_ortho_se_envia_sin_remuestrear_y_con_zoom(tmp_path):
    """El producto ortorectificado: ya esta puesto, solo hay que respetarlo.

    Este es el caso que no se cubria. Un grid de HDF-EOS trae su afin en el
    StructMetadata y NO trae capas de latitud y longitud, asi que buscandolas
    no se encontraba nada y la escena -perfectamente ubicada en el archivo-
    aterrizaba en coordenadas de pixel.

    Se comprueba entera y con zoom, porque son dos errores distintos: uno
    pone la capa en otro sitio y el otro la pone corrida.
    """
    gdal = pytest.importorskip("osgeo.gdal", reason="hace falta GDAL")
    from hdfeos_extractor.core.georef import Georreferencia
    from hdfeos_extractor.qgis_ui.exportar import enviar_vista
    from conftest import estructura_grid

    alto, ancho, bandas = 120, 160, 12
    ulx, uly, pixel = 400000.0, 4500000.0, 30.0
    datos = np.full((alto, ancho, bandas), 0.05, dtype=np.float32)
    marca_f, marca_c = 40, 100
    datos[marca_f:marca_f + 4, marca_c:marca_c + 4, :] = 0.9
    cubo = HyperspectralCube.from_array(
        datos, np.linspace(450.0, 1300.0, bandas), name="ortho.h5")
    georref = Georreferencia.de_estructura(
        estructura_grid(ancho, alto, ulx, uly, pixel, zona=18),
        lineas=alto, muestras=ancho)
    assert georref.es_afin and not georref.necesita_remuestreo

    comp = RGBComposer(660.0, 550.0, 470.0, modo="minmax")
    esperado_x = ulx + (marca_c + 2) * pixel
    esperado_y = uly - (marca_f + 2) * pixel

    for etiqueta, ventana in (("entera", (0, 0, ancho - 1, alto - 1)),
                              ("zoom", (90, 30, 139, 79))):
        ruta = str(tmp_path / ("%s.tif" % etiqueta))
        enviar_vista(cubo, comp, ventana, georref, ruta=ruta)
        ds = gdal.Open(ruta)
        gt = ds.GetGeoTransform()
        assert gt[0] == pytest.approx(ulx + ventana[0] * pixel)
        assert gt[3] == pytest.approx(uly - ventana[1] * pixel)
        assert gt[1] == pytest.approx(pixel)
        rojo = ds.GetRasterBand(1).ReadAsArray()
        fs, cs = np.where(rojo > 200)
        assert fs.size, "el cuadrado no aparece en la vista %s" % etiqueta
        x = gt[0] + (cs.mean() + 0.5) * gt[1]
        y = gt[3] + (fs.mean() + 0.5) * gt[5]
        assert x == pytest.approx(esperado_x, abs=pixel)
        assert y == pytest.approx(esperado_y, abs=pixel)
