# -*- coding: utf-8 -*-
"""Pruebas del cache acotado por bytes."""

import numpy as np
import pytest

from hdfeos_extractor.core.cache import CacheLRU


def bloque(mb):
    """Un array de aproximadamente ``mb`` megabytes."""
    return np.zeros(int(mb * 1024 * 1024 / 4), dtype=np.float32)


def test_devuelve_lo_que_guardo():
    c = CacheLRU(10)
    dato = bloque(1)
    c.poner("a", dato)
    assert c.obtener("a") is dato


def test_lo_que_no_esta_da_none():
    assert CacheLRU(10).obtener("a") is None


def test_desaloja_lo_mas_viejo_cuando_no_cabe():
    c = CacheLRU(3)
    c.poner("a", bloque(1))
    c.poner("b", bloque(1))
    c.poner("c", bloque(1))
    c.poner("d", bloque(1))                  # el cuarto echa al primero
    assert c.obtener("a") is None
    assert c.obtener("b") is not None
    assert c.obtener("d") is not None


def test_usar_algo_lo_rejuvenece():
    """Sin esto no es un LRU: seria una cola, y echaria lo mas usado."""
    c = CacheLRU(3)
    c.poner("a", bloque(1))
    c.poner("b", bloque(1))
    c.poner("c", bloque(1))
    c.obtener("a")                            # 'a' vuelve a ser el reciente
    c.poner("d", bloque(1))
    assert c.obtener("a") is not None
    assert c.obtener("b") is None


def test_se_mide_en_bytes_y_no_en_piezas():
    """Doce bandas de una escena chica y doce de una grande no son lo mismo.

    Acotar por cantidad deja el consumo de memoria a merced del tamano de la
    escena, que es justo lo que no se puede permitir con datos pesados.
    """
    c = CacheLRU(10)
    c.poner("gorda", bloque(8))
    c.poner("otra", bloque(8))
    assert c.obtener("gorda") is None        # no caben las dos
    assert c.bytes_usados <= 10 * 1024 * 1024


def test_algo_mas_grande_que_el_cache_no_se_guarda():
    """Y sobre todo: no vacia el cache entero para no guardarlo igual."""
    c = CacheLRU(4)
    c.poner("normal", bloque(1))
    c.poner("enorme", bloque(20))
    assert c.obtener("enorme") is None
    assert c.obtener("normal") is not None


def test_lo_guardado_no_se_puede_modificar_desde_fuera():
    """Quien lee una banda no debe poder corromper la copia de los demas."""
    c = CacheLRU(10)
    dato = bloque(1)
    c.poner("a", dato)
    with pytest.raises(ValueError):
        c.obtener("a")[0] = 1.0


def test_vaciar_lo_deja_como_nuevo():
    c = CacheLRU(10)
    c.poner("a", bloque(1))
    c.vaciar()
    assert c.obtener("a") is None
    assert c.bytes_usados == 0
