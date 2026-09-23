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
"""La ventana de la nube n-dimensional: el lienzo y sus controles.

Crea los widgets y los deja expuestos; no conoce ni el cubo ni QGIS. Quien
la usa -el panel del explorador- es quien arma la nube y se la entrega, igual
que con el bloque del cubo. Asi este archivo se prueba sin abrir QGIS.
"""

import numpy as np

from .ndim_view import MODO_GIRAR, MODO_LAZO, VistaND
from .qt import HORIZONTAL, QtWidgets, Qt, enum, politica, pyqtSignal

#: Cuantas bandas se eligen solas al abrir. Con 426 marcadas la nube gira
#: igual, pero los radios tapan la pantalla y cada cuadro cuesta el triple;
#: con una docena repartida por el espectro se ve la estructura y se lee.
BANDAS_POR_DEFECTO = 12


class PanelND(QtWidgets.QWidget):
    """El lienzo n-D con su columna de controles."""

    #: Cambio que bandas son las dimensiones: hay que rehacer la nube.
    bandasCambiadas = pyqtSignal(list)
    #: Se pidio guardar como firma lo que hay seleccionado.
    firmaPedida = pyqtSignal(object)
    #: Cambio la visibilidad de una clase.
    clasesCambiadas = pyqtSignal()

    def __init__(self, parent=None):
        super(PanelND, self).__init__(parent)
        self.setWindowTitle("Nube n-dimensional")
        self._bloqueado = False
        self._longitudes = np.zeros(0)
        self._unidad = "nm"
        self._seleccion = None

        caja = QtWidgets.QHBoxLayout(self)
        caja.setContentsMargins(6, 6, 6, 6)
        caja.setSpacing(6)
        self.vista = VistaND()
        caja.addWidget(self.vista, 1)
        caja.addWidget(self._columna())
        self._conectar()

    # -- construccion -------------------------------------------------------
    def _columna(self):
        marco = QtWidgets.QWidget()
        marco.setFixedWidth(232)
        columna = QtWidgets.QVBoxLayout(marco)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.setSpacing(6)
        columna.addWidget(self._grupo_giro())
        columna.addWidget(self._grupo_bandas(), 1)
        columna.addWidget(self._grupo_clases(), 1)
        columna.addWidget(self._grupo_seleccion())
        return marco

    def _grupo_giro(self):
        grupo = QtWidgets.QGroupBox("Giro")
        rejilla = QtWidgets.QVBoxLayout(grupo)
        rejilla.setSpacing(3)

        fila = QtWidgets.QHBoxLayout()
        self.boton_girar = QtWidgets.QToolButton()
        self.boton_girar.setText("Girar")
        self.boton_girar.setCheckable(True)
        self.boton_girar.setToolTip(
            "Proyecta la nube sobre un plano que rota.\n"
            "El ojo separa grupos en movimiento mucho mejor que quietos.")
        self.boton_girar.setSizePolicy(politica("Expanding"),
                                       politica("Preferred"))
        self.boton_centrar = QtWidgets.QToolButton()
        self.boton_centrar.setText("Centrar")
        self.boton_centrar.setToolTip("Deshace el giro a mano y el zoom")
        fila.addWidget(self.boton_girar, 1)
        fila.addWidget(self.boton_centrar)
        rejilla.addLayout(fila)

        self.boton_lazo = QtWidgets.QToolButton()
        self.boton_lazo.setText("Lazo")
        self.boton_lazo.setCheckable(True)
        self.boton_lazo.setToolTip(
            "Rodea un grupo con el raton para seleccionar sus pixeles.\n"
            "Con el lazo apagado, arrastrar gira la nube a mano.")
        self.boton_lazo.setSizePolicy(politica("Expanding"),
                                      politica("Preferred"))
        rejilla.addWidget(self.boton_lazo)

        rejilla.addWidget(QtWidgets.QLabel("Velocidad:"))
        self.velocidad = QtWidgets.QSlider(HORIZONTAL)
        self.velocidad.setMinimum(1)
        self.velocidad.setMaximum(100)
        self.velocidad.setValue(25)
        rejilla.addWidget(self.velocidad)

        rejilla.addWidget(QtWidgets.QLabel("Tamano del punto:"))
        self.tamano = QtWidgets.QSlider(HORIZONTAL)
        self.tamano.setMinimum(1)
        self.tamano.setMaximum(8)
        self.tamano.setValue(2)
        rejilla.addWidget(self.tamano)
        return grupo

    def _grupo_bandas(self):
        grupo = QtWidgets.QGroupBox("Dimensiones")
        columna = QtWidgets.QVBoxLayout(grupo)
        columna.setSpacing(3)

        fila = QtWidgets.QHBoxLayout()
        fila.setSpacing(3)
        self.boton_ninguna = QtWidgets.QToolButton()
        self.boton_ninguna.setText("Ninguna")
        self.boton_repartir = QtWidgets.QToolButton()
        self.boton_repartir.setText("Repartir")
        self.boton_repartir.setToolTip(
            "Elige esta cantidad de bandas repartidas por todo el espectro")
        self.cuantas = QtWidgets.QSpinBox()
        self.cuantas.setMinimum(2)
        self.cuantas.setMaximum(60)
        self.cuantas.setValue(BANDAS_POR_DEFECTO)
        fila.addWidget(self.boton_repartir)
        fila.addWidget(self.cuantas)
        fila.addWidget(self.boton_ninguna)
        columna.addLayout(fila)

        self.lista_bandas = QtWidgets.QListWidget()
        self.lista_bandas.setAlternatingRowColors(True)
        self.lista_bandas.setToolTip(
            "Las bandas marcadas son las dimensiones de la nube")
        columna.addWidget(self.lista_bandas, 1)
        self.cuenta_bandas = QtWidgets.QLabel("-")
        self.cuenta_bandas.setWordWrap(True)
        columna.addWidget(self.cuenta_bandas)
        return grupo

    def _grupo_clases(self):
        grupo = QtWidgets.QGroupBox("Clases")
        columna = QtWidgets.QVBoxLayout(grupo)
        columna.setSpacing(3)
        self.lista_clases = QtWidgets.QListWidget()
        self.lista_clases.setAlternatingRowColors(True)
        self.lista_clases.setToolTip(
            "Apagar una clase la saca de la vista sin borrarla.\n"
            "Es lo que deja mirar dos grupos que se tapan.")
        self.lista_clases.setMinimumHeight(96)
        # Sin barra horizontal: el nombre de una firma puede ser largo y esa
        # barra se come una fila entera de una lista que ya es corta.
        self.lista_clases.setHorizontalScrollBarPolicy(
            enum(Qt, "ScrollBarPolicy", "ScrollBarAlwaysOff"))
        columna.addWidget(self.lista_clases, 1)
        return grupo

    def _grupo_seleccion(self):
        grupo = QtWidgets.QGroupBox("Seleccion")
        columna = QtWidgets.QVBoxLayout(grupo)
        columna.setSpacing(3)
        self.estado = QtWidgets.QLabel("Sin seleccion")
        self.estado.setWordWrap(True)
        columna.addWidget(self.estado)
        self.boton_firma = QtWidgets.QPushButton("Guardar como firma")
        self.boton_firma.setToolTip(
            "Convierte los pixeles rodeados con el lazo en una firma nueva")
        self.boton_firma.setEnabled(False)
        columna.addWidget(self.boton_firma)
        return grupo

    # -- conexiones ---------------------------------------------------------
    def _conectar(self):
        self.boton_girar.toggled.connect(self.vista.set_animar)
        self.boton_lazo.toggled.connect(
            lambda m: self.vista.set_modo(MODO_LAZO if m else MODO_GIRAR))
        self.boton_centrar.clicked.connect(self._centrar)
        self.velocidad.valueChanged.connect(
            lambda v: self.vista.set_velocidad(v / 25.0))
        self.tamano.valueChanged.connect(self.vista.set_tamano_punto)
        self.boton_ninguna.clicked.connect(lambda: self._marcar_todas(False))
        self.boton_repartir.clicked.connect(self._repartir)
        self.lista_bandas.itemChanged.connect(self._bandas_tocadas)
        self.lista_clases.itemChanged.connect(self._clases_tocadas)
        self.vista.seleccionHecha.connect(self._seleccion_hecha)
        self.boton_firma.clicked.connect(
            lambda: self.firmaPedida.emit(self._seleccion))

    # -- datos --------------------------------------------------------------
    def set_bandas_disponibles(self, longitudes, unidad="nm"):
        """Rellena la lista de bandas y elige unas cuantas repartidas."""
        self._longitudes = np.asarray(longitudes, dtype=np.float64)
        self._unidad = unidad
        self._bloqueado = True
        self.lista_bandas.clear()
        for i, wl in enumerate(self._longitudes):
            item = QtWidgets.QListWidgetItem(
                "%d   %.1f %s" % (i, wl, unidad))
            item.setFlags(item.flags()
                          | enum(Qt, "ItemFlag", "ItemIsUserCheckable"))
            item.setCheckState(enum(Qt, "CheckState", "Unchecked"))
            item.setData(enum(Qt, "ItemDataRole", "UserRole"), i)
            self.lista_bandas.addItem(item)
        self._bloqueado = False
        self._repartir()

    def set_nube(self, nube):
        """Entrega la nube ya armada al lienzo y refresca las clases."""
        self.vista.set_nube(nube)
        self._seleccion = None
        self.boton_firma.setEnabled(False)
        self.estado.setText("Sin seleccion")
        self._llenar_clases(nube)
        self.boton_girar.setEnabled(self.vista.puede_girar())
        if not self.vista.puede_girar():
            self.boton_girar.setChecked(False)
        puntos = 0 if nube is None else nube.X.shape[0]
        self.cuenta_bandas.setText(
            "%d dimensiones, %d puntos"
            % (0 if nube is None else nube.n_dimensiones, puntos))

    def _llenar_clases(self, nube):
        self._bloqueado = True
        self.lista_clases.clear()
        for clase in (nube.clases if nube is not None else []):
            item = QtWidgets.QListWidgetItem(
                "%s   (%d px)" % (clase.nombre, clase.cuenta))
            item.setFlags(item.flags()
                          | enum(Qt, "ItemFlag", "ItemIsUserCheckable"))
            item.setCheckState(enum(Qt, "CheckState",
                                    "Checked" if clase.visible
                                    else "Unchecked"))
            if clase.color:
                from .qt import QtGui
                item.setForeground(QtGui.QBrush(QtGui.QColor(clase.color)))
            self.lista_clases.addItem(item)
        self._bloqueado = False

    def bandas(self):
        """Los indices de las bandas marcadas, en orden."""
        marcado = enum(Qt, "CheckState", "Checked")
        return [i for i in range(self.lista_bandas.count())
                if self.lista_bandas.item(i).checkState() == marcado]

    # -- acciones -----------------------------------------------------------
    def _centrar(self):
        if self.vista.tour is not None:
            self.vista.tour.reiniciar_mano()
        self.vista.zoom = 1.0
        self.vista._proyectados = None
        self.vista.update()

    def _marcar_todas(self, marcadas):
        self._bloqueado = True
        estado = enum(Qt, "CheckState", "Checked" if marcadas else "Unchecked")
        for i in range(self.lista_bandas.count()):
            self.lista_bandas.item(i).setCheckState(estado)
        self._bloqueado = False
        self._bandas_tocadas()

    def _repartir(self):
        """Marca N bandas repartidas parejo por todo el eje espectral.

        Repartidas y no las primeras N: las bandas vecinas de un cubo
        hiperespectral estan casi perfectamente correlacionadas, asi que diez
        bandas seguidas son practicamente una sola dimension y la nube sale
        aplastada en una linea.
        """
        total = self.lista_bandas.count()
        if not total:
            return
        cuantas = min(self.cuantas.value(), total)
        elegidas = set(np.linspace(0, total - 1, cuantas).round().astype(int))
        self._bloqueado = True
        for i in range(total):
            self.lista_bandas.item(i).setCheckState(
                enum(Qt, "CheckState",
                     "Checked" if i in elegidas else "Unchecked"))
        self._bloqueado = False
        self._bandas_tocadas()

    def _bandas_tocadas(self, *_):
        if self._bloqueado:
            return
        self.bandasCambiadas.emit(self.bandas())

    def _clases_tocadas(self, *_):
        if self._bloqueado:
            return
        nube = self.vista.nube
        if nube is None:
            return
        marcado = enum(Qt, "CheckState", "Checked")
        for i, clase in enumerate(nube.clases):
            if i < self.lista_clases.count():
                clase.visible = (self.lista_clases.item(i).checkState()
                                 == marcado)
        self.vista.update()
        self.clasesCambiadas.emit()

    def _seleccion_hecha(self, indices):
        self._seleccion = indices
        cuantos = 0 if indices is None else len(indices)
        self.boton_firma.setEnabled(cuantos > 0)
        self.estado.setText(
            "%d pixeles seleccionados" % cuantos if cuantos
            else "El lazo no encerro ningun punto")

    def habilitar(self, activo):
        for w in (self.boton_girar, self.boton_lazo, self.boton_centrar,
                  self.velocidad, self.tamano, self.lista_bandas,
                  self.lista_clases, self.boton_repartir, self.cuantas,
                  self.boton_ninguna):
            w.setEnabled(activo)


__all__ = ["PanelND", "BANDAS_POR_DEFECTO"]
