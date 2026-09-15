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
"""La ventana del cubo: la vista grande y las herramientas al costado.

El cubo estaba dentro del panel acoplado, compitiendo por el alto con los
controles, el grafico y la lista de firmas. En un panel al costado de QGIS eso
deja una vista de doscientos pixeles para lo que es el centro del trabajo.

Aca el cubo se queda con la ventana entera menos una columna de herramientas,
y la ventana se mueve, se agranda y se manda a otra pantalla como cualquier
otra. El panel acoplado se queda con lo que si conviene tener siempre al lado
del mapa: el espectro, las bandas malas y la biblioteca.

No importa QGIS -solo Qt-, asi que se puede probar sin abrirlo.
"""

from .cube_view import (CubeView, MODO_AREA, MODO_MULTI, MODO_PAN, MODO_PIXEL,
                        MODO_X, MODO_Y, MODO_ZOOM)
from .qt import QtWidgets, Qt, pyqtSignal

#: Las siete herramientas, en el orden en que se ofrecen. Las dos primeras
#: solo cambian que parte se mira; las cinco siguientes miden algo.
HERRAMIENTAS = (
    (MODO_PAN, "Desplazar",
     "Arrastra la imagen.\nEl boton central del raton desplaza siempre, "
     "con cualquier herramienta."),
    (MODO_ZOOM, "Acercar",
     "Arrastra un rectangulo para acercarte a el.\n"
     "La rueda acerca y aleja; el boton derecho vuelve a ver todo."),
    (MODO_PIXEL, "Pixel", "Un clic extrae el espectro de ese pixel"),
    (MODO_X, "Linea X",
     "Fija una columna. Se mueve la vertical y cambia la cara derecha del "
     "cubo: el corte de esa columna."),
    (MODO_Y, "Linea Y",
     "Fija una fila. Se mueve la horizontal y cambia la cara superior: el "
     "corte de esa fila."),
    (MODO_AREA, "Area",
     "Arrastra un rectangulo: la firma es el promedio del area, con su "
     "desviacion como envolvente."),
    (MODO_MULTI, "Pixeles",
     "Cada clic suma un pixel al conjunto. La firma sale del promedio, y su "
     "variabilidad de la dispersion entre ellos."),
)

ANCHO_COLUMNA = 210


class VentanaCubo(QtWidgets.QWidget):
    """Ventana independiente con la vista del cubo y sus herramientas.

    Crea los widgets y los deja expuestos; no los conecta. Las conexiones
    viven en el panel, que es quien conoce al controlador: asi esta ventana
    sigue sin saber nada de QGIS.
    """

    #: El usuario eligio otra herramienta.
    herramientaCambiada = pyqtSignal(str)
    #: Pidio mandar la vista actual al mapa de QGIS.
    envioPedido = pyqtSignal()
    #: Se cerro la ventana.
    cerrada = pyqtSignal()

    def __init__(self, parent=None):
        super(VentanaCubo, self).__init__(parent)
        self.setWindowTitle("Cubo hiperespectral")
        self.setWindowFlags(Qt.Window)
        self.resize(1000, 700)

        caja = QtWidgets.QHBoxLayout(self)
        caja.setContentsMargins(6, 6, 6, 6)
        caja.setSpacing(6)
        caja.addLayout(self._columna_vista(), 1)
        caja.addWidget(self._columna_herramientas())

    # -- la vista y su barra ------------------------------------------------
    def _columna_vista(self):
        columna = QtWidgets.QVBoxLayout()
        columna.setSpacing(4)
        columna.addLayout(self._barra())
        self.cubo = CubeView()
        self.cubo.setMinimumSize(320, 240)
        columna.addWidget(self.cubo, 1)
        self.lectura = QtWidgets.QLabel(" ")
        columna.addWidget(self.lectura)
        return columna

    def _barra(self):
        fila = QtWidgets.QHBoxLayout()
        fila.setSpacing(3)
        self.boton_acercar = self._boton("+", "Acercar")
        self.boton_alejar = self._boton("-", "Alejar")
        self.boton_todo = self._boton("Ver todo", "Ver la escena entera")
        self.boton_datos = self._boton(
            "Ajustar a los datos",
            "Encuadra lo que tiene dato y deja fuera el relleno y los ceros")
        for b in (self.boton_acercar, self.boton_alejar, self.boton_todo,
                  self.boton_datos):
            fila.addWidget(b)
        fila.addStretch(1)
        self.boton_enviar = self._boton(
            "Enviar vista a QGIS",
            "Agrega al mapa SOLO el RGB que se esta viendo, recortado a la\n"
            "vista actual. No carga el cubo: son tres bandas de 8 bits.\n"
            "Sirve para digitalizar encima o componer un mapa mientras se\n"
            "sigue midiendo espectros en esta ventana.")
        fila.addWidget(self.boton_enviar)
        return fila

    def _boton(self, texto, ayuda):
        boton = QtWidgets.QPushButton(texto)
        boton.setToolTip(ayuda)
        return boton

    # -- la columna del costado ---------------------------------------------
    def _columna_herramientas(self):
        marco = QtWidgets.QWidget()
        marco.setFixedWidth(ANCHO_COLUMNA)
        columna = QtWidgets.QVBoxLayout(marco)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.setSpacing(6)
        columna.addWidget(self._grupo_herramientas())
        columna.addWidget(self._grupo_imagen())
        columna.addStretch(1)
        self.banda_frontal = QtWidgets.QLabel("frente: composicion RGB")
        self.banda_frontal.setWordWrap(True)
        columna.addWidget(self.banda_frontal)
        return marco

    def _grupo_herramientas(self):
        grupo = QtWidgets.QGroupBox("Herramienta")
        rejilla = QtWidgets.QGridLayout(grupo)
        rejilla.setSpacing(3)
        self.herramientas = {}
        # Un solo grupo exclusivo para las siete: todas definen que hace el
        # boton izquierdo, asi que tener dos juegos separados dejaria al
        # usuario con dos "modos activos" a la vez y ninguna forma de saber
        # cual manda.
        self.grupo_herramientas = QtWidgets.QButtonGroup(self)
        for i, (clave, texto, ayuda) in enumerate(HERRAMIENTAS):
            boton = QtWidgets.QToolButton()
            boton.setText(texto)
            boton.setCheckable(True)
            boton.setToolTip(ayuda)
            boton.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                QtWidgets.QSizePolicy.Preferred)
            self.grupo_herramientas.addButton(boton)
            # Dos por fila; las de navegacion quedan juntas arriba.
            rejilla.addWidget(boton, i // 2, i % 2)
            self.herramientas[clave] = boton
            boton.toggled.connect(
                lambda marcado, c=clave: marcado and
                self.herramientaCambiada.emit(c))
        self.herramientas[MODO_PIXEL].setChecked(True)
        return grupo

    def _grupo_imagen(self):
        grupo = QtWidgets.QGroupBox("Imagen")
        columna = QtWidgets.QVBoxLayout(grupo)
        columna.setSpacing(3)

        self.combo_preset = QtWidgets.QComboBox()
        self.combo_preset.setToolTip("Composicion de color")
        columna.addWidget(self.combo_preset)
        self.combo_realce = QtWidgets.QComboBox()
        self.combo_realce.setToolTip("Realce de la imagen")
        columna.addWidget(self.combo_realce)

        # El resumen va en su propia linea: al lado del boton se cortaba
        # -"848/658/555 n"- justo en la parte que informa.
        self.boton_bandas_rgb = QtWidgets.QToolButton()
        self.boton_bandas_rgb.setText("Bandas R G B")
        self.boton_bandas_rgb.setCheckable(True)
        self.boton_bandas_rgb.setToolTip("Elegir las bandas una por una")
        self.boton_bandas_rgb.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        columna.addWidget(self.boton_bandas_rgb)
        self.resumen_rgb = QtWidgets.QLabel("-")
        self.resumen_rgb.setAlignment(Qt.AlignCenter)
        self.resumen_rgb.setToolTip("Bandas que alimentan la imagen")
        columna.addWidget(self.resumen_rgb)

        self.panel_rgb = QtWidgets.QWidget()
        rejilla = QtWidgets.QGridLayout(self.panel_rgb)
        rejilla.setContentsMargins(0, 0, 0, 0)
        rejilla.setVerticalSpacing(2)
        self.controles_banda = {}
        for n, (canal, etiqueta) in enumerate(
                (("red", "R"), ("green", "G"), ("blue", "B"))):
            deslizador = QtWidgets.QSlider(Qt.Horizontal)
            deslizador.setMinimum(0)
            numero = QtWidgets.QSpinBox()
            numero.setMinimum(0)
            leyenda = QtWidgets.QLabel("-")
            rejilla.addWidget(QtWidgets.QLabel(etiqueta), n, 0)
            rejilla.addWidget(deslizador, n, 1)
            rejilla.addWidget(numero, n, 2)
            rejilla.addWidget(leyenda, n + 3, 0, 1, 3)
            self.controles_banda[canal] = (deslizador, numero, leyenda)
        rejilla.setColumnStretch(1, 1)
        self.panel_rgb.setVisible(False)
        columna.addWidget(self.panel_rgb)

        fila2 = QtWidgets.QHBoxLayout()
        fila2.addWidget(QtWidgets.QLabel("Paleta:"))
        self.combo_paleta = QtWidgets.QComboBox()
        fila2.addWidget(self.combo_paleta, 1)
        columna.addLayout(fila2)
        self.boton_rgb = QtWidgets.QPushButton("Volver al RGB")
        self.boton_rgb.setToolTip(
            "Deja de mostrar una sola banda en la cara frontal")
        columna.addWidget(self.boton_rgb)
        return grupo

    # -- estado -------------------------------------------------------------
    def set_herramienta(self, clave):
        """Marca una herramienta sin volver a emitir la senal."""
        boton = self.herramientas.get(clave)
        if boton is not None and not boton.isChecked():
            boton.blockSignals(True)
            boton.setChecked(True)
            boton.blockSignals(False)

    def herramienta(self):
        for clave, boton in self.herramientas.items():
            if boton.isChecked():
                return clave
        return MODO_PIXEL

    def habilitar(self, activo):
        for boton in self.herramientas.values():
            boton.setEnabled(activo)
        for w in (self.combo_preset, self.combo_realce, self.combo_paleta,
                  self.boton_rgb, self.boton_bandas_rgb, self.boton_acercar,
                  self.boton_alejar, self.boton_todo, self.boton_datos,
                  self.boton_enviar):
            w.setEnabled(activo)

    def closeEvent(self, evento):
        self.cerrada.emit()
        super(VentanaCubo, self).closeEvent(evento)
