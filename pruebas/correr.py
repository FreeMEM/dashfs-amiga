#!/usr/bin/env python3
"""La prueba del handler de DashFS en FS-UAE: hace un disco con herramientas/hacer_disco (8 MB), compila el handler
(por el camino directo de Dash, o --gcc) y el cliente, arranca un A1200 emulado con el disco como uaehf.device unidad
1 y compara lo que ve el cliente con el manifiesto del disco.

    python3 pruebas/correr.py [--gcc] [--dash RUTA_DE_DASH]

Necesita el entorno del emulador de Dash ($DASH_KICKSTART, $DASH_EMU_SYS con C/Mount) y cargo."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AQUI / "herramientas"))


def suma(data):
    s = 0
    for i, b in enumerate(data):
        s = (s + b * ((i % 251) + 1)) & 0xFFFFFFFF
    return s


def hexs(s):
    return f"{(s >> 16) & 0xFFFF:x}:{s & 0xFFFF:x}"


def esperado(manifiesto):
    """Las líneas que debe dar el recorrido de cada montaje"""
    ahora, antes, otro = set(), set(), set()
    cambiados, borrados = {}, set()
    lineas = manifiesto.read_text(encoding="utf-8").splitlines()
    for l in lineas:
        if l.startswith("N "):
            _, ruta, n, s = l.split(" ")
            cambiados[ruta] = (int(n), int(s))
        elif l.startswith("X "):
            borrados.add(l[2:])
    for l in lineas:
        tipo, resto = l[0], l[2:]
        if tipo == "D":
            antes.add(f"DFS1 D {resto}")
            ahora.add(f"DFS0 D {resto}")
        elif tipo == "F":
            ruta, n, s = resto.rsplit(" ", 2)
            antes.add(f"DFS1 F {ruta} {n} {hexs(int(s))}")
            if ruta not in borrados:
                n2, s2 = cambiados.get(ruta, (int(n), int(s)))
                ahora.add(f"DFS0 F {ruta} {n2} {hexs(s2)}")
        elif tipo == "V":
            otro.add(f"DFS2 F del otro.txt 19 {hexs(suma(b'en el volumen Otro' + bytes([10])))}")
    return ahora | antes | otro


def main():
    args = sys.argv[1:]
    dash = Path(args[args.index("--dash") + 1]) if "--dash" in args else Path.home() / "Projects/FreeMEMLang/dash"
    por_c = ["--gcc"] if "--gcc" in args else []
    with tempfile.TemporaryDirectory(prefix="dashfs_") as tmp:
        tmp = Path(tmp)
        subprocess.run(["cargo", "build", "--release", "-q"], cwd=AQUI / "herramientas", check=True)
        hacer = AQUI / "herramientas" / "target" / "release" / "hacer_disco"
        subprocess.run([hacer, tmp / "disco.img", tmp / "manifiesto.txt", "8"], check=True, stdout=subprocess.DEVNULL)
        quiere = esperado(tmp / "manifiesto.txt")
        handler = tmp / "dashfs-handler"
        subprocess.run([dash, *por_c, "--cpu", "68020", AQUI / "src" / "dashfs.dash", "-o", handler], check=True)
        cliente = tmp / "cliente"
        subprocess.run([dash, *por_c, "--cpu", "68020", AQUI / "pruebas" / "cliente.dash", "-o", cliente], check=True)
        emu = dash.resolve().parent / "tools" / "emu_run.py"
        r = subprocess.run([sys.executable, emu, "--timeout", "1200", "--file", handler,
                            "--set", f"hard_drive_1={tmp / 'disco.img'}", "--set", "hard_drive_1_type=rdb", cliente],
                           capture_output=True)
    salida = [l.rstrip() for l in r.stdout.decode("utf-8", "replace").splitlines()]   # (emu_run: en UTF-8)
    vistas = {l for l in salida if l[:4] in ("DFS0", "DFS1", "DFS2")}
    for l in salida:
        if l[:4] not in ("DFS0", "DFS1", "DFS2"):
            print(l)
    faltan, sobran = sorted(quiere - vistas), sorted(vistas - quiere)
    for l in faltan[:20]:
        print("FALTA", l)
    for l in sobran[:20]:
        print("SOBRA", l)
    print(f"recorrido: {len(vistas & quiere)} de {len(quiere)} bien, {len(faltan)} faltan, {len(sobran)} sobran")
    return 1 if faltan or sobran else 0


if __name__ == "__main__":
    sys.exit(main())
