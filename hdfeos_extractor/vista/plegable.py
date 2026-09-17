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
"""Una seccion que se pliega al pulsar su nombre.

El panel tiene cuatro bloques y una sola columna de alto para repartir entre
ellos. Segun lo que se este haciendo, uno de ellos es el trabajo y los otros
son contexto: al comparar firmas manda el grafico, al recorrer el cubo manda
el cubo, y en ese momento la lista de firmas y el perfil son dos franjas que
no se estan mirando y que le estan quitando alto a lo que si.

El mecanismo es el que ya tenian los deslizadores RGB y las bandas malas,
subido al titulo: el nombre de la seccion ES el boton. No hay que buscar una
flecha diminuta en una esquina, y la flecha del texto dice en que estado
esta, que es lo que distingue una seccion plegada de una seccion vacia.

NO se usa ``QGroupBox`` marcable, que es la forma que Qt trae de fabrica,
porque marcarlo APAGA Y ENCIENDE a todos sus hijos. Desplegar una seccion
volveria a encender los botones que el panel habia apagado a proposito
-porque no hay ninguna escena abierta- y el usuario podria pulsarlos. Una
prueba lo fija.

No importa QGIS -solo Qt-, asi que se puede probar sin abrirlo.
"""

from .qt import QtWidgets, pyqtSignal, politica

#: Lo que se antepone al nombre. Un triangulo hacia abajo abre hacia abajo,
#: que es lo que el usuario ve pasar al pulsarlo.
ABIERTA = u"▾ "        # triangulo abajo
PLEGADA = u"▸ "        # triangulo a la derecha


class GrupoPlegable(QtWidgets.QGroupBox):
    """Un bloque con nombre pulsable y un cuerpo que se esconde.

    Hereda de ``QGroupBox`` -sin titulo propio- para conservar el marco de
    los demas bloques del panel: la seccion sigue leyendose como una
    seccion. El titulo va dentro, como boton.
    """

    #: Cambio de estado. True = abierta. Quien la contiene lo necesita para
    #: repartir de nuevo el espacio que se acaba de liberar.
    plegado = pyqtSignal(bool)

    def __init__(self, titulo, parent=None, abierto=True, ayuda=None):
        super(GrupoPlegable, self).__init__(parent)
        self._titulo = titulo

        self.cabecera = QtWidgets.QToolButton()
        self.cabecera.setCheckable(True)
        self.cabecera.setChecked(abierto)
        # Sin relieve permanente: es un titulo que ademas se pulsa, no un
        # boton mas de la fila de botones.
        self.cabecera.setAutoRaise(True)
        self.cabecera.setSizePolicy(politica("Expanding"), politica("Fixed"))
        fuente = self.cabecera.font()
        fuente.setBold(True)
        self.cabecera.setFont(fuente)
        self.cabecera.setToolTip(
            ayuda or "Pulse el nombre para plegar o desplegar esta seccion")

        self.cuerpo = QtWidgets.QWidget()

        columna = QtWidgets.QVBoxLayout(self)
        columna.setContentsMargins(4, 2, 4, 4)
        columna.setSpacing(2)
        columna.addWidget(self.cabecera)
        columna.addWidget(self.cuerpo, 1)

        self.cabecera.toggled.connect(self._plegar)
        self._aplicar(abierto)

    # -- contenido ----------------------------------------------------------
    def poner(self, layout):
        """Instala el contenido de la seccion.

        Recibe el layout ya armado y no los widgets sueltos: quien construye
        el bloque sigue decidiendo como se ordena por dentro, y esta clase no
        tiene que saberlo.
        """
        self.cuerpo.setLayout(layout)
        return self.cuerpo

    # -- estado -------------------------------------------------------------
    def abierto(self):
        return self.cabecera.isChecked()

    def set_abierto(self, abierto):
        """Pliega o despliega sin que haga falta pulsar el boton."""
        self.cabecera.setChecked(bool(abierto))

    def _plegar(self, abierto):
        self._aplicar(abierto)
        self.plegado.emit(abierto)

    def _aplicar(self, abierto):
        self.cuerpo.setVisible(abierto)
        self.cabecera.setText((ABIERTA if abierto else PLEGADA)
                              + self._titulo)
        # Plegada deja de pedir alto. Sin esto la seccion se queda con el
        # sitio que tenia y plegarla no le daria nada al cubo, que es lo
        # unico que se gana plegandola.
        self.setSizePolicy(
            politica("Preferred"),
            politica("Expanding") if abierto else politica("Fixed"))
