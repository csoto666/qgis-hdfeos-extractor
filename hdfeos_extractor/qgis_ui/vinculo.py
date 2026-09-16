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
"""Vincula la vista del cubo con el lienzo de QGIS: los dos miran lo mismo.

Es el "link displays" de toda la vida, y resuelve un problema concreto: en el
cubo se ve el detalle espectral pero no el contexto, y en el mapa esta el
contexto -la ortofoto de alta resolucion, el catastro, lo que sea- pero no el
espectro. Vinculados, acercarse en uno lleva al otro al mismo sitio, y lo que
se esta midiendo deja de ser un parche de colores para ser un sitio
reconocible.

La parte delicada no es la geometria, que se resuelve con la
geotransformacion. Es que cada lado avisa de sus cambios y el aviso mueve al
otro, que avisa a su vez: un bucle que no se detiene solo. Aqui se corta por
dos vias a la vez -ver ``_sincronizar``-, porque cada una se escapa en un
caso distinto y las dos juntas no dejan hueco.
"""

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsCsException, QgsProject, QgsRectangle)

from ..vista.qt import QtCore

#: Cuanto puede moverse la vista del otro lado sin que se considere un cambio
#: de verdad, en fraccion de su propio tamano. Sin esta tolerancia, las
#: diferencias de redondeo entre pixeles y coordenadas bastan para que los
#: dos lados se empujen indefinidamente, cada vez un poco menos, pero sin
#: llegar a pararse nunca.
TOLERANCIA = 0.01


class VinculoVistas(QtCore.QObject):
    """Mantiene el cubo y el lienzo mirando la misma zona del terreno.

    No guarda estado propio mas alla de si esta encendido: la verdad esta
    siempre en la ventana del cubo y en la extension del lienzo, y se leen
    cada vez. Un vinculo que recordara "donde estabamos" se desincroniza en
    cuanto alguien mueve algo por otro camino.
    """

    #: Cambio de estado que el panel quiere contar: (activo, explicacion).
    estadoCambiado = QtCore.pyqtSignal(bool, str)

    def __init__(self, cubo, canvas, controller, parent=None):
        super(VinculoVistas, self).__init__(parent)
        self.cubo = cubo
        self.canvas = canvas
        self.controller = controller
        self.activo = False
        self._sincronizando = False

    # -- encendido ----------------------------------------------------------
    def utilizable(self):
        """Sin georreferencia no hay vinculo posible, y hay que decirlo.

        Devuelve (se_puede, motivo). El motivo se muestra tal cual: "no
        funciona" sin decir por que es lo que convierte una limitacion en un
        fallo aparente.
        """
        cubo = self.controller.cube
        if cubo is None or cubo.cerrado:
            return False, "Primero abra una escena"
        georref = self.controller.georref
        if not georref.tiene_mapa:
            return False, ("La escena no dice donde esta, asi que no hay con "
                           "que vincularla al mapa")
        if self._crs_escena() is None:
            return False, ("La escena no declara un sistema de referencia "
                           "que QGIS reconozca")
        if georref.necesita_remuestreo:
            return True, ("Vinculado. La escena esta en geometria de sensor: "
                          "la correspondencia es aproximada, buena para "
                          "navegar y no para medir sobre el mapa")
        return True, "Vinculado: el cubo y el mapa se siguen"

    def activar(self, encender):
        """Enciende o apaga el vinculo. Devuelve el motivo para mostrar."""
        se_puede, motivo = self.utilizable()
        if encender and not se_puede:
            self._desconectar()
            self.activo = False
            self.estadoCambiado.emit(False, motivo)
            return motivo
        if encender:
            self._conectar()
            self.activo = True
            # Se sincroniza al encender, y mandando el cubo: el usuario
            # acaba de encuadrar algo ahi y espera que el mapa vaya a
            # buscarlo, no que su encuadre se pierda.
            self.del_cubo_al_mapa()
        else:
            self._desconectar()
            self.activo = False
            motivo = "Vinculo apagado"
        self.estadoCambiado.emit(self.activo, motivo)
        return motivo

    def _conectar(self):
        if self.activo:
            return
        self.cubo.vistaCambiada.connect(self._vista_del_cubo_cambio)
        self.canvas.extentsChanged.connect(self._extension_del_mapa_cambio)

    def _desconectar(self):
        if not self.activo:
            return
        for senal, receptor in (
                (self.cubo.vistaCambiada, self._vista_del_cubo_cambio),
                (self.canvas.extentsChanged, self._extension_del_mapa_cambio)):
            try:
                senal.disconnect(receptor)
            except (TypeError, RuntimeError):
                # Desconectar algo que ya no estaba conectado. No es un
                # problema: el objetivo es que quede desconectado.
                pass

    # -- sistema de referencia ----------------------------------------------
    def _crs_escena(self):
        """El SRC en que estan las coordenadas de la escena, o None."""
        georref = self.controller.georref
        if georref.wkt:
            crs = QgsCoordinateReferenceSystem.fromWkt(georref.wkt)
            if crs.isValid():
                return crs
        if georref.epsg:
            crs = QgsCoordinateReferenceSystem.fromEpsgId(int(georref.epsg))
            if crs.isValid():
                return crs
        capa = self.controller.layer
        if capa is not None and capa.crs().isValid():
            return capa.crs()
        return None

    def _transformar(self, bbox, origen, destino):
        """Caja de un SRC a otro. None si la reproyeccion no es posible."""
        if origen is None or destino is None:
            return None
        if not (origen.isValid() and destino.isValid()) or origen == destino:
            return bbox
        try:
            t = QgsCoordinateTransform(origen, destino, QgsProject.instance())
            r = t.transformBoundingBox(
                QgsRectangle(bbox[0], bbox[1], bbox[2], bbox[3]))
        except QgsCsException:
            # La zona no tiene correspondencia en el otro sistema. Se deja de
            # seguir por esta vez en vez de mover la vista a cualquier parte.
            return None
        return (r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum())

    # -- las dos direcciones ------------------------------------------------
    def del_cubo_al_mapa(self):
        """Lleva el lienzo a la zona que el cubo tiene a la vista."""
        if self._sincronizando or self.controller.cube is None:
            return
        bbox = self.controller.geo.bbox_de_ventana(self.cubo.ventana())
        destino = self.canvas.mapSettings().destinationCrs()
        bbox = self._transformar(bbox, self._crs_escena(), destino)
        if bbox is None:
            return
        actual = self.canvas.extent()
        nueva = QgsRectangle(bbox[0], bbox[1], bbox[2], bbox[3])
        if _parecidas(actual, nueva):
            return
        with self._sincronizar():
            self.canvas.setExtent(nueva)
            self.canvas.refresh()

    def del_mapa_al_cubo(self):
        """Lleva la vista del cubo a la zona que el lienzo tiene delante."""
        cubo = self.controller.cube
        if self._sincronizando or cubo is None or cubo.cerrado:
            return
        e = self.canvas.extent()
        bbox = self._transformar(
            (e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()),
            self.canvas.mapSettings().destinationCrs(), self._crs_escena())
        if bbox is None:
            return
        ventana = self.controller.geo.ventana_de_bbox(
            bbox, cubo.samples, cubo.lines)
        if ventana is None:
            # El mapa se fue a donde la escena no llega. Se deja el cubo como
            # esta: saltar a la vista completa seria perder el encuadre por
            # un desplazamiento que a lo mejor es de paso.
            return
        if _ventanas_parecidas(ventana, self.cubo.ventana()):
            return
        with self._sincronizar():
            self.cubo.set_vista(ventana)

    def _vista_del_cubo_cambio(self, _vista):
        if self.activo:
            self.del_cubo_al_mapa()

    def _extension_del_mapa_cambio(self):
        if self.activo:
            self.del_mapa_al_cubo()

    # -- corte del bucle ----------------------------------------------------
    def _sincronizar(self):
        """Marca que el movimiento lo estamos provocando nosotros.

        Es la primera de las dos vias que cortan el bucle. La segunda son las
        comparaciones de ``_parecidas``, y hacen falta las dos: la bandera no
        alcanza porque QGIS emite ``extentsChanged`` cuando le viene bien
        -a veces despues de que la bandera se haya bajado- y entonces el eco
        vuelve como si fuera un movimiento del usuario. Las comparaciones no
        alcanzan solas porque sin la bandera cada lado recalcularia el otro
        aunque el cambio fuera despreciable, y el redondeo entre pixeles y
        metros haria que nunca coincidieran del todo.
        """
        return _Bandera(self)


class _Bandera(object):
    """Sube ``_sincronizando`` mientras dure el bloque, y lo baja pase lo que
    pase: una excepcion a media sincronizacion dejaria el vinculo mudo."""

    def __init__(self, vinculo):
        self.vinculo = vinculo

    def __enter__(self):
        self.vinculo._sincronizando = True
        return self

    def __exit__(self, *_excepcion):
        self.vinculo._sincronizando = False
        return False


def _parecidas(a, b, tolerancia=TOLERANCIA):
    """True si dos extensiones son la misma vista a efectos practicos."""
    if a is None or b is None:
        return False
    if a.width() <= 0 or a.height() <= 0:
        return False
    margen_x = max(a.width(), b.width()) * tolerancia
    margen_y = max(a.height(), b.height()) * tolerancia
    return (abs(a.xMinimum() - b.xMinimum()) <= margen_x
            and abs(a.xMaximum() - b.xMaximum()) <= margen_x
            and abs(a.yMinimum() - b.yMinimum()) <= margen_y
            and abs(a.yMaximum() - b.yMaximum()) <= margen_y)


def _ventanas_parecidas(a, b, tolerancia=TOLERANCIA):
    """Lo mismo para ventanas de pixeles, con un minimo de un pixel.

    La tolerancia relativa sola no sirve aqui: en una vista de veinte
    pixeles, el uno por ciento es menos de un pixel y cualquier redondeo
    parece un cambio de verdad.
    """
    ancho = max(a[2] - a[0], b[2] - b[0]) + 1
    alto = max(a[3] - a[1], b[3] - b[1]) + 1
    margen_x = max(1.0, ancho * tolerancia)
    margen_y = max(1.0, alto * tolerancia)
    return (abs(a[0] - b[0]) <= margen_x and abs(a[2] - b[2]) <= margen_x
            and abs(a[1] - b[1]) <= margen_y and abs(a[3] - b[3]) <= margen_y)
