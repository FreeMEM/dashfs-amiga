"""Comprueba con lector.py que un disco de hacer_disco tiene lo de su manifiesto (prueba del lector de referencia)."""
import sys
from lector import DashFS, u16


def suma(data):
    s = 0
    for i, b in enumerate(data):
        s = (s + b * ((i % 251) + 1)) & 0xFFFFFFFF
    return s


def main(disco, manifiesto):
    fs = DashFS(disco)
    antes = DashFS(disco, instantanea="antes")
    malos = 0
    cambiados = {}
    borrados = set()
    lineas = open(manifiesto, encoding="utf-8").read().splitlines()
    for l in lineas:
        if l.startswith("N "):
            _, ruta, n, s = l.split(" ")
            cambiados[ruta] = (int(n), int(s))
        elif l.startswith("X "):
            borrados.add(l[2:])
    for l in lineas:
        tipo, resto = l[0], l[2:]
        if tipo == "F":
            ruta, n, s = resto.rsplit(" ", 2)
            # en la instantánea, como se escribió
            d = antes.datos(antes.buscar(ruta))
            if (len(d), suma(d)) != (int(n), int(s)):
                print("MAL (antes)", ruta); malos += 1
            if ruta in borrados:
                try:
                    fs.buscar(ruta); print("MAL: sigue", ruta); malos += 1
                except Exception:
                    pass
                continue
            d = fs.datos(fs.buscar(ruta))
            if (len(d), suma(d)) != cambiados.get(ruta, (int(n), int(s))):
                print("MAL", ruta); malos += 1
        elif tipo == "C":
            ruta, nota = resto.split("|")
            if fs.atributo(fs.buscar(ruta)).decode() != nota:
                print("MAL nota", ruta); malos += 1
        elif tipo == "V":
            vol, nombre = resto.split(" ", 1)
            otro = DashFS(disco, volumen=vol)
            if otro.datos(otro.buscar(nombre)) != b"en el volumen Otro\n":
                print("MAL volumen"); malos += 1
    print("Léeme sin mayúsculas:", fs.datos(fs.buscar("LÉEME.TXT"))[:10])
    print("Exacto/a:", fs.datos(fs.buscar("Exacto/a")), "Exacto/A:", fs.datos(fs.buscar("Exacto/A")))
    print("muchos:", len(fs.entradas(fs.buscar("Muchos"))))
    print("malos:", malos)
    return malos


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1], sys.argv[2]) else 0)
