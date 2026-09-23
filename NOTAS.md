# Notas de diseño

Por qué cada cosa está como está: el problema que resuelve el complemento, las
decisiones que lo ordenan y lo que se midió antes de tomarlas.

Esto vivía en el README. Se mudó aquí porque son dos públicos y dos preguntas
distintas: quien llega al repositorio quiere saber qué hace el complemento y
cómo instalarlo —eso está en el [README](README.md)—, y quien va a tocar el
código quiere saber por qué. Nada se recortó al mudarlo.

*Design notes, in Spanish: the reasoning behind each decision. What the plugin
does and how to install it is in the [README](README.md).*

---

## Índice

- [El problema](#el-problema)
- [El cubo no es una ilustración](#el-cubo-no-es-una-ilustración)
- [Bandas malas](#bandas-malas)
- [Los cuatro modos de navegación](#los-cuatro-modos-de-navegación)
- [Una sola herramienta: el cubo y el espectro](#una-sola-herramienta-el-cubo-y-el-espectro)
- [Plegar lo que ahora mismo no se está mirando](#plegar-lo-que-ahora-mismo-no-se-está-mirando)
- [El zoom recalcula el realce](#el-zoom-recalcula-el-realce)
- [La composición RGB se elige por longitud de onda](#la-composición-rgb-se-elige-por-longitud-de-onda)
- [Biblioteca espectral](#biblioteca-espectral)
- [Enviar la vista a QGIS](#enviar-la-vista-a-qgis)
- [Vincular el cubo con el mapa](#vincular-el-cubo-con-el-mapa)
- [La proyección: de dónde salen las coordenadas](#la-proyección-de-dónde-salen-las-coordenadas)
- [La huella espacial de una firma](#la-huella-espacial-de-una-firma)
- [La nube n-dimensional](#la-nube-n-dimensional)
- [Por qué un cubo pesado se sentía lento, y qué se hizo](#por-qué-un-cubo-pesado-se-sentía-lento-y-qué-se-hizo)
- [Rendimiento](#rendimiento)
- [Arquitectura](#arquitectura)
- [Uso del núcleo sin QGIS](#uso-del-núcleo-sin-qgis)
- [Qt5 y Qt6](#qt5-y-qt6)
- [Pruebas](#pruebas)
- [Publicar una versión](#publicar-una-versión)

---

## El problema

Un producto hiperespectral moderno llega como un solo contenedor HDF-EOS5 con
el cubo, los arreglos de geolocalización por píxel, las máscaras de calidad y
la geometría sol-sensor adentro. Ahí se rompen dos cosas.

**No se abre.** El software anterior al producto no lo entiende: ENVI 5.0 es
de 2013 y Tanager de 2024, y no existe opción de menú que lea ese contenedor.
Exportarlo como ráster común tira a la basura el metadato espectral, que es
justamente lo que vuelve utilizable un cubo.

**Y cuando se abre, se ve mal.** Un cubo es tres cosas a la vez —un lugar, una
imagen y un espectro— y casi todos los visores muestran una sola. El usuario
ve una composición en falso color, reconoce que *ahí* hay algo distinto, y no
tiene manera de preguntarle a ese píxel por qué.

## El cubo no es una ilustración

La vista clásica del cubo hiperespectral —la imagen al frente y el espectro en
los costados— aquí no es un adorno: **las caras laterales son los mismos
transectos que alimentan el gráfico**.

```
cara superior  = get_transect("y", fila)     → (x, λ)
cara derecha   = get_transect("x", columna)  → (y, λ)
```

La diferencia con el cubo de ENVI es que aquel es estático —sus caras son el
borde de la escena— y este no: **las caras son el corte que pasa por la cruz**.
Mover la cruz recorre el cubo de verdad. Es la diferencia entre mirar un cubo
y explorarlo.

Las tres bandas que arman la imagen frontal se dibujan **dentro** de las caras,
así que se ve de qué rebanadas está hecho lo que se está mirando. Y un clic en
un costado lleva esa banda al frente: es el gesto natural frente a un cubo
—se ve una franja rara y uno quiere ver esa banda—.

No hay OpenGL ni biblioteca 3D. La proyección es oblicua y se dibuja con
QPainter aplicando una transformación afín a cada cara.

## Bandas malas

Un cubo hiperespectral siempre trae bandas que no sirven, y arrastrarlas
cuesta dos cosas distintas. La visible es que el gráfico se llena de picos que
tapan la forma de la firma. **La cara es que entran en la media, en la
desviación y en el ángulo espectral como si fueran mediciones**, y ahí ya no se
ven: sólo corren los números.

El plugin las descarta por cuatro criterios, que se combinan y se encienden por
separado:

| Criterio | Qué descarta | Por defecto |
|---|---|---|
| **Lista del archivo** | La `bbl` que trae el propio producto | Activo si el archivo la incluye |
| **Vapor de agua** | 1340–1460 y 1790–1960 nm | Activo |
| **Extremos** | Por debajo de 400 y por encima de 2450 nm | Activo |
| **Rangos propios** | Lo que escribas: `1340-1460, 900` | Vacío |

Una banda sobrevive sólo si ninguno la descarta. En la duda, fuera — que es
además lo que hace el extractor al escribir la `bbl`, así que el explorador y
el ENVI extraído coinciden.

La banda descartada sale como **NaN**, y de ahí en adelante todo el resto lo
ignora solo: el gráfico corta la curva, `nanmean` la saltea, el ángulo
espectral la excluye y el realce del cubo deja de estar sesgado por el ruido de
las ventanas de absorción.

Tres detalles que importan:

- **El gráfico sombrea los tramos descartados.** Sin eso la curva simplemente
  se corta y no se sabe si falta el dato o si el sensor no llega hasta ahí.
- **`get_band` no se enmascara.** La máscara limpia el análisis espectral, no
  impide mirar una banda: quien quiere ver cómo se ve la de 1400 nm tiene
  derecho a verla, en ruido, pero verla.
- **El compositor RGB no cae en una banda descartada.** Un preset que aterriza
  dentro de una ventana de absorción devolvería ruido puro, y la imagen saldría
  con textura que no existe en el terreno —y que alguien interpretaría—.

Sin eje espectral en nanómetros los dos criterios por longitud de onda se
apagan solos: sobre un eje que es el número de banda, «descartar por debajo de
400» borraría el cubo entero.

## Los cuatro modos de navegación

Se ven en el cubo, y cada uno mueve algo distinto:

| Modo | Qué mueve | Qué cambia |
|---|---|---|
| **Píxel** | La cruz entera | El espectro de ese píxel |
| **Línea X** | Sólo la vertical | La **cara derecha** del cubo: el corte de esa columna |
| **Línea Y** | Sólo la horizontal | La **cara superior**: el corte de esa fila |
| **Área** | Un rectángulo | Firma media del área, con su desviación como envolvente |
| **Píxeles** | Un punto por clic | Firma media del conjunto, para muestrear variabilidad |

Funcionan tanto sobre el lienzo de QGIS como **dentro de la vista del cubo**.
Eso último importa: con un HDF-EOS5 abierto directamente no hay capa en el
mapa, así que sobre el lienzo no habría dónde actuar.

## Una sola herramienta: el cubo y el espectro

Son las dos caras del mismo dato —dónde está el píxel y qué mide—, así que
van en el mismo panel, separados por un divisor que se arrastra. El reparto
se **acuesta o se apila** según dónde esté acoplado el panel: al costado de
QGIS, el cubo arriba y el espectro abajo; abajo o flotando, uno al lado del
otro. Con dos pantallas, **Soltar aparte** manda el cubo a su propia ventana;
cerrarla lo devuelve al panel. Cerrar el panel entero esconde las dos y no
pierde nada: al volver a abrirlo, el arreglo que elegiste está donde lo
dejaste.

Soltar el cubo **no lo convierte a él en una ventana**: lo muda a una ventana
que ya existía, vacía hasta ese momento. La diferencia no se ve pero importa.
Ponerle a un widget ya montado la bandera de ventana y quitársela después
obliga a Qt a destruir y rehacer su ventana nativa con la interfaz en marcha,
y eso colgaba QGIS en macOS: la pila del cuelgue termina en `QWidget::create`,
llamado mientras la animación de acople recorre los hijos del panel para
mostrarlos. Cambiar de padre, en cambio, es lo que Qt hace todo el rato —un
divisor, una pestaña— y es la única operación pensada para hacerse en caliente.

Por el mismo motivo, el panel **no hace ningún trabajo dentro de su
`showEvent`**: ese método corre en mitad de la animación de acople de QGIS, y
tocar el lienzo ahí es reentrar en lo que Qt está reacomodando. Lo que haya que
rehacer al volver a mostrarlo se aplaza un giro del bucle de eventos.

## Plegar lo que ahora mismo no se está mirando

El panel tiene cuatro bloques y una sola columna de alto para repartir entre
ellos. Según lo que estés haciendo, uno de ellos es el trabajo y los otros son
contexto: al comparar firmas manda el gráfico, al recorrer el cubo manda el
cubo, y en ese momento la lista de firmas y el perfil son dos franjas que no
estás mirando y que le están quitando alto a lo que sí.

**El nombre de la sección es el botón.** Pulsa *Perfil espectral* o *Firmas
guardadas* y la sección se pliega a su título; vuelve a pulsarlo y regresa.
La flecha del nombre dice en qué estado está —▾ abierta, ▸ plegada—, que es
lo que distingue una sección plegada de una sección vacía. Es el mismo
mecanismo de *Bandas R G B* y *Bandas malas*, subido al título.

Plegar no es cerrar: no se reconstruye nada, las firmas siguen guardadas y sus
curvas siguen en el gráfico. Al plegar el perfil, el divisor **reparte de
nuevo** y ese alto se lo queda el cubo —los tamaños de un divisor de Qt son
pegajosos y, sin repartir, esconder una mitad dejaría un agujero en vez de
agrandar la otra—. Al desplegarlo vuelve el reparto que tenías, no el de
fábrica: el reparto es tuyo.

## El zoom recalcula el realce

Acercarse no es sólo ver más grande. Una escena sin ortorectificar llega dentro
de un rectángulo mucho más grande que la franja que el sensor recorrió, y el
resto es relleno y ceros. Con el realce calculado sobre la escena entera esos
ceros estiran el rango y el terreno queda aplastado en una banda de grises.

Al acercarse se recalculan **el realce y la escala de color sobre lo visible**,
y la barra de color a la derecha del cubo dice en qué valores está.

## La composición RGB se elige por longitud de onda

No por número de banda. Es lo que vuelve portables los presets: `rojo = 665 nm`
significa lo mismo en Tanager, en PRISMA y en EMIT; `rojo = banda 29` no
significa nada fuera del sensor donde se escribió.

Los presets que el sensor no alcanza no se ofrecen. Un preset SWIR sobre un
cubo que llega a 900 nm no falla: resuelve las tres bandas a la última y
devuelve una imagen gris que el usuario no sabe interpretar.

## Biblioteca espectral

Las firmas se guardan con **procedencia**: de qué escena, de qué píxeles,
cuándo y con qué notas. El vector de reflectancia solo no sirve para nada seis
meses después.

Se pueden renombrar, ocultar, borrar, comparar por **ángulo espectral** (SAM)
y exportar a CSV. El ángulo es la medida correcta entre espectros porque
compara la forma y no la magnitud: la misma cubierta en sombra y al sol da dos
curvas a alturas distintas y con el mismo ángulo.

## Enviar la vista a QGIS

**Enviar vista a QGIS** agrega al mapa sólo el RGB que se está viendo,
recortado a la vista actual y con el realce puesto. No carga el cubo: son tres
bandas de 8 bits más una de transparencia, así que el relleno no tapa el mapa
de fondo. Sirve para digitalizar encima o componer un mapa mientras se sigue
midiendo espectros en el cubo, al lado.

## Vincular el cubo con el mapa

En el cubo se ve el detalle espectral pero no el contexto; en el mapa está el
contexto —una ortofoto de alta resolución, el catastro— pero no el espectro.
**Vincular con el mapa** hace que los dos miren lo mismo: al acercarse o
desplazarse en uno, el otro va detrás. Lo que se está midiendo deja de ser un
parche de colores y pasa a ser un sitio reconocible.

Necesita que la escena esté georreferenciada; si no, el botón se queda
apagado y la barra de estado dice por qué. Con una escena en geometría de
sensor funciona, pero la correspondencia es un ajuste por mínimos cuadrados y
se avisa: sirve para navegar, no para medir sobre el mapa.

Lo difícil aquí no es la geometría sino el **bucle**: cada lado avisa de sus
cambios y ese aviso mueve al otro, que avisa a su vez. Se corta por dos vías
—una bandera mientras dura la sincronización, y una comparación que ignora
los movimientos despreciables— porque cada una se escapa en un caso distinto.
La prueba que lo cubre falla con `RecursionError` si se quita cualquiera de
las dos.

## La proyección: de dónde salen las coordenadas

Es el error más caro de los datos geoespaciales porque no se ve: una capa mal
proyectada se dibuja igual de bien, sólo que en el lugar equivocado. El plugin
lee la georreferencia **del propio archivo** y distingue tres casos, porque
tratarlos igual es justamente el error:

| Caso | De dónde sale | Qué se hace |
|---|---|---|
| **Ortho** | `StructMetadata`, un atributo `GeoTransform`, o los ejes `x`/`y` | Se usa su afín exacta. No se toca ningún píxel |
| **Afín** | `map info` de ENVI, o la geotransformación que traiga GDAL | Se escribe tal cual, con sus términos de rotación |
| **Geometría de sensor** | Las capas de latitud y longitud del HDF-EOS5 | Se reproyecta de verdad, por placa delgada, hacia una rejilla al norte |
| **Sin georreferencia** | — | Se dice. No se inventa un SRC |

El primero es el producto **ortorectificado**, y es el que más despista: no
trae capas de latitud y longitud —no las necesita, ya está puesto sobre una
proyección— así que buscárselas no encuentra nada aunque el producto venga
perfectamente ubicado. Su georreferencia es una afín, y puede estar en tres
sitios según quién escribiera el archivo: el `StructMetadata` de HDF-EOS, un
atributo `GeoTransform`, o dos vectores `x`/`y` con el centro de cada columna
y de cada fila. Se reconocen los tres. Extraer a ENVI la conserva: el cubo
extraído sale con su `map info`.

El segundo caso es el de los productos sin ortorectificar, y no es un detalle:
ahí la relación entre píxel y terreno cambia a lo ancho de la franja, y
**ninguna geotransformación afín la describe**. Escribirla como si la tuviera
deja la escena en coordenadas de píxel, es decir en el golfo de Guinea.

El tercero es deliberado. Una capa sin SRC se ve mal puesta y el usuario lo
entiende; una capa con un SRC inventado se ve bien puesta y está mal, que es
peor. El panel dice en su barra de estado de dónde salieron las coordenadas.

## Por qué un cubo pesado se sentía lento, y qué se hizo

Medido sobre un cubo del tamaño real de un Tanager —426 bandas, 655×785,
HDF5 con compresión gzip y *chunks* de un plano de banda, que es el formato en
el que estos productos circulan—, **mover la cruz un píxel costaba 7,2 s** y
no mejoraba al repetirlo.

El motivo está en cómo se guarda el archivo. Con *chunks* de un plano por
banda, leer el espectro de UN píxel obliga a descomprimir los 426 planos
enteros: 400 MB de inflado de gzip para devolver 426 números. Y cada píxel que
la cruz recorre pide tres de esas lecturas —las dos caras del cubo son
transectos, más la firma—.

Tres cambios, ninguno con dependencias nuevas:

**Caché acotado por bytes, no por piezas.** Bandas, transectos y espectros,
cada uno con su presupuesto. En bytes porque doce bandas de una escena de
200×200 son tres megabytes y doce de un Tanager son veinticinco: contar piezas
deja el consumo de memoria a merced del tamaño de la escena. Se guarda **sin
enmascarar** y la máscara se aplica al salir, así que cambiar el filtro de
vapor de agua no devuelve dato viejo.

**El espectro sale gratis del transecto.** La cara de arriba del cubo *es* el
transecto en Y de la fila de la cruz, y el espectro del píxel es una de sus
columnas. Al revés no: un clic suelto no lee la fila entera, porque sobre un
ENVI mapeado en memoria eso sería traer cientos de veces más dato del
necesario.

**El arrastre se atiende al ritmo que el dato deje, no al del ratón.** Sin
freno, arrastrar la cruz medio segundo encola cien lecturas de cinco segundos
cada una y QGIS queda inservible varios minutos por algo que ya dejaste de
pedir. El freno se mide solo —no se empieza otro hasta que haya pasado lo que
tardó el anterior— así que con dato rápido no frena nada, y lo que se salta
son los movimientos *intermedios*: el último se guarda y se atiende al soltar,
de modo que la cruz siempre acaba donde la llevaste.

| gesto | antes | ahora |
|---|---|---|
| mover la cruz a un píxel nuevo | 7,2 s | 5,0 s |
| volver a un píxel ya visitado | 7,0 s | **0,00 s** |
| arrastrar 60 píxeles | 277 s | **14,4 s** |

Los 5 s del píxel nuevo son el archivo, no el plugin: es lo que cuesta
descomprimirlo. Sobre un ENVI extraído —que está mapeado en memoria y sin
comprimir— los mismos gestos cuestan milisegundos, y por eso **Extraer…**
sigue siendo la mejor inversión para trabajar mucho rato sobre una escena.

## La huella espacial de una firma

El dato ya estaba. `Signature` guarda la lista completa de `(x, y)` desde la
primera versión —se guardó para poder volver a extraer la firma del cubo y
comprobarla— y no se estaba usando para nada más. Lo único que faltaba era
pasarla por la geotransformación y decidir qué forma le corresponde.

Y le corresponde una distinta según cómo se tomó, que es justo lo que no hay que
perder:

    un píxel        →  un punto
    un rectángulo   →  el polígono de su borde exterior
    píxeles sueltos →  varios puntos, NO su caja envolvente

**Lo último importa.** La caja que envuelve tres píxeles dispersos pinta en el
mapa hectáreas de terreno que nadie midió, y un mapa que afirma algo que no se
midió es peor que un mapa sin la capa.

### El tipo se deduce, no se guarda

Podría haber añadido un campo `tipo` a `Signature`. No lo hice: se deduce de los
píxeles —uno solo es un punto; varios que llenan entero el rectángulo que los
envuelve son un área; el resto son píxeles sueltos—. Así una biblioteca guardada
con una versión anterior se puede llevar al mapa igual, sin migrar nada y sin
echar de menos un campo que no existe.

### El borde exterior, no el centro de los píxeles del borde

El polígono de un área va por la esquina de fuera de sus píxeles. Tomarlo por el
centro dejaría fuera media fila y media columna de lo que de verdad se midió.

Y son las **cuatro esquinas**, no dos opuestas: con rotación —una franja de
sensor sin ortorectificar llega inclinada— el rectángulo de píxeles es un rombo
en el terreno, y su caja envolvente vuelve a pintar terreno que la firma nunca
tocó. `esquinas_de_ventana` se sacó de dentro de `bbox_de_ventana`, donde ya se
calculaba para después tirarlo.

### El GeoJSON se reproyecta, no se avisa

El RFC 7946 fija WGS84 y quitó el miembro `crs` que antes permitía declarar otro
sistema. Un GeoJSON con metros UTM dentro es un archivo que cada programa
interpreta a su manera —y casi siempre mal, como si fueran grados: la escena
aparece en el golfo de Guinea—. Escribirlo bien es trabajo de quien lo escribe,
así que se reproyecta a longitud/latitud. Sin SRC en la escena no hay desde
dónde reproyectar; ahí se escribe tal cual y se dice, que es lo único honesto
que queda.

### Al día sin perder el sitio

Las capas se ponen al día vaciándolas y rellenándolas, no quitándolas y creando
otras. Una capa nueva tiene otro identificador, se va al final del árbol de capas
y pierde el sitio y la visibilidad que el usuario le había dado. Ponerla al día
no debería costarle eso.

Antes de tocarlas se comprueba que sigan en el proyecto. Si el usuario las quitó,
el complemento las suelta y no vuelve a agregarlas: quitarlas es una decisión
suya y devolvérselas sería discutírsela.

### El tipo de campo y Qt6

Declarar los campos de una capa pasa por `QMetaType.Type` y no por
`QVariant.Type`: **Qt6 quitó `QVariant.Type` entero**. En PyQt6 no existe ni
`QVariant.String` ni `QVariant.Type`, y una capa cuyos campos no se pueden
declarar es una capa que no se crea. Lo encontró el detector de enums sin
calificar del propio repositorio, en el mismo commit que lo introdujo.

Y el sistema de referencia se resuelve preguntándole a QGIS por el código EPSG
antes de construir un WKT con GDAL: QGIS resuelve códigos sin ayuda de nadie, y
ese camino sigue funcionando en instalaciones donde el enlace de Python con GDAL
está roto —que las hay, y es justo donde uno no quiere perder la capa—.

## La nube n-dimensional

Un gráfico de dispersión de dos bandas es lo que casi todas las herramientas
ofrecen, y casi siempre **miente por omisión**: dos clases que en el espectro
completo están clarísimamente separadas pueden caer una encima de la otra en el
par de bandas que uno eligió. La separación existe, pero no en ese plano.

La salida no es mirar más planos de dos en dos —con 426 bandas son noventa mil
pares— sino mirar la nube entera y hacerla **girar**. Una nube de n dimensiones
proyectada sobre un plano que rota va enseñando una sombra distinta a cada
instante, y el ojo humano separa grupos en movimiento muchísimo mejor que en
una imagen quieta. Es lo que hace el *n-D Visualizer* de ENVI, y esto es lo
mismo sobre las firmas guardadas del complemento.

### La pieza matemática son dos vectores

La pantalla son dos vectores ortonormales `u` y `v` en R^n: `(x, y) = (dato·u,
dato·v)`. Girar es mover ese par.

El giro se arma como producto de **rotaciones de Givens** —giros en un plano de
dos coordenadas— con frecuencias que son raíces de primos. Dos decisiones ahí,
y las dos importan:

**Raíces de primos** porque sus cocientes son irracionales, así que el recorrido
no tiene ciclo y la animación nunca vuelve a pasar exactamente por la misma
vista. Con frecuencias enteras la rotación se cerraría en pocos segundos y
dejaría de mostrar proyecciones nuevas, que es para lo único que sirve.

**Se gira el plano (k, k+1) para todo k**, de modo que ninguna banda se queda
fuera del recorrido. Si alguna no participara, su dirección nunca se vería de
frente y un grupo separado sólo en esa banda quedaría escondido para siempre.

Cada rotación de Givens es ortogonal, así que el producto también lo es y la
base sale ortonormal **por construcción**: no hay que reortogonalizar y no hay
deriva numérica. Y se aplican sólo a los dos vectores de la base, no a la matriz
entera: eso es O(n) por cuadro en vez de O(n²), y con doscientas bandas
seleccionadas es la diferencia entre animar y no animar.

Una prueba fija que la base es ortonormal a cualquier `t`, y otra que la
proyección nunca alarga un vector —la sombra no puede ser más larga que el
objeto—. Si eso fallara, las distancias que el usuario ve estarían mintiendo.

### Los radios son lo que la vuelve legible

Cada banda seleccionada se dibuja como un radio: su eje unitario proyectado. Un
radio que apunta hacia donde se alarga un grupo dice que **esa banda es la que
lo separa**. Sin ellos la nube es una mancha bonita que gira.

Se dibujan más tenues cuanto más cortos, y eso también es información: un radio
corto es una banda que en esta vista apunta casi de frente a la pantalla, y
verlo apagarse al girar dice que ahora mismo esa banda no está separando nada.
Sólo se rotulan los más largos y se salta el rótulo que caería encima de otro
ya escrito, porque dos bandas casi paralelas ponen su número en el mismo sitio
y el resultado es ilegible.

### Los puntos son píxeles, no medias

Cada firma guardada aporta **todos sus píxeles**, no su media. Esa es la
diferencia que hace útil la vista: una firma de área es un solo espectro en el
gráfico espectral y quinientos puntos aquí, y la media no muestra si el área
era un grupo o dos.

Se puede porque `Signature` guarda la lista completa de `(x, y)` desde el
principio —se guardó para poder volver a extraer la firma del cubo y
comprobarla, y resultó ser justo lo que esta vista necesitaba—.

Hay tope de puntos por clase, y el submuestreo es **parejo y no por el
principio**: los píxeles de un área vienen ordenados por fila, así que cortar
los primeros N dejaría fuera media escena y el usuario vería un grupo que no
existe.

### Escalar con un solo número

La nube se centra y se divide por **un** número —el máximo global— en vez de
normalizar banda por banda. Normalizar cada banda por separado le daría a una
banda de puro ruido el mismo peso que a una que separa las clases, y el ruido se
comería la estructura que se venía a ver.

### El lazo cierra el círculo

Sin él la nube sería una vista bonita de la que no sale nada. Con él, el grupo
que sólo se ve girando vuelve a la biblioteca como una firma con sus píxeles,
comparable con las demás por ángulo espectral y exportable a CSV.

El punto en polígono va vectorizado sobre todos los puntos a la vez: con veinte
mil puntos, hacerlo punto por punto se nota al soltar el ratón. Y funciona con
lazos cóncavos, que es lo que sale de dibujar a mano alzada.

### Lo que cuesta

La nube se arma sólo cuando la ventana está encendida, y se rehace al cambiar
las firmas o las bandas. Leer los píxeles de todas las firmas cuesta —sobre un
HDF5 comprimido, bastante— y no tiene sentido pagarlo por una ventana que nadie
ve. Por eso la ventana nace apagada y el reloj se para al esconder el panel.

Se dibuja con QPainter y no con OpenGL: el complemento no puede pedir
dependencias que QGIS no traiga, y los puntos se pasan todos juntos —un
`drawPoints` por clase— en vez de uno por uno, que es lo que multiplicaría por
veinte el coste del cuadro.

## Rendimiento

ENVI se abre por memoria mapeada: el cubo no se carga, el sistema pagina lo que
se toca, y extraer un espectro lee unos pocos kilobytes.

HDF5 está comprimido y por trozos, así que un espectro obliga a descomprimir
los trozos que lo contienen. Con h5py se nota poco; con el respaldo de GDAL se
nota más. **Para una escena que se va a recorrer mucho, sigue conviniendo
extraer a ENVI** —y por eso el botón está en el panel—.

El principio que ordena el resto:

> **La resolución de despliegue y la de análisis están separadas.**

El mapa puede mostrar una imagen reducida mientras la extracción de espectros
sigue yendo al dato original, a resolución completa.

## Arquitectura

El núcleo está deliberadamente separado del frontend.

```
core/     numpy puro. No importa QGIS ni Qt.
   ↓
vista/    widgets de Qt. No importa QGIS.
   ↓
qgis_ui/  lo que habla con QGIS.
```

No es prolijidad: es lo que permite que el mismo núcleo sirva desde Jupyter o
desde un script, y —más inmediato— que se pueda **probar sin tener QGIS
instalado**.

```
hdfeos_extractor/
  lector.py      HDF-EOS5: descubre el cubo, los metadatos y escribe ENVI
  algoritmo.py   el algoritmo de Processing
  core/
    hdf5.py      el HDF-EOS5 como fuente del explorador, sin pasar por ENVI
    envi.py      cabecera ENVI y lectura por memoria mapeada
    sources.py   las otras fuentes: memoria y GDAL
    cube.py      HyperspectralCube: la API con dimensiones nombradas
    geo.py       conversión mapa ↔ píxel
    rgb.py       composición y realce
    colormap.py  paletas para pintar un plano del cubo
    bandas.py    qué banda entra al análisis y cuál no
    spectral.py  firmas, estadísticas, ángulo espectral
    library.py   biblioteca persistente
```

Las cuatro fuentes cumplen el mismo contrato —`shape`, `wavelengths`,
`read_pixel`, `read_band`, `read_window`, `close`—, y por eso agregar HDF-EOS5
fue llenar un hueco que el diseño ya dejaba y no reescribir el explorador.

### El modelo de datos no asume tres dimensiones

Hacia afuera no se ofrece `cubo[y, x, banda]` sino operaciones con nombre:

```python
cube.get_spectrum(x, y)
cube.get_band(wavelength=665)
cube.get_transect(axis="x", position=80)
cube.get_roi(x0, y0, x1, y1)
```

Hoy el cubo es `C(y, x, λ)`. Mañana puede ser `C(tiempo, λ, y, x)`. La API con
nombre deja esa puerta abierta sin reescribir a los consumidores.

## Uso del núcleo sin QGIS

```python
from hdfeos_extractor.core import HyperspectralCube, RGBComposer

with HyperspectralCube.load("escena.h5") as cubo:   # o "escena.hdr"
    print(cubo)                                     # dimensiones y rango
    espectro = cubo.get_spectrum(x=342, y=218)
    rojo = cubo.get_band(wavelength=665)
    columna = cubo.get_transect("x", 80)            # (fila, banda)
    rgb = RGBComposer(842, 665, 560).create_composite(cubo)
```

`load()` elige el lector solo: HDF-EOS5 por la **firma del archivo** —no por la
extensión, porque los productos circulan como `.h5`, `.he5`, `.hdf5` y a veces
sin sufijo útil—, después ENVI, y GDAL como respaldo.

Para verlo funcionando de punta a punta sobre una escena sintética:

```sh
python3 hdfeos_extractor/examples/demo_cube.py
```

## Qt5 y Qt6

QGIS se está moviendo a Qt6, y ahí los enums sin calificar —`Qt.Horizontal`,
`QSizePolicy.Expanding`— dejaron de existir. No fallan al importar: fallan al
abrir el panel, a media construcción de la interfaz.

Todos pasan por un resolutor que prueba la forma calificada primero y deja la
plana de respaldo, así que el mismo código corre en QGIS 3.16 y en Qt6. Dos
comprobaciones lo sostienen, y las dos están en `verificar.sh` y en CI:

- **`tests/test_qt6.py`** lee el árbol sintáctico del complemento entero y
  falla si encuentra un solo enum sin calificar.
- **`comprobar_qt6.py`** construye la interfaz con PyQt6 de verdad y la
  dibuja. Lo que el detector estático no vea, se cae al pintar.

## Pruebas

```sh
./verificar.sh     # pruebas, estilo y demo: lo mismo que corre el CI
python3 -m pytest  # sólo las pruebas
```

Corren también en cada empujón a GitHub, en **Python 3.9 y 3.12**. El 3.9 está
ahí a propósito: es el que traen las compilaciones de QGIS para macOS, y es
donde aparecería cualquier uso de sintaxis o de numpy posterior a esa versión.

Las del núcleo corren sin QGIS ni Qt. Las del gráfico, el cubo y el panel se
saltan solas si no hay enlaces de Qt; las de HDF-EOS5, si no hay `h5py`.

`tests/test_paquete.py` arma el ZIP con el script real y comprueba su forma:
una sola carpeta raíz, con nombre que sea un identificador de Python válido, y
`__init__.py` y `metadata.txt` directamente adentro. Existe porque esa forma se
rompió una vez y el error apareció en la máquina del usuario, que es el peor
lugar para enterarse.

La prueba que sostiene el diseño está en `tests/test_hdf5.py`: extrae un cubo
sintético a ENVI con el mismo código que usa el algoritmo y comprueba que
explorar el `.h5` y explorar el ENVI extraído devuelven **los mismos números,
píxel a píxel**. Si eso no se cumpliera, tener las dos rutas en una sola
herramienta sería peor que no tenerlas.

## Publicar una versión

El ciclo completo, desde un cambio hasta que aparece en el gestor de
complementos de QGIS:

1. Subir la versión en `hdfeos_extractor/metadata.txt` y describir el cambio
   en su `changelog`. Esa es la fuente: el ZIP toma de ahí su nombre y la
   etiqueta del *Release* tiene que coincidir.
2. `./verificar.sh` — pruebas, estilo, Qt6 y la demo.
3. Empujar a `main` y esperar a CI.
4. Lanzar el flujo **publicar** desde la pestaña *Actions*. Arma el ZIP,
   crea el *Release* y, si está el secreto, lo sube a plugins.qgis.org.

El secreto se llama **`QGIS_PLUGIN_TOKEN`**. Se crea en la página del
complemento en plugins.qgis.org y se guarda en *Settings → Secrets and
variables → Actions*. Sin él, el paso de subida se salta con un aviso y el
*Release* de GitHub se publica igual: siempre queda la vía manual.

Se sube **el mismo ZIP** que queda adjunto al *Release*, no uno armado
aparte. Lo que se descarga de GitHub y lo que se instala desde QGIS tienen
que ser byte por byte el mismo archivo, y es el que pasó las pruebas de
paquete.

### Las pruebas del paquete

`tests/test_paquete.py` comprueba la forma del ZIP, y dos de sus pruebas
existen por un fallo concreto: se publicó una versión sin uno de los módulos
porque el empaquetador tenía la lista escrita a mano. Ahora una compara el
ZIP contra los archivos **en disco** y la otra exige que todos los imports
relativos resuelvan dentro del ZIP. Una lista no puede comprobar a otra
lista.
