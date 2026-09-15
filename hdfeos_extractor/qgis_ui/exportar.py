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
puesto -un GeoTIFF de 8 bits, tres bandas-, lo agrega al proyecto y deja la
ventana del cubo libre para seguir con lo espectral.

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


class ErrorExportar(Exception):
    """No se pudo escribir la imagen o falta GDAL."""


def componer_visible(cube, composer, ventana, max_lado=4000):
    """Devuelve (rgb uint8, paso) del rectangulo visible.

    Se compone aca y no con ``create_composite`` para saber el paso de
    submuestreo: sin el no se puede escribir una geotransformacion correcta,
    y la capa aparece en el mapa con el tamano de pixel equivocado.
    """
    x0, y0, x1, y1 = [int(v) for v in ventana]
    canales, paso = [], 1
    for wl in (composer.red, composer.green, composer.blue):
        banda, paso = cube.preview_band(wavelength=wl, max_lado=max_lado)
        banda = banda[y0 // paso:y1 // paso + 1, x0 // paso:x1 // paso + 1]
        canales.append(estirar(banda, composer.modo, composer.percentiles))
    rgb = np.dstack(canales)
    return (rgb * 255.0 + 0.5).astype(np.uint8), paso


def geotransformacion(geo, ventana, paso):
    """La geotransformacion del recorte, a partir de la del cubo entero.

    El origen se corre al pixel (x0, y0) y el tamano de pixel se multiplica
    por el paso de submuestreo. Olvidar cualquiera de las dos cosas pone la
    capa en el lugar equivocado o con la escala equivocada, y es el tipo de
    error que se ve recien cuando se compara con otra capa.
    """
    gt = geo.gt
    x0, y0 = int(ventana[0]), int(ventana[1])
    return (gt[0] + x0 * gt[1] + y0 * gt[2],
            gt[1] * paso, gt[2] * paso,
            gt[3] + x0 * gt[4] + y0 * gt[5],
            gt[4] * paso, gt[5] * paso)


def escribir_geotiff(ruta, rgb, gt, wkt=None):
    """Escribe el RGB como GeoTIFF de 3 bandas y 8 bits."""
    if gdal is None:
        raise ErrorExportar(
            "GDAL no esta disponible: no se puede escribir la imagen")
    alto, ancho = rgb.shape[:2]
    driver = gdal.GetDriverByName("GTiff")
    # LZW con predictor: una composicion RGB comprime mucho y el archivo es
    # temporal. Tiled para que QGIS lea por bloques al hacer zoom.
    ds = driver.Create(ruta, ancho, alto, 3, gdal.GDT_Byte,
                       options=["COMPRESS=LZW", "PREDICTOR=2", "TILED=YES"])
    if ds is None:
        raise ErrorExportar("GDAL no pudo crear %s" % ruta)
    try:
        ds.SetGeoTransform(gt)
        if wkt:
            ds.SetProjection(wkt)
        for i in range(3):
            banda = ds.GetRasterBand(i + 1)
            banda.WriteRaster(0, 0, ancho, alto,
                              np.ascontiguousarray(rgb[:, :, i]).tobytes())
            banda.SetColorInterpretation(
                [gdal.GCI_RedBand, gdal.GCI_GreenBand,
                 gdal.GCI_BlueBand][i])
    finally:
        ds = None                          # cierra y vuelca al disco
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


def enviar_vista(cube, composer, ventana, geo, wkt=None, ruta=None,
                 max_lado=4000):
    """Escribe la vista actual como GeoTIFF. Devuelve (ruta, nombre_capa)."""
    rgb, paso = componer_visible(cube, composer, ventana, max_lado)
    longitudes = composer.wavelengths_of(cube)
    if ruta is None:
        ruta = ruta_temporal(cube.name, *longitudes)
    escribir_geotiff(ruta, rgb, geotransformacion(geo, ventana, paso), wkt)
    nombre = "%s  RGB %d/%d/%d" % (
        os.path.splitext(cube.name)[0],
        round(longitudes[0]), round(longitudes[1]), round(longitudes[2]))
    return ruta, nombre
