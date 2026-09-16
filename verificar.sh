#!/bin/sh
# Todo lo que hay que pasar antes de empujar: pruebas, estilo y la demo.
#
# Existe para que el CI y la comprobacion local no se desincronicen. El
# workflow llama a este mismo script, asi que lo que pasa aca pasa alla -y al
# reves-. La primera version tenia los comandos escritos dos veces y se
# separaron en un dia: el CI encontro un E741 que el comando local, escrito
# de memoria con otros argumentos, no miraba.
set -e

AQUI=$(cd "$(dirname "$0")" && pwd)
cd "$AQUI"

export QT_QPA_PLATFORM=offscreen

echo "== pruebas =="
python3 -m pytest -q

echo "== pyflakes =="
python3 -m pyflakes hdfeos_extractor comprobar_qt6.py

echo "== pycodestyle =="
# lector.py y proveedor.py quedan fuera: traen dos lineas largas de la
# version 1.0 y reformatearlas ensuciaria el historial del plugin publicado
# sin arreglar nada.
python3 -m pycodestyle --max-line-length=80 \
    hdfeos_extractor/core hdfeos_extractor/vista \
    hdfeos_extractor/qgis_ui hdfeos_extractor/examples \
    hdfeos_extractor/compat.py comprobar_qt6.py
# E402 en las pruebas: varias empiezan con pytest.importorskip para saltarse
# el modulo cuando falta una dependencia opcional, y eso obliga a importar
# despues. Es la forma que pytest documenta.
python3 -m pycodestyle --max-line-length=80 --ignore=E402 \
    hdfeos_extractor/tests

echo "== bandit =="
# El repositorio de complementos BLOQUEA la publicacion por los hallazgos
# criticos de bandit, asi que enterarse aqui y no alli ahorra una version
# quemada. Las pruebas quedan fuera: alli un except amplio es legitimo.
# Si bandit no esta instalado se avisa y se sigue, como con las demas
# herramientas opcionales.
if python3 -c "import bandit" 2>/dev/null; then
    python3 -m bandit -r hdfeos_extractor --exclude hdfeos_extractor/tests -q
else
    echo "bandit no esta instalado: no se revisa. pip install bandit"
fi

echo "== la interfaz se construye con Qt6 =="
# Aparte de la suite a proposito: la vinculacion de Qt se elige una vez por
# proceso, y mezclar PyQt5 y PyQt6 en la misma sesion de pytest no da un
# resultado dudoso, da una caida. Sin PyQt6 instalado, avisa y se aparta.
python3 comprobar_qt6.py

echo "== la demo corre de punta a punta =="
python3 hdfeos_extractor/examples/demo_cube.py > /dev/null

echo
echo "todo en verde"
