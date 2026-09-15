# -*- coding: utf-8 -*-
"""Dobles de prueba.

``qgis/`` es un doble minimo de la API de QGIS: solo los nombres que el
plugin usa, con el comportamiento justo para que el panel se construya y
responda.

Que prueba y que no. SI prueba el cableado: que las senales existan y esten
conectadas, que los metodos que el plugin llama existan, que un clic llegue
al grafico y que la lista se refresque. NO prueba que QGIS de verdad se
comporte asi -un doble puede quedar desactualizado respecto de la API real-.
Es una prueba de humo del frontend, no un sustituto de abrir QGIS.

El doble solo se usa cuando QGIS no esta disponible. Donde si lo esta, la
prueba corre contra QGIS de verdad, que es mejor.
"""

import importlib.util
import os
import sys


def instalar_si_falta_qgis():
    """Pone el doble en sys.path solo si no hay QGIS.

    Devuelve True si termino usando el doble. ``find_spec`` y no un ``import``
    dentro de un try: averigua si el modulo existe sin llegar a cargarlo, que
    para QGIS no es gratis.
    """
    if importlib.util.find_spec("qgis") is not None:
        return False
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    return True
