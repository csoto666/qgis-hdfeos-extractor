# -*- coding: utf-8 -*-
"""Pruebas de la biblioteca espectral."""

import csv
import json

import numpy as np
import pytest

from hyperspectral_explorer.core.library import LibraryError, SpectralLibrary
from hyperspectral_explorer.core.spectral import Signature


def firma(nombre, valores, wl=None):
    valores = np.asarray(valores, dtype=np.float32)
    if wl is None:
        wl = np.linspace(400.0, 900.0, valores.size)
    return Signature(nombre, wl, valores, pixels=[(1, 2)], source="escena",
                     notes="nota de " + nombre)


@pytest.fixture
def biblioteca():
    b = SpectralLibrary()
    b.add(firma("Vegetacion", [0.05, 0.08, 0.45, 0.42]))
    b.add(firma("Suelo", [0.12, 0.18, 0.25, 0.30]))
    b.add(firma("Agua", [0.06, 0.04, 0.02, 0.01]))
    return b


# -- coleccion ----------------------------------------------------------------
def test_alta_consulta_y_baja(biblioteca):
    assert len(biblioteca) == 3
    assert "Suelo" in biblioteca
    assert biblioteca.get("Suelo").name == "Suelo"
    assert biblioteca.remove("Suelo") is True
    assert biblioteca.remove("Suelo") is False
    assert "Suelo" not in biblioteca


def test_una_firma_que_no_esta(biblioteca):
    with pytest.raises(KeyError):
        biblioteca.get("Nieve")


def test_un_nombre_repetido_se_numera(biblioteca):
    """El costo de equivocarse tiene que ser una firma de mas, nunca una
    firma perdida que costo diez minutos de muestreo."""
    biblioteca.add(firma("Agua", [0.1, 0.1, 0.1, 0.1]))
    assert biblioteca.names()[-1] == "Agua (2)"
    assert len(biblioteca) == 4


def test_se_puede_reemplazar_a_proposito(biblioteca):
    biblioteca.add(firma("Agua", [0.9, 0.9, 0.9, 0.9]), reemplazar=True)
    assert len(biblioteca) == 3
    assert np.allclose(biblioteca.get("Agua").values, 0.9)


def test_renombrar(biblioteca):
    biblioteca.rename("Agua", "Agua clara")
    assert "Agua clara" in biblioteca and "Agua" not in biblioteca


def test_renombrar_a_uno_ocupado_falla(biblioteca):
    with pytest.raises(LibraryError, match="Ya hay una firma"):
        biblioteca.rename("Agua", "Suelo")


def test_renombrar_a_vacio_falla(biblioteca):
    with pytest.raises(LibraryError, match="no puede quedar vacio"):
        biblioteca.rename("Agua", "   ")


def test_renombrar_al_mismo_nombre_no_hace_nada(biblioteca):
    assert biblioteca.rename("Agua", "Agua").name == "Agua"
    assert len(biblioteca) == 3


# -- comparacion --------------------------------------------------------------
def test_comparar_dos_por_nombre(biblioteca):
    assert biblioteca.compare("Agua", "Agua") == pytest.approx(0.0, abs=1e-9)
    assert biblioteca.compare("Agua", "Vegetacion") > 10.0


def test_ordenar_por_parecido(biblioteca):
    """El caso util: a cual de mis firmas se parece el pixel que acabo de
    tocar."""
    parecida_a_vegetacion = firma("?", [0.04, 0.07, 0.44, 0.40])
    orden = biblioteca.compare_all(parecida_a_vegetacion)
    assert [n for n, _ in orden][0] == "Vegetacion"
    angulos = [a for _, a in orden]
    assert angulos == sorted(angulos)


def test_compare_all_se_salta_lo_incomparable(biblioteca):
    """Una firma de otro sensor no debe tumbar la comparacion entera."""
    biblioteca.add(firma("Otro sensor", [0.1, 0.2, 0.3]))
    orden = biblioteca.compare_all("Agua")
    assert "Otro sensor" not in [n for n, _ in orden]
    assert len(orden) == 2


def test_compare_all_no_se_compara_consigo_misma(biblioteca):
    assert "Agua" not in [n for n, _ in biblioteca.compare_all("Agua")]


def test_match_devuelve_la_mas_cercana(biblioteca):
    nombre, angulo = biblioteca.match(firma("?", [0.05, 0.04, 0.02, 0.01]))
    assert nombre == "Agua"
    # 5.1 grados. El siguiente candidato esta a mas de 40: la separacion es
    # amplia, el umbral no es un ajuste fino.
    assert angulo < 10.0


def test_match_en_biblioteca_vacia():
    assert SpectralLibrary().match(firma("?", [0.1, 0.2])) is None


# -- persistencia -------------------------------------------------------------
def test_guardar_y_releer(tmp_path, biblioteca):
    destino = str(tmp_path / "libreria.json")
    biblioteca.save(destino)
    vuelta = SpectralLibrary.load(destino)
    assert vuelta.names() == biblioteca.names()
    original = biblioteca.get("Vegetacion")
    copia = vuelta.get("Vegetacion")
    assert np.allclose(copia.values, original.values)
    assert copia.pixels == original.pixels
    assert copia.notes == original.notes
    assert copia.source == original.source


def test_el_archivo_lleva_version_de_formato(tmp_path, biblioteca):
    destino = str(tmp_path / "l.json")
    biblioteca.save(destino)
    with open(destino, encoding="utf-8") as f:
        assert json.load(f)["formato"] == 1


def test_save_recuerda_la_ruta(tmp_path, biblioteca):
    destino = str(tmp_path / "l.json")
    biblioteca.save(destino)
    biblioteca.add(firma("Nieve", [0.8, 0.8, 0.7, 0.6]))
    biblioteca.save()                      # sin argumento
    assert len(SpectralLibrary.load(destino)) == 4


def test_guardar_sin_decir_donde(biblioteca):
    with pytest.raises(LibraryError, match="donde guardar"):
        biblioteca.save()


def test_la_escritura_no_deja_temporales(tmp_path, biblioteca):
    destino = str(tmp_path / "l.json")
    biblioteca.save(destino)
    assert not list(tmp_path.glob("*.tmp"))


def test_guardar_encima_no_destruye_lo_anterior_si_falla(tmp_path, biblioteca):
    """Se escribe a un temporal y se renombra. Un corte a mitad de escritura
    deja intacta la version anterior en vez de un archivo truncado."""
    destino = tmp_path / "l.json"
    biblioteca.save(str(destino))
    original = destino.read_text(encoding="utf-8")
    rota = SpectralLibrary(path=str(destino))
    rota.add(Signature("mala", [400.0], [0.1]))
    rota._firmas.append(object())          # revienta al serializar
    with pytest.raises(AttributeError):
        rota.save()
    assert destino.read_text(encoding="utf-8") == original


def test_leer_algo_que_no_existe(tmp_path):
    with pytest.raises(LibraryError, match="No existe"):
        SpectralLibrary.load(str(tmp_path / "nada.json"))


def test_leer_un_json_que_no_es_biblioteca(tmp_path):
    ruta = tmp_path / "otro.json"
    ruta.write_text('{"cualquier": "cosa"}', encoding="utf-8")
    with pytest.raises(LibraryError, match="forma de biblioteca"):
        SpectralLibrary.load(str(ruta))


def test_leer_un_json_roto(tmp_path):
    ruta = tmp_path / "roto.json"
    ruta.write_text("{esto no es json", encoding="utf-8")
    with pytest.raises(LibraryError, match="JSON valido"):
        SpectralLibrary.load(str(ruta))


# -- exportacion --------------------------------------------------------------
def test_csv_ancho_cuando_el_eje_es_comun(tmp_path, biblioteca):
    ruta = str(tmp_path / "firmas.csv")
    assert biblioteca.to_csv(ruta) == "ancho"
    with open(ruta, encoding="utf-8") as f:
        filas = list(csv.reader(f))
    assert filas[0] == ["wavelength", "Vegetacion", "Suelo", "Agua"]
    assert len(filas) == 5                 # cabecera + 4 bandas
    assert float(filas[1][1]) == pytest.approx(0.05)


def test_csv_largo_cuando_los_ejes_difieren(tmp_path, biblioteca):
    """Forzar la tabla ancha alinearia en la misma fila valores de bandas
    distintas, que es un grafico que miente."""
    biblioteca.add(firma("Otro sensor", [0.1, 0.2, 0.3]))
    ruta = str(tmp_path / "firmas.csv")
    assert biblioteca.to_csv(ruta) == "largo"
    with open(ruta, encoding="utf-8") as f:
        filas = list(csv.reader(f))
    assert filas[0][:3] == ["name", "wavelength", "value"]
    assert len(filas) == 1 + 4 * 3 + 3


def test_los_nan_salen_como_celda_vacia(tmp_path):
    b = SpectralLibrary()
    b.add(firma("con hueco", [0.1, np.nan, 0.3, 0.4]))
    ruta = str(tmp_path / "f.csv")
    b.to_csv(ruta)
    with open(ruta, encoding="utf-8") as f:
        filas = list(csv.reader(f))
    assert filas[2][1] == ""


def test_exportar_una_biblioteca_vacia(tmp_path):
    with pytest.raises(LibraryError, match="vacia"):
        SpectralLibrary().to_csv(str(tmp_path / "f.csv"))
