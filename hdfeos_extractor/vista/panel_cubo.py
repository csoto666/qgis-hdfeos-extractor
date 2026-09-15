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
"""El bloque del cubo: la vista grande y las herramientas al costado.

Esto empezo dentro del panel acoplado, se mudo a una ventana propia porque
ahi competia por el alto con todo lo demas, y ahora vuelve al panel pero como
una mitad entera de un divisor, no como una franja. Las dos cosas que hacian
falta eran tener el cubo y el espectro a la vista a la vez -son las dos caras
del mismo dato- y que el cubo tuviera alto de verdad. Un divisor da las dos:
el usuario reparte el espacio y el reparto queda donde el lo dejo.

El bloque sirve igual empotrado que suelto en una ventana aparte, porque es
un widget corriente y quien lo usa decide donde ponerlo. El boton de soltar
esta para cuando hay dos pantallas, que es cuando la ventana aparte gana.

No importa QGIS -solo Qt-, asi que se puede probar sin abrirlo.
"""

from .cube_view import (CubeView, MODO_AREA, MODO_MULTI, MODO_PAN, MODO_PIXEL,
                        MODO_X, MODO_Y, MODO_ZOOM)
from .qt import QtWidgets, Qt, enum, pyqtSignal

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

#: La columna de herramientas se conforma con menos cuando el panel esta
#: acoplado al costado de QGIS. Era ancho fijo, y con el cubo empotrado ese
#: ancho fijo se sumaba al minimo del bloque entero: el panel no bajaba de
#: mil quinientos pixeles y no entraba en ningun costado.
ANCHO_COLUMNA = 210
ANCHO_COLUMNA_MIN = 148


class PanelCubo(QtWidgets.QWidget):
    """La vista del cubo y sus herramientas, empotrable o suelta.

    Crea los widgets y los deja expuestos; no los conecta. Las conexiones
    viven en el panel del explorador, que es quien conoce al controlador:
    asi este bloque sigue sin saber nada de QGIS.
    """

    #: El usuario eligio otra herramienta.
    herramientaCambiada = pyqtSignal(str)
    #: Pidio mandar la vista actual al mapa de QGIS.
    envioPedido = pyqtSignal()
    #: Pidio soltar el cubo a una ventana aparte, o volver a empotrarlo.
    soltarPedido = pyqtSignal(bool)
    #: Se cerro la ventana suelta.
    cerrada = pyqtSignal()

    def __init__(self, parent=None):
        super(PanelCubo, self).__init__(parent)
        self.setWindowTitle("Cubo hiperespectral")

        caja = QtWidgets.QHBoxLayout(self)
        caja.setContentsMargins(6, 6, 6, 6)
        caja.setSpacing(6)
        caja.addLayout(self._columna_vista(), 1)
        caja.addWidget(self._herramientas_con_barrido())

    # -- la vista y su barra ------------------------------------------------
    def _columna_vista(self):
        columna = QtWidgets.QVBoxLayout()
        columna.setSpacing(4)
        columna.addLayout(self._barra())
        self.cubo = CubeView()
        # Chico a proposito: es el minimo con el que el cubo sigue siendo
        # legible, y de el depende cuanto puede angostarse el panel entero.
        self.cubo.setMinimumSize(200, 160)
        columna.addWidget(self.cubo, 1)
        self.lectura = QtWidgets.QLabel(" ")
        columna.addWidget(self.lectura)
        return columna

    def _barra(self):
        """Solo encuadre: acercar, alejar y los dos encuadres utiles.

        Con botones pequenos y etiquetas cortas. Eran QPushButton con el
        texto entero -"Ajustar a los datos", "Enviar vista a QGIS"- y entre
        los seis pedian setecientos pixeles de ancho minimo, que es la mitad
        de la razon por la que el panel no entraba acoplado al costado.
        """
        fila = QtWidgets.QHBoxLayout()
        fila.setSpacing(3)
        self.boton_acercar = self._boton("+", "Acercar")
        self.boton_alejar = self._boton("-", "Alejar")
        self.boton_todo = self._boton("Todo", "Ver la escena entera")
        self.boton_datos = self._boton(
            "Datos",
            "Encuadra lo que tiene dato y deja fuera el relleno y los ceros")
        for b in (self.boton_acercar, self.boton_alejar, self.boton_todo,
                  self.boton_datos):
            fila.addWidget(b)
        fila.addStretch(1)
        return fila

    def _boton(self, texto, ayuda):
        boton = QtWidgets.QToolButton()
        boton.setText(texto)
        boton.setToolTip(ayuda)
        return boton

    # -- la columna del costado ---------------------------------------------
    def _herramientas_con_barrido(self):
        """La columna del costado: lo que se desplaza y lo que no.

        Los grupos apilados piden medio millar de pixeles de alto, y ese
        numero se convertia en el alto minimo de todo el panel: acoplado al
        costado de QGIS, el explorador no cabia en una pantalla de portatil.
        Un area de desplazamiento lo arregla, pero con todo dentro el boton
        de enviar la vista al mapa quedaba bajo el pliegue, y es la accion
        por la que se abre esta ventana. Asi que la salida va anclada abajo,
        fuera del area: se desplaza lo que se ajusta de vez en cuando y se
        queda fijo lo que se pulsa.
        """
        marco = QtWidgets.QWidget()
        marco.setMaximumWidth(ANCHO_COLUMNA + 16)
        marco.setMinimumWidth(ANCHO_COLUMNA_MIN + 16)
        marco.setSizePolicy(QtWidgets.QSizePolicy.Maximum,
                            QtWidgets.QSizePolicy.Preferred)
        columna = QtWidgets.QVBoxLayout(marco)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.setSpacing(6)

        area = QtWidgets.QScrollArea()
        area.setWidget(self._columna_herramientas())
        area.setWidgetResizable(True)
        area.setFrameShape(QtWidgets.QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(
            enum(Qt, "ScrollBarPolicy", "ScrollBarAlwaysOff"))
        columna.addWidget(area, 1)
        columna.addWidget(self._grupo_salida())
        return marco

    def _columna_herramientas(self):
        marco = QtWidgets.QWidget()
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

    def _grupo_salida(self):
        """Lo que saca el cubo de aca: al mapa, o a una ventana propia.

        Van juntos y en la columna, no en la barra de encuadre: no cambian
        lo que se ve, cambian donde va. Y en la barra su texto largo obligaba
        a un ancho que el panel acoplado no tiene.
        """
        grupo = QtWidgets.QGroupBox("Salida")
        columna = QtWidgets.QVBoxLayout(grupo)
        columna.setSpacing(3)
        self.boton_enviar = QtWidgets.QPushButton("Enviar vista a QGIS")
        self.boton_enviar.setToolTip(
            "Agrega al mapa SOLO el RGB que se esta viendo, recortado a la\n"
            "vista actual y en su sitio. No carga el cubo: son tres bandas\n"
            "de 8 bits. Sirve para digitalizar encima o componer un mapa\n"
            "mientras se sigue midiendo espectros aca al lado.")
        columna.addWidget(self.boton_enviar)
        self.boton_soltar = QtWidgets.QPushButton("Soltar aparte")
        self.boton_soltar.setCheckable(True)
        self.boton_soltar.setToolTip(
            "Saca el cubo a una ventana aparte, para mandarlo a otra\n"
            "pantalla. Cerrar esa ventana lo devuelve aca.")
        self.boton_soltar.toggled.connect(self.soltarPedido.emit)
        columna.addWidget(self.boton_soltar)
        return grupo

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
                  self.boton_enviar, self.boton_soltar):
            w.setEnabled(activo)

    def closeEvent(self, evento):
        """Cerrar la ventana suelta devuelve el cubo al panel.

        Es lo unico que no deja al usuario sin cubo y sin forma obvia de
        recuperarlo. Quien la cierra quiere dejar de tener una ventana
        suelta, no perder la vista.
        """
        self.cerrada.emit()
        super(PanelCubo, self).closeEvent(evento)
