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
"""El panel acoplable: toda la interfaz del plugin en un QDockWidget.

El lienzo de QGIS sigue siendo la vista espacial principal. Este panel aporta
lo que el lienzo no tiene -el eje espectral- y los controles que relacionan
los dos.

El panel no toca el cubo ni la biblioteca directamente: pide y escucha al
controlador. Es lo que permite que el mapa, el grafico y la lista de firmas
se mantengan sincronizados sin que cada uno conozca a los otros dos.
"""

import os

from qgis.core import QgsProject, QgsRasterLayer

from ..core.cube import CubeError, HyperspectralCube
from ..core.georef import Georreferencia
from ..core.hdf5 import Hdf5Source
from ..core.library import LibraryError, SpectralLibrary
from ..core.bandas import formatear_rangos, parsear_rangos
from ..core.colormap import nombres as paletas
from ..core.rgb import MODOS, RGBComposer
from ..vista.cube_view import MODOS_NAVEGACION
from ..vista.panel_cubo import PanelCubo, VentanaSuelta
from ..vista.qt import (HORIZONTAL, VERTICAL, QtCore, QtGui,
                        QtWidgets, Qt, enum, politica)
from ..vista.spectral_plot import SpectralPlot
from . import map_tools
from .controller import SpatialSpectralController
from .exportar import ErrorExportar, enviar_vista
from .render import aplicar_composicion
from .vinculo import VinculoVistas

ETIQUETAS_REALCE = {
    "percentil": "Percentil 2-98",
    "minmax": "Minimo-maximo",
    "reflectancia": "Reflectancia 0-1",
    "desviacion": "Media +- 2 sigma",
}

FILTRO_ARCHIVOS = (
    "Cubos hiperespectrales (*.h5 *.he5 *.hdf5 *.hdr *.dat *.img *.bil "
    "*.bsq *.bip *.tif *.tiff);;"
    "HDF-EOS5 (*.h5 *.he5 *.hdf5);;"
    "ENVI (*.hdr *.dat *.img *.bil *.bsq *.bip);;"
    "Todos los archivos (*)")

#: Identificador del algoritmo de extraccion, para abrirlo desde el panel.
ALGORITMO_EXTRAER = "hdfeos_extractor:extraer_hdfeos_a_envi"


#: Enums de Qt que se usan en varios sitios del panel. En Qt6 viven dentro de
#: su clase; resolverlos aqui una vez deja las comparaciones legibles.
_AREA_IZQUIERDA = enum(Qt, "DockWidgetArea", "LeftDockWidgetArea")
_AREA_DERECHA = enum(Qt, "DockWidgetArea", "RightDockWidgetArea")
_AREA_ARRIBA = enum(Qt, "DockWidgetArea", "TopDockWidgetArea")
_AREA_ABAJO = enum(Qt, "DockWidgetArea", "BottomDockWidgetArea")
_MARCADO = enum(Qt, "CheckState", "Checked")
_SIN_MARCAR = enum(Qt, "CheckState", "Unchecked")

TITULO = "Hyperspectral Explorer"


def georreferencia_de(cubo, capa):
    """De donde saca la escena sus coordenadas, en orden de confianza.

    Primero el archivo. Solo si el archivo no dice nada se recurre a la capa
    de QGIS, y ese camino es un ultimo recurso declarado: la extension de una
    capa es la caja que envuelve la escena, asi que con una escena rotada da
    un origen y un tamano de pixel que no son los suyos. Preferir el archivo
    es todo el arreglo del problema de proyeccion.
    """
    propia = cubo.georreferencia if cubo is not None else None
    if propia is not None and propia.tiene_mapa:
        return propia
    if capa is not None:
        de_capa = Georreferencia.de_capa(capa)
        if de_capa.tiene_mapa:
            return de_capa
    return propia if propia is not None else Georreferencia.ninguna()


def _aviso_de_georreferencia(georref):
    """Lo que hay que decirle al usuario sobre donde quedo la capa."""
    if georref.necesita_remuestreo:
        return ("La escena viene en geometria de sensor: la vista se "
                "reproyecto con los puntos de control del producto (%s). "
                "Los pixeles se remuestrearon, asi que sirve para ubicar y "
                "digitalizar, no para medir." % (georref.nombre_src or "-"))
    if not georref.tiene_mapa:
        return ("Sin georreferencia: la escena no dice donde esta, asi que "
                "la capa queda en coordenadas de pixel y no se alineara con "
                "otras. %s" % georref.nota)
    if not georref.tiene_src:
        return ("La escena trae coordenadas pero no dice en que sistema: la "
                "capa sale sin SRC y hay que asignarselo a mano. %s"
                % georref.nota)
    aviso = "Georreferencia: %s." % georref.describir()
    if georref.nota:
        aviso += " " + georref.nota
    return aviso


class HyperspectralDock(QtWidgets.QDockWidget):
    """Panel principal del explorador."""

    def __init__(self, iface, parent=None):
        super(HyperspectralDock, self).__init__(TITULO, parent)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.controller = SpatialSpectralController(self)
        self.herramienta = None
        self._bloqueado = False        # corta los bucles de senales
        self.divisor = None            # existe recien en _construir
        self._cubo_suelto = False
        self.vinculo = None            # necesita el cubo, que aun no existe
        # Hijo del panel a proposito: Qt lo destruye junto con el, asi que un
        # empotrado aplazado no puede dispararse sobre un panel ya borrado.
        # Un QTimer.singleShot suelto no da esa garantia -no admite objeto de
        # contexto en estas vinculaciones- y dejaria una llamada pendiente
        # hacia un objeto de C++ que ya no existe.
        self._aplazado = QtCore.QTimer(self)
        self._aplazado.setSingleShot(True)
        # Lo mismo para lo que hay que rehacer al volver a mostrar el panel:
        # el showEvent corre dentro de la animacion de acople de QGIS y ahi
        # no se toca nada de fuera. Vease showEvent.
        self._al_mostrar = QtCore.QTimer(self)
        self._al_mostrar.setSingleShot(True)

        self.setObjectName("HyperspectralExplorerDock")
        self.setWidget(self._construir())
        self._conectar()
        self.recargar_capas()
        self._habilitar(False)

    # -- construccion -------------------------------------------------------
    def _construir(self):
        """El cubo y el espectro en la misma herramienta, repartidos a mano.

        Son las dos caras del mismo dato -donde esta el pixel y que mide- y
        mirarlas a la vez es todo el trabajo. Estuvieron apiladas en una
        columna, y ahi el cubo se quedaba con doscientos pixeles de alto;
        despues en dos ventanas, y ahi habia que ir y volver. Un divisor
        resuelve las dos cosas: cada mitad tiene alto de verdad, el usuario
        reparte el espacio y el reparto se queda donde el lo dejo.
        """
        self.panel_cubo = PanelCubo()
        self._adoptar_widgets_del_cubo()
        # Vacia hasta que se suelte el cubo. Se crea junto con el panel para
        # que soltar sea solo mudar de padre, sin construir nada en caliente.
        self.ventana_suelta = VentanaSuelta(self._ventana_principal())

        # En el divisor van las dos vistas y nada mas. Metiendo ademas la
        # fila de la escena, la biblioteca y el estado, la mitad de abajo
        # sumaba minimos hasta desbordar y los bloques se pisaban. Lo que no
        # necesita area queda fuera, arriba y abajo, donde ocupa su alto y
        # se acaba la discusion.
        self.divisor = QtWidgets.QSplitter(HORIZONTAL)
        self.divisor.setChildrenCollapsible(False)
        self.divisor.addWidget(self.panel_cubo)
        self.divisor.addWidget(self._bloque_grafico())
        self.divisor.setStretchFactor(0, 3)
        self.divisor.setStretchFactor(1, 2)
        self._orientar_divisor()

        contenedor = QtWidgets.QWidget()
        caja = QtWidgets.QVBoxLayout(contenedor)
        caja.setContentsMargins(6, 6, 6, 6)
        caja.setSpacing(6)
        caja.addWidget(self._bloque_escena())
        caja.addWidget(self.divisor, 1)
        caja.addWidget(self._bloque_firmas())
        self.estado = QtWidgets.QLabel("Elija una capa raster hiperespectral")
        self.estado.setWordWrap(True)
        caja.addWidget(self.estado)
        return contenedor

    def _orientar_divisor(self):
        """Reparte a lo ancho o a lo alto segun donde este el panel.

        Un dock de QGIS vive igual pegado al costado -alto y angosto- que
        abajo o flotando -ancho y bajo-. Con una orientacion fija, la mitad
        de esas posiciones deja las dos vistas en una franja inservible.

        Se mira primero el area de acople y solo despues la forma, y ese
        orden importa: el ancho minimo de un divisor acostado es la suma de
        sus mitades, asi que decidir por el ancho actual se muerde la cola
        -el panel no puede angostarse hasta que se apile, y no se apila
        hasta que se angoste-. El area no depende del tamano y corta el
        nudo.
        """
        if self.divisor is None:
            return
        quiere = HORIZONTAL if self._conviene_a_lo_ancho() else VERTICAL
        if self.divisor.orientation() != quiere:
            self.divisor.setOrientation(quiere)
            self._repartir_divisor()

    def _repartir_divisor(self):
        """Reparte de nuevo al cambiar de orientacion, y solo entonces.

        Al voltearlo, Qt conserva los tamanos del reparto anterior y quedan
        sin sentido: apilado, el cubo se quedaba con casi todo el alto y al
        espectro le tocaba una franja de setenta pixeles. Se reparte una vez
        -algo mas para el cubo, que es el que necesita area- y a partir de
        ahi manda el usuario: dentro de una misma orientacion no se le toca
        el divisor.
        """
        largo = (self.divisor.width()
                 if self.divisor.orientation() == HORIZONTAL
                 else self.divisor.height())
        if largo > 0:
            cubo = int(largo * 0.56)
            self.divisor.setSizes([cubo, largo - cubo])

    def _conviene_a_lo_ancho(self):
        area = self._area_de_acople()
        if area in (_AREA_IZQUIERDA, _AREA_DERECHA):
            # Columna: el cubo arriba y el espectro abajo.
            return False
        if area in (_AREA_ARRIBA, _AREA_ABAJO):
            return True                # franja ancha: uno al lado del otro
        return self.width() >= self.height() * 1.2      # flotante

    def _area_de_acople(self):
        """Donde esta acoplado, o None si flota o todavia no se sabe."""
        if self.isFloating():
            return None
        ventana = self._ventana_principal()
        try:
            return ventana.dockWidgetArea(self) if ventana else None
        except (AttributeError, RuntimeError):
            return None

    def _ventana_principal(self):
        """La ventana de QGIS, o None si el anfitrion no la ofrece."""
        try:
            return self.iface.mainWindow()
        except (AttributeError, RuntimeError):
            return None

    def resizeEvent(self, evento):
        super(HyperspectralDock, self).resizeEvent(evento)
        self._orientar_divisor()

    # -- vinculo con el lienzo ----------------------------------------------
    def _vincular(self, encender):
        """Enciende o apaga el seguimiento entre el cubo y el mapa.

        El boton se desmarca solo si no se pudo: dejarlo hundido sobre un
        vinculo que no existe es la clase de mentira que hace desconfiar de
        todo lo demas.
        """
        if self.vinculo is None:
            return
        motivo = self.vinculo.activar(encender)
        if encender and not self.vinculo.activo:
            boton = self.panel_cubo.boton_vinculo
            boton.blockSignals(True)
            boton.setChecked(False)
            boton.blockSignals(False)
        self._avisar(motivo)

    def _soltar_vinculo(self):
        """Apaga el vinculo al cerrar o cambiar de escena.

        Sin esto queda escuchando al lienzo con un cubo que ya no esta, y el
        primer desplazamiento del mapa busca una ventana en una escena
        cerrada.
        """
        if self.vinculo is not None and self.vinculo.activo:
            self.vinculo.activar(False)
            boton = self.panel_cubo.boton_vinculo
            boton.blockSignals(True)
            boton.setChecked(False)
            boton.blockSignals(False)

    # -- soltar y empotrar el cubo ------------------------------------------
    def _soltar_cubo(self, suelto):
        """Saca el cubo a una ventana aparte, o lo devuelve al divisor.

        Empotrado es lo normal; suelto gana cuando hay dos pantallas. Pasar
        de uno a otro es solo cambiar de padre -del divisor a la ventana de
        al lado y de vuelta-, asi que la vista no se reconstruye: el cubo
        abierto, el zoom y la herramienta elegida siguen donde estaban.

        Lo que NO se hace es volver ventana al propio cubo. Esa es la
        diferencia que importa: ponerle y quitarle la bandera de ventana a
        un widget ya montado colgaba QGIS en macOS. Vease ``VentanaSuelta``.
        """
        if suelto == self._cubo_suelto or self.ventana_suelta is None:
            return
        self._cubo_suelto = suelto
        if suelto:
            self.ventana_suelta.resize(1000, 700)
            self.ventana_suelta.alojar(self.panel_cubo)
        else:
            self.divisor.insertWidget(0, self.panel_cubo)
            self.divisor.setStretchFactor(0, 3)
            self.panel_cubo.show()
            self.ventana_suelta.hide()
        self.panel_cubo.boton_soltar.setText(
            "Empotrar aqui" if suelto else "Soltar aparte")

    def _cubo_cerrado(self):
        """La ventana suelta se cerro: el cubo vuelve al panel.

        Nunca se pierde la vista por cerrar una ventana. El boton se
        desmarca solo, y desmarcarlo es lo que empotra de vuelta.

        Se aplaza al siguiente giro del bucle de eventos, y no es un adorno:
        esto corre DENTRO del closeEvent de la propia ventana. Reinsertarla
        y mostrarla ahi mismo no sirve, porque Qt termina de cerrar despues y
        la vuelve a esconder: el cubo quedaba empotrado pero invisible, sin
        ningun boton que dijera "traelo de vuelta".
        """
        if self._cubo_suelto:
            self._aplazado.start(0)

    def _reempotrar_cubo(self):
        """Desmarcar el boton es lo que dispara el empotrado."""
        if self._cubo_suelto:
            self.panel_cubo.boton_soltar.setChecked(False)

    def _adoptar_widgets_del_cubo(self):
        """Toma prestados los widgets que viven en el bloque del cubo.

        El bloque los crea y los muestra; el panel los conecta, porque es
        quien conoce al controlador. Asi el bloque sigue sin saber nada de
        QGIS y las conexiones siguen viviendo en un solo lugar.
        """
        v = self.panel_cubo
        self.cubo = v.cubo
        self.modos = v.herramientas
        self.combo_preset = v.combo_preset
        self.combo_realce = v.combo_realce
        self.combo_paleta = v.combo_paleta
        self.controles_banda = v.controles_banda
        self.panel_rgb = v.panel_rgb
        self.resumen_rgb = v.resumen_rgb
        self.boton_bandas_rgb = v.boton_bandas_rgb
        self.boton_rgb = v.boton_rgb
        self.boton_datos = v.boton_datos
        self.boton_todo = v.boton_todo
        self.banda_frontal = v.banda_frontal
        # La lectura del cursor va junto al cubo, que es donde esta el
        # cursor. Estaba duplicada: el bloque espectral creaba otra etiqueta
        # con el mismo nombre y se quedaba con el texto, asi que la de aca
        # no se escribia nunca.
        self.lectura = v.lectura
        for modo in MODOS:
            self.combo_realce.addItem(ETIQUETAS_REALCE.get(modo, modo), modo)
        for nombre in paletas():
            self.combo_paleta.addItem(nombre)

    def _bloque_escena(self):
        """Capa y modo de navegacion en un solo grupo.

        Eran dos: dos titulos y dos marcos para dos filas. En un panel
        acoplado al costado ese adorno se lo quita a las vistas, que es lo
        unico que de verdad necesita alto.
        """
        grupo = QtWidgets.QGroupBox("Escena")
        columna = QtWidgets.QVBoxLayout(grupo)
        columna.setSpacing(4)
        columna.addLayout(self._fila_capa())
        return grupo

    def _fila_capa(self):
        rejilla = QtWidgets.QHBoxLayout()
        self.combo_capa = QtWidgets.QComboBox()
        self.combo_capa.setSizePolicy(politica("Expanding"),
                                      politica("Preferred"))
        self.boton_abrir = QtWidgets.QPushButton("Abrir...")
        self.boton_abrir.setToolTip(
            "Abre un cubo desde el disco: HDF-EOS5 directamente, o un ENVI "
            "ya extraido")
        self.boton_extraer = QtWidgets.QPushButton("Extraer...")
        self.boton_extraer.setToolTip(
            "Escribe la escena HDF-EOS5 abierta en formato nativo de ENVI, "
            "para llevarla a otro programa")
        self.boton_extraer.setEnabled(False)
        rejilla.addWidget(QtWidgets.QLabel("Capa:"))
        rejilla.addWidget(self.combo_capa, 1)
        rejilla.addWidget(self.boton_abrir)
        rejilla.addWidget(self.boton_extraer)
        return rejilla

    def _bloque_grafico(self):
        grupo = QtWidgets.QGroupBox("Perfil espectral")
        caja = QtWidgets.QVBoxLayout(grupo)
        caja.setContentsMargins(3, 3, 3, 3)
        self.grafico = SpectralPlot()
        # Un piso para el grafico: apilado bajo el cubo se quedaba en una
        # franja donde no se distingue una firma de otra, que es justo lo
        # que hay que mirar.
        self.grafico.setMinimumHeight(130)
        caja.addWidget(self.grafico, 1)
        # Fila siempre visible: la lectura del cursor, la cuenta de bandas
        # descartadas -que hay que ver aunque no se este configurando nada- y
        # el boton que despliega los controles.
        fila = QtWidgets.QHBoxLayout()
        self.boton_bandas = QtWidgets.QToolButton()
        self.boton_bandas.setText("Bandas malas")
        self.boton_bandas.setCheckable(True)
        self.boton_bandas.setToolTip(
            "Elegir que bandas quedan fuera del analisis")
        fila.addWidget(self.boton_bandas)
        self.cuenta_bandas = QtWidgets.QLabel("-")
        # Con ajuste de linea: el texto enumera los tramos descartados y sin
        # esto su largo se convertia en el ancho minimo del panel entero.
        self.cuenta_bandas.setWordWrap(True)
        fila.addWidget(self.cuenta_bandas, 1)
        caja.addLayout(fila)

        # Los controles van escondidos por defecto. Son un ajuste por escena,
        # no algo que se toque todo el rato, y el panel acoplado al costado no
        # tiene alto de sobra: dejarlos siempre visibles se lo quitaba justo a
        # las dos vistas, que es lo que hay que mirar.
        self.panel_bandas = QtWidgets.QWidget()
        self.panel_bandas.setLayout(self._filas_bandas_malas())
        self.panel_bandas.setVisible(False)
        caja.addWidget(self.panel_bandas)
        return grupo

    def _filas_bandas_malas(self):
        columna = QtWidgets.QVBoxLayout()
        columna.setContentsMargins(0, 0, 0, 0)
        columna.setSpacing(2)

        fila = QtWidgets.QHBoxLayout()
        fila.addWidget(QtWidgets.QLabel("Descartar:"))
        self.casillas_bandas = {}
        for clave, texto, ayuda in (
                ("usar_bbl", "del archivo",
                 "La lista de bandas malas (bbl) que trae el propio\n"
                 "producto. Se desactiva si el archivo no la incluye."),
                ("usar_absorcion", "vapor de agua",
                 "1340-1460 y 1790-1960 nm. Ahi el vapor atmosferico\n"
                 "absorbe casi todo: lo que vuelve es ruido, no terreno."),
                ("usar_extremos", "extremos",
                 "Por debajo de 400 y por encima de 2450 nm el sensor\n"
                 "ya no responde bien y la relacion senal-ruido cae.")):
            casilla = QtWidgets.QCheckBox(texto)
            casilla.setToolTip(ayuda)
            casilla.setChecked(True)
            fila.addWidget(casilla)
            self.casillas_bandas[clave] = casilla
        fila.addStretch(1)
        columna.addLayout(fila)

        fila2 = QtWidgets.QHBoxLayout()
        fila2.addWidget(QtWidgets.QLabel("Rangos propios:"))
        self.campo_rangos = QtWidgets.QLineEdit()
        self.campo_rangos.setPlaceholderText("1340-1460, 1790-1960")
        self.campo_rangos.setToolTip(
            "Rangos en nanometros, separados por comas. Un valor suelto\n"
            "descarta esa sola banda. Se aplica al terminar de escribir.")
        fila2.addWidget(self.campo_rangos, 1)
        columna.addLayout(fila2)
        return columna

    def _boton_chico(self, texto, ayuda):
        boton = QtWidgets.QToolButton()
        boton.setText(texto)
        boton.setToolTip(ayuda)
        boton.setSizePolicy(politica("Expanding"), politica("Preferred"))
        return boton

    def _bloque_firmas(self):
        grupo = QtWidgets.QGroupBox("Firmas guardadas")
        # Preferred/Maximum y no el Expanding que traen los grupos: sin esto
        # se queda con el alto sobrante en vez de cederselo al divisor, que
        # es donde estan las dos vistas.
        grupo.setSizePolicy(politica("Preferred"), politica("Maximum"))
        caja = QtWidgets.QVBoxLayout(grupo)
        self.lista = QtWidgets.QListWidget()
        self.lista.setAlternatingRowColors(True)
        # Con un tope, la lista deja de competir por el alto con las dos
        # vistas. Acoplado al costado el panel es alto y angosto, y la suma de
        # los minimos de cuatro bloques ahoga al divisor.
        self.lista.setMinimumHeight(48)
        self.lista.setMaximumHeight(88)
        self.lista.setToolTip(
            "La casilla muestra u oculta la curva en el grafico")
        caja.addWidget(self.lista)

        # QToolButton y no QPushButton: los cuatro en fila con el ancho
        # minimo de un boton normal pedian casi cuatrocientos pixeles, y ese
        # numero terminaba siendo el ancho minimo del panel acoplado.
        fila = QtWidgets.QHBoxLayout()
        fila.setSpacing(3)
        self.boton_guardar = self._boton_chico(
            "Guardar", "Guarda la firma que se esta viendo")
        self.boton_renombrar = self._boton_chico(
            "Renombrar", "Cambia el nombre de la firma elegida")
        self.boton_quitar = self._boton_chico(
            "Quitar", "Saca de la biblioteca la firma elegida")
        for b in (self.boton_guardar, self.boton_renombrar, self.boton_quitar):
            fila.addWidget(b)
        caja.addLayout(fila)

        # Abrir, guardar y exportar van en un menu y no en una segunda fila
        # de botones: se usan una vez por sesion y esa fila le quitaba alto
        # permanente a las dos vistas.
        self.menu_lib = QtWidgets.QMenu(self)
        self.accion_abrir_lib = self.menu_lib.addAction("Abrir biblioteca...")
        self.accion_guardar_lib = self.menu_lib.addAction(
            "Guardar biblioteca...")
        self.accion_csv = self.menu_lib.addAction("Exportar CSV...")
        self.boton_lib = QtWidgets.QToolButton()
        self.boton_lib.setText("Archivo")
        self.boton_lib.setMenu(self.menu_lib)
        self.boton_lib.setPopupMode(
            enum(QtWidgets.QToolButton, "ToolButtonPopupMode",
                 "InstantPopup"))
        fila.addWidget(self.boton_lib)
        return grupo

    # -- conexiones ---------------------------------------------------------
    def _conectar(self):
        self.combo_capa.currentIndexChanged.connect(self._capa_elegida)
        self.boton_abrir.clicked.connect(self._abrir_archivo)
        self.boton_extraer.clicked.connect(self._extraer_a_envi)
        self.panel_cubo.herramientaCambiada.connect(self._cambiar_modo)
        self.panel_cubo.envioPedido.connect(self._enviar_a_qgis)
        self.panel_cubo.boton_enviar.clicked.connect(self._enviar_a_qgis)
        self.panel_cubo.soltarPedido.connect(self._soltar_cubo)
        self._aplazado.timeout.connect(self._reempotrar_cubo)
        self._al_mostrar.timeout.connect(self._restablecer)
        self.vinculo = VinculoVistas(self.cubo, self.canvas, self.controller,
                                     self)
        self.panel_cubo.vinculoPedido.connect(self._vincular)
        # Mover el panel de costado a abajo cambia que reparto conviene, y
        # no pasa por resizeEvent con la forma final: hay que escucharlo.
        self.dockLocationChanged.connect(lambda _area:
                                         self._orientar_divisor())
        self.topLevelChanged.connect(lambda _flota: self._orientar_divisor())
        self.ventana_suelta.cerrada.connect(self._cubo_cerrado)
        self.panel_cubo.boton_acercar.clicked.connect(
            lambda: self.cubo.acercar(0.7))
        self.panel_cubo.boton_alejar.clicked.connect(
            lambda: self.cubo.acercar(1.0 / 0.7))

        self.combo_preset.activated.connect(self._preset_elegido)
        self.combo_realce.activated.connect(self._realce_elegido)
        for canal, (deslizador, numero, _) in self.controles_banda.items():
            deslizador.valueChanged.connect(
                lambda v, c=canal: self._banda_cambiada(c, v))
            numero.valueChanged.connect(
                lambda v, c=canal: self._banda_cambiada(c, v))

        self.boton_guardar.clicked.connect(self._guardar_firma)
        self.boton_renombrar.clicked.connect(self._renombrar_firma)
        self.boton_quitar.clicked.connect(self._quitar_firma)
        self.lista.itemChanged.connect(self._visibilidad_cambiada)

        # El cubo y el mapa son dos maneras de senalar el mismo pixel, asi
        # que los dos entran por el controlador y los dos escuchan su
        # respuesta. Mover la cruz del cubo mueve el resaltado del mapa, y al
        # reves, sin que ninguno de los dos conozca al otro.
        self.cubo.posicionMovida.connect(self.controller.on_pixel_changed)
        self.cubo.pixelElegido.connect(self.controller.on_pixel_changed)
        self.cubo.longitudElegida.connect(self._banda_del_cubo)
        # El cubo ofrece los mismos cuatro modos que el mapa. Hace falta: con
        # un HDF-EOS5 abierto no hay capa en el mapa, asi que la herramienta
        # de mapa no tiene donde actuar y los modos parecen no hacer nada.
        self.cubo.transectoPedido.connect(self._linea_movida)
        self.cubo.areaElegida.connect(self.controller.on_area_selected)
        self.cubo.pixelesElegidos.connect(self._pixeles_elegidos)
        self.cubo.vistaCambiada.connect(self._vista_cambiada)
        self.boton_datos.clicked.connect(self.cubo.zoom_a_los_datos)
        self.boton_todo.clicked.connect(lambda: self.cubo.set_vista(None))
        self.boton_bandas_rgb.toggled.connect(self.panel_rgb.setVisible)
        self.accion_abrir_lib.triggered.connect(self._abrir_biblioteca)
        self.accion_guardar_lib.triggered.connect(self._guardar_biblioteca)
        self.accion_csv.triggered.connect(self._exportar_csv)
        self.combo_paleta.currentTextChanged.connect(self.cubo.set_paleta)
        self.boton_rgb.clicked.connect(self._volver_al_rgb)

        self.controller.curvasCambiadas.connect(self.grafico.set_curvas)
        self.controller.bibliotecaCambiada.connect(self._refrescar_lista)
        self.controller.pixelCambiado.connect(self._mostrar_pixel)
        self.controller.pixelCambiado.connect(self.cubo.set_posicion)
        self.controller.transectoCambiado.connect(self._mostrar_transecto)
        self.controller.composicionCambiada.connect(self._aplicar_composicion)
        self.controller.mensaje.connect(self._avisar)
        self.grafico.posicionCambiada.connect(self._mostrar_lectura)

        for clave, casilla in self.casillas_bandas.items():
            casilla.toggled.connect(
                lambda marcado, c=clave: self._bandas_cambiadas(**{c: marcado}))
        # editingFinished y no textChanged: aplicar en cada tecla recalcularia
        # la firma a media palabra, con rangos que el usuario no termino de
        # escribir.
        self.campo_rangos.editingFinished.connect(self._rangos_cambiados)
        self.boton_bandas.toggled.connect(self.panel_bandas.setVisible)
        self.controller.mascaraCambiada.connect(self._mostrar_mascara)

        QgsProject.instance().layersAdded.connect(self.recargar_capas)
        QgsProject.instance().layersRemoved.connect(self.recargar_capas)

    # -- capas --------------------------------------------------------------
    def recargar_capas(self, *_):
        """Relista las capas raster del proyecto sin perder la elegida."""
        if self._bloqueado:
            return
        self._bloqueado = True
        actual = self.combo_capa.currentData()
        self.combo_capa.clear()
        self.combo_capa.addItem("(ninguna)", None)
        for capa in QgsProject.instance().mapLayers().values():
            if isinstance(capa, QgsRasterLayer) and capa.isValid():
                self.combo_capa.addItem(capa.name(), capa.id())
        indice = self.combo_capa.findData(actual)
        self.combo_capa.setCurrentIndex(max(0, indice))
        self._bloqueado = False

    def _capa_elegida(self, *_):
        if self._bloqueado:
            return
        identificador = self.combo_capa.currentData()
        if not identificador:
            self.controller.close_cube()
            self.cubo.set_cube(None)
            self._habilitar(False)
            return
        capa = QgsProject.instance().mapLayer(identificador)
        if capa is None:
            return
        self._cargar_cubo(capa.source(), capa)

    def _abrir_archivo(self):
        ruta, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Abrir cubo hiperespectral", "", FILTRO_ARCHIVOS)
        if not ruta:
            return
        capa = QgsRasterLayer(ruta, os.path.splitext(
            os.path.basename(ruta))[0])
        if not capa.isValid():
            # QGIS no lo abre pero el nucleo tal vez si -un ENVI con cabecera
            # que GDAL rechaza, por ejemplo-. Se intenta igual y se avisa que
            # no habra imagen en el mapa.
            self._cargar_cubo(ruta, None)
            return
        QgsProject.instance().addMapLayer(capa)
        self.recargar_capas()
        indice = self.combo_capa.findData(capa.id())
        if indice >= 0:
            self.combo_capa.setCurrentIndex(indice)

    def es_hdf5_abierto(self):
        """True si el cubo abierto se esta leyendo del HDF-EOS5 directo."""
        cubo = self.controller.cube
        return cubo is not None and isinstance(cubo.source, Hdf5Source)

    def _extraer_a_envi(self):
        """Abre el algoritmo de extraccion con el archivo ya puesto.

        Se abre el dialogo de Processing en vez de extraer aca mismo, y no es
        pereza: ese dialogo ya trae la eleccion de salidas -cubo, IGM, capas
        auxiliares-, la barra de avance, la cancelacion y el registro. Ademas
        deja el algoritmo a un paso del modo por lotes, que es lo que hace
        falta cuando son treinta escenas y no una.
        """
        cubo = self.controller.cube
        if cubo is None:
            self._avisar("Primero abra una escena")
            return
        ruta = getattr(cubo.source, "ruta", None)
        if not self.es_hdf5_abierto() or not ruta:
            self._avisar("La extraccion a ENVI parte de un archivo HDF-EOS5")
            return
        try:
            import processing
            processing.execAlgorithmDialog(ALGORITMO_EXTRAER,
                                           {"ENTRADA": ruta})
        except Exception as exc:
            self._avisar("No se pudo abrir el algoritmo de extraccion: %s"
                         % exc)

    def _cargar_cubo(self, ruta, capa):
        try:
            cubo = HyperspectralCube.load(ruta)
        except CubeError as exc:
            self._avisar(str(exc))
            self.controller.close_cube()
            self._habilitar(False)
            return
        self._soltar_vinculo()
        self.controller.set_cube(cubo, capa, georreferencia_de(cubo, capa))
        self.cubo.set_cube(cubo, self.controller.composer)
        self.cubo.unidad = ("reflectancia" if cubo.scale or cubo.aplicar_escala
                            else "valor")
        self._volver_al_rgb()
        self._preparar_controles(cubo)
        self._habilitar(True)
        self._activar_herramienta()
        self.estado.setText(
            "%s - %d x %d pixeles, %d bandas, %.1f a %.1f %s"
            % (cubo.name, cubo.samples, cubo.lines, cubo.bands,
               cubo.wavelengths[0], cubo.wavelengths[-1],
               cubo.unidad_espectral))
        self.estado.setText(
            self.estado.text() + "\n" + self.controller.georref.describir())
        if capa is None:
            if self.es_hdf5_abierto():
                self.estado.setText(
                    self.estado.text() + "\nHDF-EOS5 abierto directamente. "
                    "QGIS no dibuja el contenedor en el mapa; el cubo y el "
                    "espectro si funcionan. Para verlo en el mapa, extraelo "
                    "a ENVI.")
            else:
                self.estado.setText(
                    self.estado.text() + "\nQGIS no pudo abrir esta capa: "
                    "no habra imagen en el mapa.")

    def _preparar_controles(self, cubo):
        """Ajusta los controles al cubo recien abierto."""
        self._bloqueado = True
        self.combo_preset.clear()
        for nombre in RGBComposer.presets_aplicables(cubo):
            self.combo_preset.addItem(nombre)
        for canal, (deslizador, numero, _) in self.controles_banda.items():
            deslizador.setMaximum(cubo.bands - 1)
            numero.setMaximum(cubo.bands - 1)
        self.grafico.set_unidad(cubo.unidad_espectral)
        self._bloqueado = False
        self._sincronizar_bandas()

    def _habilitar(self, activo):
        for w in (self.combo_preset, self.combo_realce, self.lista,
                  self.boton_guardar, self.boton_renombrar, self.boton_quitar,
                  self.combo_paleta, self.boton_rgb, self.boton_lib,
                  self.campo_rangos, self.boton_bandas,
                  self.boton_bandas_rgb, self.boton_datos, self.boton_todo):
            w.setEnabled(activo)
        for casilla in self.casillas_bandas.values():
            casilla.setEnabled(activo)
        # La casilla de la bbl depende del archivo, no del panel. Sin esta
        # linea _habilitar corre despues de _mostrar_mascara y vuelve a
        # encenderla sobre un cubo que no trae ninguna lista.
        mascara = self.controller.mask
        self.casillas_bandas["usar_bbl"].setEnabled(
            activo and mascara is not None and mascara.hay_bbl)
        # Extraer solo tiene sentido sobre un HDF-EOS5: sobre un ENVI ya
        # extraido el boton no haria nada util.
        self.boton_extraer.setEnabled(activo and self.es_hdf5_abierto())
        for deslizador, numero, _ in self.controles_banda.values():
            deslizador.setEnabled(activo)
            numero.setEnabled(activo)
        self.panel_cubo.habilitar(activo)
        # Vincular necesita ademas saber donde esta la escena; sin eso el
        # boton se queda apagado y su ayuda explica por que.
        se_puede = activo and self.controller.georref.tiene_mapa
        self.panel_cubo.boton_vinculo.setEnabled(se_puede)

    # -- herramienta de mapa ------------------------------------------------
    def _enviar_a_qgis(self):
        """Manda al mapa solo el RGB visible, no el cubo.

        Cargar el cubo entero como capa para poder trabajar en QGIS es caro y
        casi siempre inutil: son cientos de bandas de las que el mapa dibuja
        tres.
        """
        cubo = self.controller.cube
        if cubo is None or cubo.cerrado:
            self._avisar("Primero abra una escena")
            return
        georref = self.controller.georref
        try:
            ruta, nombre = enviar_vista(
                cubo, self.controller.composer, self.cubo.ventana(), georref)
        except (ErrorExportar, OSError) as exc:
            self._avisar("No se pudo escribir la vista: %s" % exc)
            return
        capa = QgsRasterLayer(ruta, nombre)
        if not capa.isValid():
            self._avisar("QGIS no pudo abrir la imagen escrita en %s" % ruta)
            return
        QgsProject.instance().addMapLayer(capa)
        self._avisar("Vista enviada al mapa: %s\n%s"
                     % (nombre, _aviso_de_georreferencia(georref)))

    def _activar_herramienta(self):
        if self.herramienta is None:
            self.herramienta = map_tools.HerramientaExplorar(
                self.canvas, self.controller)
            self.herramienta.pixelElegido.connect(
                self.controller.on_pixel_changed)
            self.herramienta.lineaMovida.connect(self._linea_movida)
            self.herramienta.areaElegida.connect(
                self.controller.on_area_selected)
            self.herramienta.pixelesElegidos.connect(self._pixeles_elegidos)
            self.herramienta.fueraDeLaImagen.connect(
                lambda: self.lectura.setText("fuera de la imagen"))
        self.canvas.setMapTool(self.herramienta)
        self.herramienta.set_modo(self._modo_actual())

    def _modo_actual(self):
        return self.panel_cubo.herramienta()

    def _cambiar_modo(self, clave):
        self.panel_cubo.set_herramienta(clave)
        self.cubo.set_modo(clave)
        if self.herramienta is None:
            return
        # Desplazar y acercar son de la ventana del cubo: sobre el mapa de
        # QGIS esos gestos ya los da QGIS, y pisarselos con la herramienta
        # del plugin seria peor. Ahi se queda en el ultimo modo de muestreo.
        if clave not in MODOS_NAVEGACION:
            self.herramienta.set_modo(clave)

    def _pixeles_elegidos(self, coords):
        """Llego un conjunto de pixeles sueltos desde el cubo."""
        if not coords:
            return
        firma = self.controller.on_pixels_selected(coords)
        if firma is not None:
            self.estado.setText(
                "%d pixeles elegidos - la firma es su promedio, y la "
                "envolvente su variabilidad" % len(coords))

    def _vista_cambiada(self, vista):
        if vista is None:
            self.estado.setText("Vista completa")
            return
        x0, y0, x1, y1 = vista
        self.estado.setText(
            "Acercado a X %d-%d, Y %d-%d (%d x %d pixeles). El realce y la "
            "escala de color se recalcularon sobre esta zona."
            % (x0, x1, y0, y1, x1 - x0 + 1, y1 - y0 + 1))

    def _linea_movida(self, eje, posicion):
        if eje == map_tools.MODO_X:
            self.controller.on_x_changed(posicion)
        else:
            self.controller.on_y_changed(posicion)

    # -- composicion --------------------------------------------------------
    def _preset_elegido(self, *_):
        nombre = self.combo_preset.currentText()
        if nombre:
            self.controller.on_preset_selected(nombre)
            self._sincronizar_bandas()

    def _realce_elegido(self, *_):
        modo = self.combo_realce.currentData()
        self.controller.on_stretch_changed(modo)
        self.cubo.set_modo_realce(modo)

    def _banda_cambiada(self, canal, indice):
        """Un deslizador o su casilla se movieron.

        Los dos controles apuntan a lo mismo, asi que cada uno mueve al otro.
        Sin el cerrojo, esa ida y vuelta es un bucle infinito.
        """
        if self._bloqueado or self.controller.cube is None:
            return
        self._bloqueado = True
        deslizador, numero, _ = self.controles_banda[canal]
        deslizador.setValue(indice)
        numero.setValue(indice)
        self._bloqueado = False
        longitud = float(self.controller.cube.wavelengths[indice])
        self.controller.on_rgb_changed(**{canal: longitud})
        self._sincronizar_bandas()

    def _sincronizar_bandas(self):
        """Pone los controles en la banda que el compositor esta usando."""
        cubo = self.controller.cube
        if cubo is None:
            return
        self._bloqueado = True
        indices = self.controller.composer.bands_of(cubo)
        for canal, indice in zip(("red", "green", "blue"), indices):
            deslizador, numero, leyenda = self.controles_banda[canal]
            deslizador.setValue(indice)
            numero.setValue(indice)
            leyenda.setText("%.1f %s" % (cubo.wavelengths[indice],
                                         cubo.unidad_espectral))
        self._bloqueado = False
        self.resumen_rgb.setText("%.0f/%.0f/%.0f %s" % (
            cubo.wavelengths[indices[0]], cubo.wavelengths[indices[1]],
            cubo.wavelengths[indices[2]], cubo.unidad_espectral))
        self.grafico.set_marcadores_rgb(self.controller.marcadores_rgb())

    def _aplicar_composicion(self, composer):
        cubo = self.controller.cube
        # Esta senal llega tambien cuando el cubo se acaba de cerrar -al
        # cambiar de capa o al vaciar la seleccion-, y entonces no hay nada
        # que recomponer. Preguntar es mas barato que coordinar el orden
        # exacto en que se enteran las cinco vistas.
        if cubo is None or cubo.cerrado:
            self.cubo.refrescar_frontal()
            return
        self.cubo.refrescar_frontal()
        self.cubo.set_marcadores_rgb(self.controller.marcadores_rgb())
        if self.controller.layer is None:
            return
        aplicar_composicion(self.controller.layer, cubo, composer)

    def _banda_del_cubo(self, longitud):
        """Se eligio una banda haciendo clic en un costado del cubo."""
        cubo = self.controller.cube
        if cubo is None:
            return
        indice = cubo.band_index(longitud)
        self.banda_frontal.setText(
            "frente: banda %d (%.1f %s)"
            % (indice, cubo.wavelengths[indice], cubo.unidad_espectral))

    def _volver_al_rgb(self):
        self.cubo.set_banda_unica(None)
        self.banda_frontal.setText("frente: composicion RGB")

    # -- lecturas -----------------------------------------------------------
    def _mostrar_pixel(self, x, y):
        cubo = self.controller.cube
        texto = "Pixel seleccionado:  X %d  |  Y %d" % (x, y)
        comparacion = self.controller.compare_current()
        if comparacion is not None:
            texto += "   -   se parece a '%s' (%.1f grados)" % comparacion
        if cubo is not None and self.controller.layer is not None:
            mx, my = self.controller.geo.to_map(x, y)
            texto += "\n%.3f, %.3f  (%s)" % (
                mx, my, self.controller.layer.crs().authid() or "sin SRC")
        self.estado.setText(texto)

    def _mostrar_transecto(self, eje, posicion):
        cubo = self.controller.cube
        total = cubo.lines if eje == "x" else cubo.samples
        self.estado.setText(
            "Transecto %s = %d  -  %d pixeles resumidos (media, minimo y "
            "maximo)" % (eje.upper(), posicion, total))

    def _bandas_cambiadas(self, **cambios):
        if self._bloqueado:
            return
        self.controller.on_mask_changed(**cambios)

    def _rangos_cambiados(self):
        if self._bloqueado:
            return
        self.controller.on_mask_changed(
            rangos=parsear_rangos(self.campo_rangos.text()))

    def _mostrar_mascara(self, mascara):
        """Pone los controles y el grafico al dia con la mascara vigente."""
        self._bloqueado = True
        for clave, casilla in self.casillas_bandas.items():
            casilla.setChecked(bool(getattr(mascara, clave)))
        # La casilla de la bbl no tiene sentido si el archivo no la trae.
        self.casillas_bandas["usar_bbl"].setEnabled(mascara.hay_bbl)
        if not mascara.hay_bbl:
            self.casillas_bandas["usar_bbl"].setToolTip(
                "Este archivo no trae lista de bandas malas")
        texto = formatear_rangos(mascara.rangos)
        if texto != self.campo_rangos.text():
            self.campo_rangos.setText(texto)
        self._bloqueado = False
        self.cuenta_bandas.setText(mascara.describir())
        self.grafico.set_descartados(mascara.tramos_malos())

    def _mostrar_lectura(self, longitud):
        cubo = self.controller.cube
        if cubo is None:
            return
        indice = cubo.band_index(longitud)
        self.lectura.setText("banda %d  -  %.1f %s"
                             % (indice, cubo.wavelengths[indice],
                                cubo.unidad_espectral))

    def _avisar(self, texto):
        self.estado.setText(texto)
        barra = getattr(self.iface, "messageBar", None)
        if barra is not None:
            barra().pushInfo("Hyperspectral Explorer", texto)

    # -- firmas -------------------------------------------------------------
    def _guardar_firma(self):
        if self.controller.firma_actual is None:
            self._avisar("Primero haga clic en un pixel o dibuje un area")
            return
        sugerido = self.controller.firma_actual.name
        nombre, aceptado = QtWidgets.QInputDialog.getText(
            self, "Guardar firma", "Nombre:",
            enum(QtWidgets.QLineEdit, "EchoMode", "Normal"), sugerido)
        if aceptado and nombre.strip():
            self.controller.save_current(nombre.strip())

    def _seleccionada(self):
        item = self.lista.currentItem()
        return None if item is None else item.text()

    def _renombrar_firma(self):
        actual = self._seleccionada()
        if actual is None:
            return
        nombre, aceptado = QtWidgets.QInputDialog.getText(
            self, "Renombrar firma", "Nuevo nombre:",
            enum(QtWidgets.QLineEdit, "EchoMode", "Normal"), actual)
        if aceptado:
            self.controller.rename_signature(actual, nombre.strip())

    def _quitar_firma(self):
        actual = self._seleccionada()
        if actual is not None:
            self.controller.remove_signature(actual)

    def _visibilidad_cambiada(self, item):
        if self._bloqueado:
            return
        self.controller.set_signature_visible(
            item.text(), item.checkState() == _MARCADO)

    def _refrescar_lista(self):
        self._bloqueado = True
        seleccion = self._seleccionada()
        self.lista.clear()
        for firma in self.controller.library:
            item = QtWidgets.QListWidgetItem(firma.name)
            item.setFlags(
                item.flags() | enum(Qt, "ItemFlag",
                                    "ItemIsUserCheckable"))
            item.setCheckState(_MARCADO if firma.visible else _SIN_MARCAR)
            if firma.color:
                # La fila se pinta del color de su curva: es como el usuario
                # relaciona la lista con el grafico sin leer la leyenda.
                item.setForeground(QtGui.QBrush(QtGui.QColor(firma.color)))
            detalle = [firma.source, firma.created]
            if firma.is_area:
                detalle.append("%d px" % firma.count)
            if firma.notes:
                detalle.append(firma.notes)
            item.setToolTip("\n".join(d for d in detalle if d))
            self.lista.addItem(item)
            if firma.name == seleccion:
                self.lista.setCurrentItem(item)
        self._bloqueado = False

    # -- biblioteca en disco ------------------------------------------------
    def _abrir_biblioteca(self):
        ruta, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Abrir biblioteca espectral", "",
            "Biblioteca (*.json);;Todos los archivos (*)")
        if not ruta:
            return
        try:
            self.controller.library = SpectralLibrary.load(ruta)
        except LibraryError as exc:
            self._avisar(str(exc))
            return
        self.controller.bibliotecaCambiada.emit()
        self.controller._emitir_curvas()

    def _guardar_biblioteca(self):
        if not len(self.controller.library):
            self._avisar("No hay firmas para guardar")
            return
        ruta, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Guardar biblioteca espectral",
            self.controller.library.path or "biblioteca.json",
            "Biblioteca (*.json)")
        if not ruta:
            return
        try:
            self.controller.library.save(ruta)
        except (LibraryError, OSError) as exc:
            self._avisar(str(exc))
            return
        self._avisar("Biblioteca guardada en %s" % ruta)

    def _exportar_csv(self):
        ruta, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Exportar firmas a CSV", "firmas.csv", "CSV (*.csv)")
        if not ruta:
            return
        try:
            forma = self.controller.library.to_csv(ruta)
        except (LibraryError, OSError) as exc:
            self._avisar(str(exc))
            return
        self._avisar("Exportado en forma %s: %s" % (forma, ruta))

    # -- cierre -------------------------------------------------------------
    def closeEvent(self, evento):
        """Cerrar el panel lo esconde; no termina la sesion.

        La X de un panel acoplado de QGIS lo oculta, y el complemento sigue
        cargado. Aqui se cerraba ademas la escena y se soltaban las senales
        del proyecto, asi que al volver a abrirlo el usuario encontraba el
        panel vacio: habia perdido el trabajo por pulsar una X que en ningun
        otro sitio de QGIS significa eso.

        Lo que si se suelta es lo que no tiene sentido con el panel oculto:
        el vinculo con el lienzo y la herramienta de mapa, que si no seguiria
        capturando los clics del usuario sobre un panel que no ve. Las dos
        vuelven solas al mostrarlo.

        El desmontaje de verdad esta en ``apagar()``, que corre cuando el
        complemento se descarga, que es cuando de verdad se termina.
        """
        self._soltar_vinculo()
        # Un restablecimiento pendiente vuelve a mostrarlo todo sobre un
        # panel que el usuario acaba de cerrar: mostrar y cerrar en el mismo
        # giro del bucle es exactamente lo que pasa al descargar el
        # complemento con el panel recien abierto.
        self._al_mostrar.stop()
        if self._cubo_suelto and self.ventana_suelta is not None:
            # Esconderla, no cerrarla. Cerrarla dispararia el reempotrado, y
            # eso es reacomodar el arbol de widgets justo mientras Qt lo
            # esta escondiendo. Ademas se perderia el arreglo de dos
            # ventanas que el usuario eligio; escondida vuelve tal cual.
            self.ventana_suelta.hide()
        self._soltar_herramienta()
        super(HyperspectralDock, self).closeEvent(evento)

    def showEvent(self, evento):
        """Al volver a mostrarlo, todo lo suyo vuelve con el -un giro despues.

        Nada de trabajo aqui dentro. Este metodo corre en mitad de la
        animacion de acople de QGIS: ``QMainWindowLayout`` la da por
        terminada y ahi mismo muestra el panel y, uno a uno, sus hijos.
        Tocar el lienzo -o el arbol de widgets- en ese punto es reentrar en
        lo que Qt esta reacomodando, y de ahi salio un cuelgue en macOS.
        Aplazarlo un giro del bucle no le cuesta nada al usuario y saca todo
        lo nuestro de esa pila.
        """
        super(HyperspectralDock, self).showEvent(evento)
        self._al_mostrar.start(0)

    def _restablecer(self):
        """Lo que el panel recupera al volver a la vista."""
        if not self.isVisible():
            return
        if self._cubo_suelto:
            self.ventana_suelta.show()
        if self.controller.cube is not None:
            self._activar_herramienta()

    def apagar(self):
        """El desmontaje de verdad: el complemento se esta descargando.

        Separado de ``closeEvent`` a proposito. Son dos cosas distintas que
        antes estaban en la misma: esconder un panel y terminar una sesion.
        """
        # Primero los aplazados: si no, un reempotrado o un restablecimiento
        # pendiente se despierta sobre un panel a medio desmontar.
        self._aplazado.stop()
        self._al_mostrar.stop()
        self._soltar_vinculo()
        self._desconectar_proyecto()
        self.controller.close_cube()
        self._soltar_herramienta()
        self._recoger_la_ventana_suelta()

    def _recoger_la_ventana_suelta(self):
        """El cubo vuelve al panel y la ventana de al lado se va con el.

        La ventana suelta no es hija del panel -cuelga de la ventana
        principal de QGIS-, asi que sin esto sobrevive a la descarga del
        complemento y queda flotando encima, con un cubo ya cerrado dentro.

        Se puede llamar dos veces sin miedo: ``apagar`` no es un paso de un
        guion sino una promesa -esto queda desmontado-, y quien la pide dos
        veces no tiene por que saber si ya estaba cumplida.
        """
        if self.ventana_suelta is None:
            return
        self.panel_cubo.boton_soltar.setChecked(False)
        self._soltar_cubo(False)
        ventana, self.ventana_suelta = self.ventana_suelta, None
        ventana.close()
        ventana.deleteLater()

    def _soltar_herramienta(self):
        if self.herramienta is not None:
            self.canvas.unsetMapTool(self.herramienta)

    def _desconectar_proyecto(self):
        """Suelta las senales del proyecto.

        Sin esto, cerrar el panel deja dos conexiones vivas hacia un objeto
        que ya no esta, y la proxima capa que se agregue al proyecto tumba
        QGIS.
        """
        for senal in (QgsProject.instance().layersAdded,
                      QgsProject.instance().layersRemoved):
            try:
                senal.disconnect(self.recargar_capas)
            except (TypeError, RuntimeError):
                pass
