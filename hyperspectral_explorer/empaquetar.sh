#!/bin/sh
# Arma el ZIP instalable en QGIS (Complementos > Instalar desde ZIP).
#
# Igual que en el plugin hermano de este repositorio: el "Download ZIP" de
# GitHub genera una carpeta raiz con el nombre del repositorio, y QGIS toma
# ese nombre como nombre del complemento. Este script deja la carpeta raiz
# llamada hyperspectral_explorer, que es lo que el plugin espera.
set -e

PAQUETE=hyperspectral_explorer
AQUI=$(cd "$(dirname "$0")" && pwd)
VERSION=$(sed -n 's/^version=//p' "$AQUI/metadata.txt")
SALIDA="$AQUI/$PAQUETE-$VERSION.zip"
TEMP=$(mktemp -d)

mkdir "$TEMP/$PAQUETE"
# Solo lo que hace falta en tiempo de ejecucion, mas README y LICENSE. Las
# pruebas y los ejemplos no van: no los usa QGIS y engordan la descarga.
for f in __init__.py plugin.py metadata.txt icon.png icon.svg README.md; do
    cp "$AQUI/$f" "$TEMP/$PAQUETE/"
done
cp "$AQUI/../LICENSE" "$TEMP/$PAQUETE/"
for d in core vista qgis_ui; do
    mkdir "$TEMP/$PAQUETE/$d"
    cp "$AQUI/$d"/*.py "$TEMP/$PAQUETE/$d/"
done

rm -f "$SALIDA"
(cd "$TEMP" && zip -q -r - "$PAQUETE") > "$SALIDA"
rm -rf "$TEMP"

echo "Listo: $SALIDA"
unzip -l "$SALIDA" | tail -n +2
