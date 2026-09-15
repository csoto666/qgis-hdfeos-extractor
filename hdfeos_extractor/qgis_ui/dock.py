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
from ..core.geo import GeoError, GeoTransform
from ..core.hdf5 import Hdf5Source
from ..core.library import LibraryError, SpectralLibrary
from ..core.bandas import formatear_rangos, parsear_rangos
from ..core.colormap import nombres as paletas
from ..core.rgb import MODOS, RGBComposer
from ..vista.cube_view import CubeView
from ..vista.qt import QtGui, QtWidgets, Qt
from ..vista.spectral_plot import SpectralPlot
from . import map_tools
from .controller import SpatialSpectralController
from .render import aplicar_composicion

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


TITULO = "Hyperspectral Explorer"


class HyperspectralDock(QtWidgets.QDockWidget):
    """Panel principal del explorador."""

    def __init__(self, iface, parent=None):
        super(HyperspectralDock, self).__init__(TITULO, parent)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.controller = SpatialSpectralController(self)
        self.herramienta = None
        self._bloqueado = False        # corta los bucles de senales

        self.setObjectName("HyperspectralExplorerDock")
        self.setWidget(self._construir())
        self._conectar()
        self.recargar_capas()
        self._habilitar(False)

    # -- construccion -------------------------------------------------------
    def _construir(self):
        contenedor = QtWidgets.QWidget()
        caja = QtWidgets.QVBoxLayout(contenedor)
        caja.setContentsMargins(6, 6, 6, 6)
        caja.setSpacing(6)
        caja.addWidget(self._bloque_escena())

        caja.addWidget(self._bloque_rgb())

        # Solo las dos vistas entran al divisor. Los bloques de control piden
        # un alto minimo que no se puede negociar, y metidos en el divisor se
        # lo quitan justamente a lo que hay que mirar: con cuatro bloques
        # adentro, el grafico terminaba en una franja de cien pixeles.
        # El cubo y el perfil van apilados y no en pestanas porque el sentido
        # de todo esto es verlos a la vez.
        divisor = QtWidgets.QSplitter(Qt.Vertical)
        divisor.addWidget(self._bloque_cubo())
        divisor.addWidget(self._bloque_grafico())
        divisor.setStretchFactor(0, 3)
        divisor.setStretchFactor(1, 2)
        self._divisor = divisor
        self._usuario_ajusto = False
        divisor.splitterMoved.connect(self._divisor_arrastrado)
        caja.addWidget(divisor, 1)
        caja.addWidget(self._bloque_firmas())

        self.estado = QtWidgets.QLabel("Elija una capa raster hiperespectral")
        self.estado.setWordWrap(True)
        caja.addWidget(self.estado)
        return contenedor

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
        columna.addLayout(self._fila_modo())
        return grupo

    def _fila_capa(self):
        rejilla = QtWidgets.QHBoxLayout()
        self.combo_capa = QtWidgets.QComboBox()
        self.combo_capa.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                      QtWidgets.QSizePolicy.Preferred)
        self.boton_abrir = QtWidgets.QPushButton("Abrir...")
        self.boton_abrir.setToolTip(
            "Abre un cubo desde el disco: HDF-EOS5 directamente, o un ENVI "
            "ya extraido")
        self.boton_extraer = QtWidgets.QPushButton("Extraer a ENVI...")
        self.boton_extraer.setToolTip(
            "Escribe la escena HDF-EOS5 abierta en formato nativo de ENVI, "
            "para llevarla a otro programa")
        self.boton_extraer.setEnabled(False)
        rejilla.addWidget(QtWidgets.QLabel("Capa:"))
        rejilla.addWidget(self.combo_capa, 1)
        rejilla.addWidget(self.boton_abrir)
        rejilla.addWidget(self.boton_extraer)
        return rejilla

    def _fila_modo(self):
        fila = QtWidgets.QHBoxLayout()
        fila.addWidget(QtWidgets.QLabel("Navegacion:"))
        self.modos = {}
        for clave, texto, ayuda in (
                (map_tools.MODO_PIXEL, "Pixel",
                 "Un clic extrae el espectro de ese pixel"),
                (map_tools.MODO_X, "Linea X",
                 "Recorre columnas: fija x y resume toda la columna"),
                (map_tools.MODO_Y, "Linea Y",
                 "Recorre filas: fija y y resume toda la fila"),
                (map_tools.MODO_AREA, "Area",
                 "Arrastra un rectangulo y promedia su espectro")):
            boton = QtWidgets.QRadioButton(texto)
            boton.setToolTip(ayuda)
            fila.addWidget(boton)
            self.modos[clave] = boton
        self.modos[map_tools.MODO_PIXEL].setChecked(True)
        fila.addStretch(1)
        return fila

    def _bloque_rgb(self):
        grupo = QtWidgets.QGroupBox("Composicion RGB")
        rejilla = QtWidgets.QGridLayout(grupo)
        rejilla.setVerticalSpacing(3)

        fila = QtWidgets.QHBoxLayout()
        fila.addWidget(QtWidgets.QLabel("Preset:"))
        self.combo_preset = QtWidgets.QComboBox()
        self.combo_preset.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                        QtWidgets.QSizePolicy.Preferred)
        fila.addWidget(self.combo_preset, 1)
        fila.addWidget(QtWidgets.QLabel("Realce:"))
        self.combo_realce = QtWidgets.QComboBox()
        for modo in MODOS:
            self.combo_realce.addItem(ETIQUETAS_REALCE.get(modo, modo), modo)
        fila.addWidget(self.combo_realce, 1)
        rejilla.addLayout(fila, 0, 0, 1, 4)

        self.controles_banda = {}
        for fila, (canal, etiqueta) in enumerate(
                (("red", "R"), ("green", "G"), ("blue", "B")), start=1):
            deslizador = QtWidgets.QSlider(Qt.Horizontal)
            deslizador.setMinimum(0)
            numero = QtWidgets.QSpinBox()
            numero.setMinimum(0)
            numero.setToolTip("Numero de banda")
            leyenda = QtWidgets.QLabel("-")
            leyenda.setMinimumWidth(74)
            leyenda.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            rejilla.addWidget(QtWidgets.QLabel(etiqueta), fila, 0)
            rejilla.addWidget(deslizador, fila, 1)
            rejilla.addWidget(numero, fila, 2)
            rejilla.addWidget(leyenda, fila, 3)
            self.controles_banda[canal] = (deslizador, numero, leyenda)

        rejilla.setColumnStretch(1, 1)
        return grupo

    def _bloque_cubo(self):
        grupo = QtWidgets.QGroupBox("Cubo hiperespectral")
        caja = QtWidgets.QVBoxLayout(grupo)
        caja.setContentsMargins(3, 3, 3, 3)
        self.cubo = CubeView()
        self.cubo.setToolTip(
            "Arrastre sobre la imagen para recorrer el cubo.\n"
            "Clic en un costado: esa banda pasa al frente.\n"
            "Doble clic en el frente: vuelve a la composicion RGB.")
        caja.addWidget(self.cubo, 1)

        fila = QtWidgets.QHBoxLayout()
        fila.addWidget(QtWidgets.QLabel("Paleta:"))
        self.combo_paleta = QtWidgets.QComboBox()
        for nombre in paletas():
            self.combo_paleta.addItem(nombre)
        fila.addWidget(self.combo_paleta)
        self.boton_rgb = QtWidgets.QPushButton("Volver al RGB")
        self.boton_rgb.setToolTip(
            "Deja de mostrar una sola banda en la cara frontal")
        fila.addWidget(self.boton_rgb)
        fila.addStretch(1)
        self.banda_frontal = QtWidgets.QLabel("frente: composicion RGB")
        fila.addWidget(self.banda_frontal)
        caja.addLayout(fila)
        return grupo

    def _bloque_grafico(self):
        grupo = QtWidgets.QGroupBox("Perfil espectral")
        caja = QtWidgets.QVBoxLayout(grupo)
        caja.setContentsMargins(3, 3, 3, 3)
        self.grafico = SpectralPlot()
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
        fila.addWidget(self.cuenta_bandas)
        fila.addStretch(1)
        self.lectura = QtWidgets.QLabel(" ")
        self.lectura.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fila.addWidget(self.lectura)
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

    def _bloque_firmas(self):
        grupo = QtWidgets.QGroupBox("Firmas guardadas")
        # Preferred/Maximum y no el Expanding que traen los grupos: sin esto
        # se queda con el alto sobrante en vez de cederselo al divisor, que
        # es donde estan las dos vistas.
        grupo.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                            QtWidgets.QSizePolicy.Maximum)
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

        fila = QtWidgets.QHBoxLayout()
        self.boton_guardar = QtWidgets.QPushButton("Guardar")
        self.boton_guardar.setToolTip("Guarda la firma que se esta viendo")
        self.boton_renombrar = QtWidgets.QPushButton("Renombrar")
        self.boton_quitar = QtWidgets.QPushButton("Quitar")
        for b in (self.boton_guardar, self.boton_renombrar, self.boton_quitar):
            fila.addWidget(b)
        caja.addLayout(fila)

        fila2 = QtWidgets.QHBoxLayout()
        self.boton_abrir_lib = QtWidgets.QPushButton("Abrir biblioteca")
        self.boton_guardar_lib = QtWidgets.QPushButton("Guardar biblioteca")
        self.boton_csv = QtWidgets.QPushButton("Exportar CSV")
        for b in (self.boton_abrir_lib, self.boton_guardar_lib,
                  self.boton_csv):
            fila2.addWidget(b)
        caja.addLayout(fila2)
        return grupo

    # -- conexiones ---------------------------------------------------------
    def _conectar(self):
        self.combo_capa.currentIndexChanged.connect(self._capa_elegida)
        self.boton_abrir.clicked.connect(self._abrir_archivo)
        self.boton_extraer.clicked.connect(self._extraer_a_envi)
        for clave, boton in self.modos.items():
            boton.toggled.connect(
                lambda marcado, c=clave: marcado and self._cambiar_modo(c))

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
        self.boton_abrir_lib.clicked.connect(self._abrir_biblioteca)
        self.boton_guardar_lib.clicked.connect(self._guardar_biblioteca)
        self.boton_csv.clicked.connect(self._exportar_csv)
        self.lista.itemChanged.connect(self._visibilidad_cambiada)

        # El cubo y el mapa son dos maneras de senalar el mismo pixel, asi
        # que los dos entran por el controlador y los dos escuchan su
        # respuesta. Mover la cruz del cubo mueve el resaltado del mapa, y al
        # reves, sin que ninguno de los dos conozca al otro.
        self.cubo.posicionMovida.connect(self.controller.on_pixel_changed)
        self.cubo.pixelElegido.connect(self.controller.on_pixel_changed)
        self.cubo.longitudElegida.connect(self._banda_del_cubo)
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
        try:
            geo = (GeoTransform.from_layer(capa) if capa is not None
                   else GeoTransform.identidad())
        except GeoError:
            geo = GeoTransform.identidad()
        self.controller.set_cube(cubo, capa, geo)
        self.cubo.set_cube(cubo, self.controller.composer)
        self._volver_al_rgb()
        self._preparar_controles(cubo)
        self._habilitar(True)
        self._activar_herramienta()
        self.estado.setText(
            "%s - %d x %d pixeles, %d bandas, %.1f a %.1f %s"
            % (cubo.name, cubo.samples, cubo.lines, cubo.bands,
               cubo.wavelengths[0], cubo.wavelengths[-1],
               cubo.unidad_espectral))
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
                  self.boton_csv, self.boton_guardar_lib,
                  self.combo_paleta, self.boton_rgb,
                  self.campo_rangos, self.boton_bandas):
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
        for boton in self.modos.values():
            boton.setEnabled(activo)

    # -- herramienta de mapa ------------------------------------------------
    def _activar_herramienta(self):
        if self.herramienta is None:
            self.herramienta = map_tools.HerramientaExplorar(
                self.canvas, self.controller)
            self.herramienta.pixelElegido.connect(
                self.controller.on_pixel_changed)
            self.herramienta.lineaMovida.connect(self._linea_movida)
            self.herramienta.areaElegida.connect(
                self.controller.on_area_selected)
            self.herramienta.fueraDeLaImagen.connect(
                lambda: self.lectura.setText("fuera de la imagen"))
        self.canvas.setMapTool(self.herramienta)
        self.herramienta.set_modo(self._modo_actual())

    def _modo_actual(self):
        for clave, boton in self.modos.items():
            if boton.isChecked():
                return clave
        return map_tools.MODO_PIXEL

    def _cambiar_modo(self, clave):
        if self.herramienta is not None:
            self.herramienta.set_modo(clave)

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
        self.grafico.set_marcadores_rgb(self.controller.marcadores_rgb())

    def _aplicar_composicion(self, composer):
        self.cubo.refrescar_frontal()
        self.cubo.set_marcadores_rgb(self.controller.marcadores_rgb())
        if self.controller.cube is None or self.controller.layer is None:
            return
        aplicar_composicion(self.controller.layer, self.controller.cube,
                            composer)

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
            QtWidgets.QLineEdit.Normal, sugerido)
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
            QtWidgets.QLineEdit.Normal, actual)
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
            item.text(), item.checkState() == Qt.Checked)

    def _refrescar_lista(self):
        self._bloqueado = True
        seleccion = self._seleccionada()
        self.lista.clear()
        for firma in self.controller.library:
            item = QtWidgets.QListWidgetItem(firma.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if firma.visible else Qt.Unchecked)
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

    # -- disposicion --------------------------------------------------------
    #: Reparto vertical entre el cubo y el perfil espectral.
    REPARTO = (0.56, 0.44)

    def _divisor_arrastrado(self, *_):
        """El usuario movio el divisor: desde aca manda el."""
        self._usuario_ajusto = True

    def _repartir(self):
        """Reparte el alto del divisor entre el cubo y el perfil.

        Se rehace en cada cambio de tamano, no una sola vez al mostrarse: en
        el primer showEvent la geometria todavia no esta asentada y el reparto
        sale contra un alto que no es el final -que es como el perfil termina
        en una franja de cien pixeles-. Deja de rehacerse en cuanto el usuario
        arrastra el divisor, porque a partir de ahi la proporcion la eligio
        el.
        """
        if self._usuario_ajusto:
            return
        alto = self._divisor.height()
        if alto <= 0:
            return
        tamanos = [int(alto * f) for f in self.REPARTO]
        if self._divisor.sizes() != tamanos:
            self._divisor.setSizes(tamanos)

    def showEvent(self, evento):
        super(HyperspectralDock, self).showEvent(evento)
        self._repartir()

    def resizeEvent(self, evento):
        super(HyperspectralDock, self).resizeEvent(evento)
        self._repartir()

    # -- cierre -------------------------------------------------------------
    def closeEvent(self, evento):
        self._desconectar_proyecto()
        self.controller.close_cube()
        if self.herramienta is not None:
            self.canvas.unsetMapTool(self.herramienta)
        super(HyperspectralDock, self).closeEvent(evento)

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
