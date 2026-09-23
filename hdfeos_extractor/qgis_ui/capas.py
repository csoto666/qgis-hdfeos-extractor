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
"""Las huellas de las firmas, como capas vectoriales de QGIS.

Dos capas y no una: los puntos por un lado y las areas por otro. QGIS admite
capas de geometria mixta desde hace poco, pero casi ninguna herramienta que
las consuma lo hace, y separarlas ademas deja simbolizar cada cosa como
corresponde.

Las capas son de memoria: aparecen en el proyecto al instante y no dejan
archivos sueltos por el disco. Quien quiera un archivo tiene la exportacion
a GeoJSON al lado.

Lo que decide que geometria le toca a cada firma esta en ``core.huella``,
que se prueba sin QGIS. Aqui queda la traduccion a objetos de QGIS.
"""

from qgis.core import (QgsCategorizedSymbolRenderer,
                       QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsCsException, QgsFeature,
                       QgsField, QgsGeometry, QgsPointXY, QgsProject,
                       QgsRendererCategory, QgsSymbol, QgsVectorLayer)

from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtGui import QColor

from ..compat import enum

from ..core.geojson import colecciones_de_firmas, escribir
from ..core.huella import (CAMPOS, Huella, atributos_de_firma,
                           huella_de_firma)
from .exportar import wkt_de

#: Errores que puede lanzar QGIS al armar una capa o un simbolo. Se enumeran
#: en vez de atrapar Exception a secas: un fallo que no este aqui es un error
#: del programa y tiene que verse.
ERRORES_DE_QGIS = (RuntimeError, ValueError, TypeError, AttributeError)

#: Tipo de campo de Qt por tipo de Python. Se pasa por QMetaType y no por
#: QVariant porque Qt6 quito QVariant.Type entero: en PyQt6 no existe ni
#: QVariant.String ni QVariant.Type, y una capa cuyos campos no se pueden
#: declarar es una capa que no se crea.
TIPOS_QT = {
    str: enum(QMetaType, "Type", "QString"),
    int: enum(QMetaType, "Type", "Int"),
    float: enum(QMetaType, "Type", "Double"),
}

#: El unico sistema que GeoJSON admite.
EPSG_WGS84 = 4326


class ErrorCapas(Exception):
    """No se pudo armar la capa de huellas."""


def src_de(georref):
    """El SRC de la escena, o None si no se sabe cual es.

    Se le pregunta a QGIS por el codigo EPSG antes de construir un WKT con
    GDAL: QGIS resuelve codigos sin ayuda de nadie, y ese camino sigue
    funcionando en instalaciones donde el enlace de Python con GDAL esta
    roto -que las hay, y es justo donde uno no quiere perder la capa-.
    """
    if georref is None:
        return None
    wkt = wkt_de(georref)
    if wkt:
        src = QgsCoordinateReferenceSystem()
        try:
            src.createFromWkt(wkt)
        except ERRORES_DE_QGIS:
            src = None
        if src is not None and src.isValid():
            return src
    codigo = getattr(georref, "epsg", None)
    if codigo:
        try:
            src = QgsCoordinateReferenceSystem.fromEpsgId(int(codigo))
        except ERRORES_DE_QGIS:
            return None
        if src.isValid():
            return src
    return None


def aviso_de_huellas(georref, n_puntos, n_areas, sin_sitio):
    """Lo que hay que decirle al usuario sobre las capas que acaba de ver."""
    partes = ["%d punto(s) y %d area(s) en el mapa" % (n_puntos, n_areas)]
    if sin_sitio:
        partes.append(
            "%d firma(s) se quedaron fuera porque no traen pixeles: no se "
            "sabe de donde salieron y no se les inventa un sitio."
            % sin_sitio)
    if georref is None or not georref.tiene_mapa:
        partes.append(
            "La escena no dice donde esta, asi que las huellas salen en "
            "coordenadas de pixel y no se alinearan con ninguna otra capa.")
    elif not georref.tiene_src:
        partes.append(
            "La escena trae coordenadas pero no dice en que sistema: hay "
            "que asignarle el SRC a las capas a mano.")
    return " ".join(partes)


def capas_de_firmas(firmas, geo, georref, prefijo="Firmas"):
    """Arma las dos capas de memoria. Devuelve ``(puntos, areas, aviso)``.

    Una capa sale None cuando no hay ninguna firma de esa clase: agregar al
    proyecto una capa vacia llamada "Firmas - areas" hace pensar que algo
    fallo.
    """
    puntos, areas, sin_sitio = repartir_huellas(list(firmas), geo)
    src = src_de(georref)
    capa_puntos = _capa("MultiPoint", "%s - puntos" % prefijo, puntos, src)
    capa_areas = _capa("Polygon", "%s - areas" % prefijo, areas, src)
    return (capa_puntos, capa_areas,
            aviso_de_huellas(georref, len(puntos), len(areas), sin_sitio))


def _capa(geometria, nombre, pares, src):
    if not pares:
        return None
    capa = QgsVectorLayer(geometria, nombre, "memory")
    if not capa.isValid():
        raise ErrorCapas("QGIS no pudo crear la capa %s" % nombre)
    if src is not None:
        capa.setCrs(src)
    proveedor = capa.dataProvider()
    proveedor.addAttributes([QgsField(campo, TIPOS_QT[tipo])
                             for campo, tipo in CAMPOS.items()])
    capa.updateFields()
    proveedor.addFeatures([_rasgo(firma, huella) for firma, huella in pares])
    capa.updateExtents()
    _pintar_por_color(capa, [f for f, _ in pares])
    return capa


def _rasgo(firma, huella):
    rasgo = QgsFeature()
    rasgo.setGeometry(_geometria(huella))
    rasgo.setAttributes(list(atributos_de_firma(firma).values()))
    return rasgo


def _geometria(huella):
    if huella.es_area:
        return QgsGeometry.fromPolygonXY(
            [[QgsPointXY(x, y) for x, y in huella.anillo]])
    return QgsGeometry.fromMultiPointXY(
        [QgsPointXY(x, y) for x, y in huella.puntos])


def _pintar_por_color(capa, firmas):
    """Cada huella con el color de su curva en el grafico.

    Es lo que relaciona el mapa con el grafico espectral sin leer ninguna
    leyenda: la mancha verde del mapa es la curva verde del perfil. Si algo
    falla al armar el simbolo se deja el de siempre; una capa con el color
    por defecto sigue sirviendo, y quedarse sin capa por un simbolo no.
    """
    colores = []
    for firma in firmas:
        color = getattr(firma, "color", None)
        if color and color not in colores:
            colores.append(color)
    if not colores:
        return
    try:
        categorias = []
        for color in colores:
            simbolo = QgsSymbol.defaultSymbol(capa.geometryType())
            simbolo.setColor(QColor(color))
            categorias.append(QgsRendererCategory(color, simbolo, color))
        capa.setRenderer(QgsCategorizedSymbolRenderer("color", categorias))
    except ERRORES_DE_QGIS:
        pass


def rellenar(capa, pares):
    """Vacia la capa y le vuelve a poner las huellas.

    Vaciar y rellenar en vez de quitar la capa y crear otra: una capa nueva
    tiene otro identificador, se va al final del arbol de capas y pierde el
    sitio y la visibilidad que el usuario le habia dado. Poner al dia no
    deberia costarle eso.
    """
    proveedor = capa.dataProvider()
    try:
        proveedor.truncate()
    except ERRORES_DE_QGIS:
        return False
    proveedor.addFeatures([_rasgo(firma, huella) for firma, huella in pares])
    capa.updateExtents()
    _pintar_por_color(capa, [f for f, _ in pares])
    return True


def repartir_huellas(firmas, geo):
    """Separa las firmas en las que van a puntos y las que van a areas.

    Devuelve ``(puntos, areas, sin_sitio)``, cada lista con pares
    ``(firma, huella)``.
    """
    puntos, areas, sin_sitio = [], [], 0
    for firma in firmas:
        huella = huella_de_firma(firma, geo)
        if huella is None:
            sin_sitio += 1
        elif huella.es_area:
            areas.append((firma, huella))
        else:
            puntos.append((firma, huella))
    return puntos, areas, sin_sitio


def agregar_al_proyecto(capas):
    """Mete en el proyecto las capas que existan y devuelve cuantas."""
    vivas = [c for c in capas if c is not None]
    for capa in vivas:
        QgsProject.instance().addMapLayer(capa)
    return len(vivas)


def exportar_geojson(firmas, geo, georref, ruta_base):
    """Escribe las huellas en dos GeoJSON y devuelve lo que escribio.

    Se REPROYECTA a longitud/latitud, no se avisa de que no lo esta. El RFC
    7946 fija WGS84 y quito el miembro que antes permitia declarar otro
    sistema, asi que un GeoJSON con metros UTM dentro es un archivo que cada
    programa interpreta a su manera -y casi siempre mal, como si fueran
    grados: la escena aparece en el golfo de Guinea-. Escribirlo bien es
    trabajo de quien lo escribe.

    Sin SRC en la escena no hay desde donde reproyectar. Ahi se escribe tal
    cual y se dice, que es lo unico honesto que queda.
    """
    firmas = list(firmas)
    huellas = [huella_de_firma(f, geo) for f in firmas]
    huellas, aviso = _a_longitud_latitud(huellas, georref)
    puntos, areas = colecciones_de_firmas(firmas, huellas)
    escritos = []
    for sufijo, coleccion in (("puntos", puntos), ("areas", areas)):
        if not coleccion["features"]:
            continue
        ruta = "%s_%s.geojson" % (ruta_base, sufijo)
        escribir(ruta, coleccion)
        escritos.append((ruta, len(coleccion["features"])))
    return escritos, aviso


def _a_longitud_latitud(huellas, georref):
    """Pasa las huellas a WGS84, que es lo que GeoJSON significa."""
    origen = src_de(georref)
    if origen is None:
        return huellas, ("La escena no declara sistema de referencia, asi "
                         "que el GeoJSON lleva las coordenadas tal cual. "
                         "Quien lo abra no puede saber a que se refieren.")
    destino = QgsCoordinateReferenceSystem.fromEpsgId(EPSG_WGS84)
    try:
        cambio = QgsCoordinateTransform(origen, destino,
                                        QgsProject.instance())
        pasadas = [_reproyectar(h, cambio) for h in huellas]
    except (QgsCsException,) + ERRORES_DE_QGIS:
        return huellas, ("No se pudo reproyectar a longitud/latitud: el "
                         "GeoJSON sale en el sistema de la escena, que no "
                         "es lo que el formato asume.")
    return pasadas, ""


def _mover(punto, cambio):
    salida = cambio.transform(QgsPointXY(punto[0], punto[1]))
    return (salida.x(), salida.y())


def _reproyectar(huella, cambio):
    if huella is None:
        return None

    def mover(punto):
        return _mover(punto, cambio)

    if huella.es_area:
        return Huella(huella.tipo, anillo=[mover(p) for p in huella.anillo])
    return Huella(huella.tipo, puntos=[mover(p) for p in huella.puntos])


__all__ = ["ErrorCapas", "agregar_al_proyecto", "aviso_de_huellas",
           "capas_de_firmas", "exportar_geojson", "src_de"]
