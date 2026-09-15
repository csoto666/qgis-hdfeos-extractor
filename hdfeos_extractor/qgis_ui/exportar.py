# -*- coding: utf-8 -*-
#
# HDF-EOS Extractor - plugin de QGIS para extraer cubos hiperespectrales
# HDF-EOS5 al formato nativo de ENVI
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
"""Manda al mapa de QGIS lo que se esta viendo, y nada mas.

Cargar el cubo entero como capa para poder trabajar en QGIS es caro y casi
siempre inutil: son cientos de bandas de las que el mapa dibuja tres. Esto
escribe solo esas tres, solo del rectangulo visible y solo con el realce
puesto, lo agrega al proyecto y deja la ventana del cubo libre para seguir
con lo espectral.

Lo dificil de esta operacion no es escribir la imagen: es ponerla en el lugar
correcto. Hay tres casos y se tratan distinto, porque tratarlos igual es
justamente lo que deja la capa corrida:

*Escena georreferenciada con una afin.* Se escribe la geotransformacion tal
cual, con sus terminos de rotacion si los tiene, corrida al recorte y
multiplicada por el submuestreo. No se toca ningun pixel.

*Escena en geometria de sensor.* No hay afin que la describa: la relacion
entre pixel y terreno cambia a lo ancho de la franja. Se escribe con los
puntos de control del producto y se remuestrea de verdad -placa delgada-
hacia una rejilla al norte. Es el unico caso en que los pixeles se mueven, y
se mueven porque no moverlos seria mentir.

*Escena sin georreferencia.* Se escribe la imagen sin sistema de referencia
y se avisa. Una capa sin SRC se ve mal puesta y el usuario lo entiende; una
capa con un SRC inventado se ve bien puesta y esta mal, que es peor.

El resultado es una imagen, no un cubo: sirve para digitalizar encima,
componer un mapa o exportar una figura. Para medir espectros esta la ventana
del cubo, que sigue leyendo el dato original.
"""

import os
import tempfile

import numpy as np

from ..core.rgb import estirar

try:
    from osgeo import gdal, osr
    gdal.UseExceptions()
except Exception:                          # pragma: no cover
    gdal = osr = None

#: Margen, en fraccion del lado de la vista, con que se conservan puntos de
#: control de alrededor del recorte. Con solo los de dentro, la placa delgada
#: extrapola en los bordes y la imagen sale estirada justo donde se mira.
MARGEN_GCP = 0.5

#: Cuanto se le permite a GDAL apartarse de la transformacion exacta, en
#: pixeles. Con esto GDAL usa el transformador aproximado y subdivide la
#: imagen en vez de resolver la placa delgada pixel por pixel, que en una
#: vista de varios megapixeles tarda minutos.
TOLERANCIA_REMUESTREO = 0.125


class ErrorExportar(Exception):
    """No se pudo escribir la imagen o falta GDAL."""


def componer_visible(cube, composer, ventana, max_lado=4000):
    """Devuelve ``(rgba uint8, col0, fila0, paso)`` del rectangulo visible.

    ``col0`` y ``fila0`` son la esquina del recorte en pixeles del cubo
    entero y no los de la ventana pedida: el submuestreo obliga a recortar en
    multiplos del paso, y el redondeo se hace aca para que quien escriba la
    georreferencia use la esquina real y no la solicitada. Es medio pixel de
    diferencia con paso 1 y varios pixeles con paso 8.

    La cuarta banda es la mascara de validez. Sin ella el relleno sale negro
    y tapa lo que haya debajo en el mapa; con ella la escena se recorta sola
    contra su propio borde, que es lo que el usuario espera al superponerla.
    """
    x0, y0, x1, y1 = [int(v) for v in ventana]
    canales, validos, paso = [], None, 1
    for wl in (composer.red, composer.green, composer.blue):
        banda, paso = cube.preview_band(wavelength=wl, max_lado=max_lado)
        banda = banda[y0 // paso:y1 // paso + 1, x0 // paso:x1 // paso + 1]
        finito = np.isfinite(banda)
        validos = finito if validos is None else (validos | finito)
        canales.append(estirar(banda, composer.modo, composer.percentiles))
    rgb = (np.dstack(canales) * 255.0 + 0.5).astype(np.uint8)
    alfa = np.where(validos, np.uint8(255), np.uint8(0))
    rgba = np.dstack([rgb, alfa])
    return rgba, (x0 // paso) * paso, (y0 // paso) * paso, paso


def georreferencia_del_recorte(georref, col0, fila0, paso, ancho, alto):
    """Lleva la georreferencia del cubo entero al recorte que se va a escribir.

    Con puntos de control se quedan ademas solo los que sirven: los de la
    vista mas un margen alrededor. Los de la otra punta de la escena no
    aportan nada al ajuste local y si lo empeoran.
    """
    recorte = georref.recortada(col0, fila0, paso)
    if recorte.es_gcp:
        margen = MARGEN_GCP * max(ancho, alto)
        recorte = recorte.recortar_gcps(ancho, alto, margen=margen)
    return recorte


def wkt_de(georref):
    """WKT del sistema de referencia, resolviendo el EPSG si hace falta.

    La georreferencia del nucleo guarda un codigo EPSG cuando lo dedujo del
    ``map info`` y no construye WKT, porque para eso hace falta OSR y el
    nucleo no depende de GDAL. Aca si hay GDAL, asi que se resuelve.
    """
    if georref is None:
        return None
    if georref.wkt:
        return georref.wkt
    if not georref.epsg or osr is None:
        return None
    try:
        src = osr.SpatialReference()
        if src.ImportFromEPSG(int(georref.epsg)) != 0:
            return None
        return src.ExportToWkt()
    except Exception:                      # pragma: no cover - OSR raro
        return None


def escribir_geotiff(ruta, rgba, georref):
    """Escribe la vista como GeoTIFF, remuestreando solo si hace falta."""
    if gdal is None:
        raise ErrorExportar(
            "GDAL no esta disponible: no se puede escribir la imagen")
    wkt = wkt_de(georref)
    if georref is not None and georref.necesita_remuestreo:
        if not wkt:
            raise ErrorExportar(
                "La escena viene en geometria de sensor y no declara sistema "
                "de referencia: no se puede reproyectar")
        return _escribir_remuestreado(ruta, rgba, georref, wkt)
    gt = georref.gt if georref is not None else None
    return _escribir_directo(ruta, rgba, gt, wkt)


def _crear(driver, ruta, rgba, opciones=None):
    """Crea un dataset de cuatro bandas y le vuelca el RGBA."""
    alto, ancho, bandas = rgba.shape
    ds = gdal.GetDriverByName(driver).Create(
        ruta, ancho, alto, bandas, gdal.GDT_Byte, options=opciones or [])
    if ds is None:
        raise ErrorExportar("GDAL no pudo crear %s" % ruta)
    interpretacion = [gdal.GCI_RedBand, gdal.GCI_GreenBand,
                      gdal.GCI_BlueBand, gdal.GCI_AlphaBand]
    for i in range(bandas):
        banda = ds.GetRasterBand(i + 1)
        banda.WriteRaster(0, 0, ancho, alto,
                          np.ascontiguousarray(rgba[:, :, i]).tobytes())
        banda.SetColorInterpretation(interpretacion[i])
    return ds


#: LZW con predictor: una composicion RGB comprime mucho y el archivo es
#: temporal. Tiled para que QGIS lea por bloques al hacer zoom. ALPHA=YES
#: para que la cuarta banda se declare como transparencia y no como un canal
#: cualquiera que QGIS tendria que adivinar.
OPCIONES_TIF = ["COMPRESS=LZW", "PREDICTOR=2", "TILED=YES",
                "PHOTOMETRIC=RGB", "ALPHA=YES"]


def _escribir_directo(ruta, rgba, gt, wkt):
    """Escribe sin tocar ningun pixel: la afin va tal cual al archivo."""
    ds = _crear("GTiff", ruta, rgba, OPCIONES_TIF)
    try:
        if gt is not None:
            ds.SetGeoTransform(tuple(float(v) for v in gt))
        if wkt:
            ds.SetProjection(wkt)
    finally:
        ds = None                          # cierra y vuelca al disco
    return ruta


def _escribir_remuestreado(ruta, rgba, georref, wkt):
    """Reproyecta desde los puntos de control hacia una rejilla al norte.

    El intermedio va en el driver MEM y no a un archivo temporal: es del
    mismo tamano que la vista, y escribirlo al disco para volver a leerlo
    solo sirve para dejar basura si algo falla en medio.

    Se remuestrea por vecino mas cercano a proposito. La imagen ya esta
    realzada a 8 bits y no se va a medir sobre ella; interpolar solo
    inventaria colores intermedios en los bordes del relleno.
    """
    origen = _crear("MEM", "", rgba)
    salida = None
    try:
        origen.SetGCPs(
            [gdal.GCP(float(x), float(y), 0.0, float(c), float(f))
             for c, f, x, y in georref.gcps], wkt)
        salida = gdal.Warp(
            ruta, origen, format="GTiff", tps=True, resampleAlg="near",
            dstSRS=wkt, srcAlpha=True, dstAlpha=True,
            errorThreshold=TOLERANCIA_REMUESTREO,
            creationOptions=OPCIONES_TIF)
        if salida is None:
            raise ErrorExportar(
                "GDAL no pudo reproyectar la vista a %s" % ruta)
    finally:
        salida = None                      # cierra y vuelca al disco
        origen = None
    return ruta


def ruta_temporal(nombre_base, r, g, b):
    """Un nombre que dice de que escena y de que bandas salio.

    Importa mas de lo que parece: despues de media hora de trabajo el mapa
    tiene cuatro de estas capas y "salida_1.tif" no distingue ninguna.
    """
    limpio = "".join(c if c.isalnum() or c in "-_" else "_"
                     for c in os.path.splitext(nombre_base)[0])[:40]
    nombre = "%s_rgb_%d-%d-%d.tif" % (limpio, round(r), round(g), round(b))
    return os.path.join(tempfile.gettempdir(), nombre)


def enviar_vista(cube, composer, ventana, georref=None, ruta=None,
                 max_lado=4000):
    """Escribe la vista actual como GeoTIFF. Devuelve ``(ruta, nombre_capa)``.

    ``georref`` es una ``Georreferencia`` del nucleo. Si no se pasa, se le
    pregunta al cubo, que es lo correcto casi siempre: la georreferencia del
    archivo es mas fiel que cualquier cosa deducida desde la capa de QGIS.
    """
    if georref is None:
        georref = cube.georreferencia
    rgba, col0, fila0, paso = componer_visible(
        cube, composer, ventana, max_lado)
    alto, ancho = rgba.shape[:2]
    recorte = georreferencia_del_recorte(
        georref, col0, fila0, paso, ancho, alto)
    longitudes = composer.wavelengths_of(cube)
    if ruta is None:
        ruta = ruta_temporal(cube.name, *longitudes)
    escribir_geotiff(ruta, rgba, recorte)
    nombre = "%s  RGB %d/%d/%d" % (
        os.path.splitext(cube.name)[0],
        round(longitudes[0]), round(longitudes[1]), round(longitudes[2]))
    return ruta, nombre
