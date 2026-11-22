# DashFS para AmigaOS 3.x

Un handler de DOS de solo lectura para leer en un Amiga los discos DashFS (el sistema de archivos de DashOS) hechos en
DashOS o en Linux. Está escrito en Dash, con el modo handler (`./dash --handler`, que pone `lib/amiga/handler.dash`).
Idea del usuario.

Lee: la cabecera más nueva del anillo, el árbol de nodos, las carpetas H-tree, los ficheros (registros con LZ4 o sin
comprimir, datos dentro del nodo, huecos), las sumas seahash de todo lo que lee, los nombres sin distinguir mayúsculas
(en las carpetas que lo piden), el comentario y los bits del Amiga, las instantáneas y los volúmenes. No lee los
volúmenes cifrados ni los discos RedoxFS cifrados enteros. Necesita un 68020 o más y unos 2 MB de memoria libre.

## Compilar

```
./dash --cpu 68020 src/dashfs.dash -o L:DashFS-handler        # desde el repo de Dash, o con su ruta
```

## Montar

Una mountlist con la geometría de la partición (el disco DashFS empieza en el primer bloque de la partición):

```
DFS0:
    FileSystem = L:DashFS-handler
    Device = scsi.device
    Unit = 1
    Surfaces = 1
    BlocksPerTrack = 32
    Reserved = 0
    LowCyl = 0
    HighCyl = 1023
    BlockSize = 512
    Buffers = 5
    DosType = 0x44465301
    GlobVec = -1
    StackSize = 16384
    Control = "LOG=T:dfs0.log"
    Activate = 1
#
```

Opciones de `Control` (separadas por espacios, todas opcionales):

| Opción | Qué hace |
|---|---|
| `VOLUMEN=nombre` | Otro volumen del disco (sin él, el principal) |
| `INSTANTANEA=nombre` | Lo que había en esa instantánea (sin ella, lo de ahora) |
| `NOMBRE=nombre` | El nombre del volumen en el Amiga ("DashFS", el del volumen, o "volumen instantánea") |
| `SINSUMAS` | No comprueba las sumas de los datos de los ficheros (las de la estructura sí): más rápido |
| `LOG=ruta` | Un registro de lo que pasa (nunca en el propio disco DashFS) |

Los nombres en UTF-8 se ven en Latin-1; un carácter que Latin-1 no tiene sale como algo parecido o `?`.

## Pruebas

- `herramientas/`: `hacer_disco` (Rust, con el RedoxFS de DashOS en `../dashos/archivos/redoxfs`) hace un disco con
  de todo y su manifiesto; `lector.py` es un lector de referencia en Python; `comprobar.py` lo comprueba con el
  manifiesto; `seahash.py`, la suma.
- `pruebas/correr.py`: arranca un A1200 emulado (FS-UAE, el entorno del emulador de Dash) con el disco, monta el
  handler tres veces (ahora, la instantánea y el otro volumen) y compara lo que ve un cliente con el manifiesto.
  `--gcc` lo compila por C.
- `pruebas/prueba_seahash.dash` y `pruebas/prueba_lz4.dash`: las piezas en ensamblador contra la referencia.

Plan y bitácora: `docs/HANDLER_LOOP.md` del repo de Dash.
