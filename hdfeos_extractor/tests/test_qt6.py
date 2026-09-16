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
"""Compatibilidad con Qt6: que no vuelva a colarse un enum sin calificar.

Qt6 metio los enums dentro de su propia clase y quito la forma plana. QGIS
hizo lo mismo con los suyos. Un ``Qt.Horizontal`` suelto no falla al
importar ni al ejecutar las pruebas -aqui hay PyQt5- : falla en la maquina
del usuario, al abrir el panel, con un AttributeError a media construccion
de la interfaz.

Por eso la comprobacion es sobre el codigo y no sobre su ejecucion. Se lee
el arbol sintactico y se busca el patron ``Clase.MIEMBRO`` donde deberia
haber ``Clase.Grupo.MIEMBRO``. Es la misma idea que usa el verificador del
repositorio de complementos, con dos diferencias: corre aqui, antes de
publicar, y mira tambien los enums de PyQt, que aquel no revisa y que rompen
igual.
"""

import ast
import os

import pytest

#: Modulos que solo son el camino hasta la clase: ``QtWidgets.QSizePolicy``
#: es la clase QSizePolicy, no un enum de un modulo.
MODULOS = ("QtWidgets", "QtGui", "QtCore", "qgis", "PyQt5", "PyQt6")

#: Nombres que empiezan en mayuscula y no son miembros de enum. Sin esta
#: lista, construir una clase -``QtWidgets.QWidget()``- o nombrar una
#: excepcion darian falsos positivos.
NO_SON_ENUM = frozenset([
    "Signal", "Slot", "Property", "Error", "Exception", "Warning",
])


def raiz_del_paquete():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fuentes():
    """Los .py del complemento, sin las pruebas ni los dobles."""
    base = raiz_del_paquete()
    for carpeta, subs, ficheros in os.walk(base):
        subs[:] = [d for d in subs if d not in ("tests", "__pycache__")]
        for fichero in sorted(ficheros):
            if fichero.endswith(".py"):
                yield os.path.join(carpeta, fichero)


def _ruta_punteada(nodo):
    """``QtWidgets.QSizePolicy.Expanding`` -> ['QtWidgets', ...]. None si no
    es una cadena de nombres."""
    partes = []
    while isinstance(nodo, ast.Attribute):
        partes.append(nodo.attr)
        nodo = nodo.value
    if not isinstance(nodo, ast.Name):
        return None
    partes.append(nodo.id)
    return list(reversed(partes))


def enums_sin_calificar(ruta):
    """Devuelve [(linea, expresion)] de los accesos que romperian en Qt6.

    Solo se mira el extremo de cada cadena de atributos. Con la forma
    calificada, ``Qt.Orientation.Horizontal``, el extremo tiene tres partes
    y no se marca; el ``Qt.Orientation`` de en medio no se examina por su
    cuenta, que si la tendria dos y pareceria un enum plano.
    """
    with open(ruta, encoding="utf-8") as f:
        arbol = ast.parse(f.read(), ruta)

    intermedios = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Attribute):
            intermedios.add(id(nodo.value))

    hallazgos = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Attribute) or id(nodo) in intermedios:
            continue
        partes = _ruta_punteada(nodo)
        if not partes:
            continue
        while partes and partes[0] in MODULOS:
            partes.pop(0)
        if len(partes) != 2:
            continue
        clase, miembro = partes
        if miembro in NO_SON_ENUM or not miembro[:1].isupper():
            continue
        # Qt es el espacio de nombres; lo demas, clases de Qt o de QGIS.
        if clase != "Qt" and not clase.startswith("Q"):
            continue
        hallazgos.append((nodo.lineno, ".".join(partes)))
    return hallazgos


def test_no_hay_enums_sin_calificar():
    """El contrato: en todo el complemento, ni uno.

    Si esta prueba falla, el arreglo no es una excepcion en la lista: es
    envolver el acceso en ``enum(clase, "Grupo", "Miembro")``, que resuelve
    la forma calificada primero y deja la plana de respaldo para Qt5.
    """
    culpables = []
    for ruta in fuentes():
        for linea, expresion in enums_sin_calificar(ruta):
            culpables.append("%s:%d  %s"
                             % (os.path.basename(ruta), linea, expresion))
    detalle = "\n  ".join(culpables)
    assert not culpables, (
        "Enums sin calificar, que en Qt6 no existen:\n  " + detalle)


def test_el_detector_reconoce_las_dos_formas(tmp_path):
    """Una prueba que no distinga plano de calificado no prueba nada."""
    fichero = tmp_path / "ejemplo.py"
    fichero.write_text(
        "from qgis.PyQt.QtCore import Qt\n"
        "from qgis.PyQt import QtWidgets\n"
        "plano = Qt.Horizontal\n"
        "calificado = Qt.Orientation.Horizontal\n"
        "plano_de_clase = QtWidgets.QSizePolicy.Expanding\n"
        "calificado_de_clase = QtWidgets.QSizePolicy.Policy.Expanding\n"
        "metodo = QtWidgets.QApplication.instance()\n"
        "construir = QtWidgets.QWidget()\n",
        encoding="utf-8")
    hallados = {expresion for _l, expresion in enums_sin_calificar(fichero)}
    assert hallados == {"Qt.Horizontal", "QSizePolicy.Expanding"}


def test_el_resolutor_prueba_calificado_antes_que_plano():
    """El orden no es indiferente: en Qt6 solo existe el calificado."""
    from hdfeos_extractor.compat import enum

    class Calificado(object):
        Miembro = "calificado"

    class ConLasDos(object):
        Grupo = Calificado
        Miembro = "plano"

    class SoloPlano(object):
        Miembro = "plano"

    assert enum(ConLasDos, "Grupo", "Miembro") == "calificado"
    assert enum(SoloPlano, "Grupo", "Miembro") == "plano"


def test_el_resolutor_aguanta_un_grupo_vacio():
    """Hay vinculaciones en que la clase del enum existe pero no lleva sus
    miembros: cuelgan de la clase de fuera y de ningun otro sitio.

    Encadenar getattr a ciegas revienta justo ahi, y es el caso de las
    versiones intermedias de QGIS, que es donde menos se prueba.
    """
    from hdfeos_extractor.compat import enum

    class GrupoVacio(object):
        pass

    class Clase(object):
        Grupo = GrupoVacio
        Miembro = "plano"

    assert enum(Clase, "Grupo", "Miembro") == "plano"
    with pytest.raises(AttributeError):
        enum(Clase, "Grupo", "NoExiste")
