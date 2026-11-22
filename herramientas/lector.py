"""Un lector de DashFS de solo lectura en Python: la referencia del handler del Amiga (src/dashfs.dash) y de sus
pruebas. Hace lo mismo y en el mismo orden: la cabecera más nueva del anillo, el árbol de nodos, las carpetas (H-tree),
los registros de los ficheros (LZ4, sumas seahash), los atributos (el comentario), las instantáneas y los volúmenes.

    python3 lector.py disco.img [--volumen NOMBRE] [--instantanea NOMBRE] ls RUTA | cat RUTA | arbol
"""
import struct
import sys

from seahash import seahash

BLOCK = 4096
HEADER_RING = 256


class Roto(Exception):
    pass


def u16(b, o): return struct.unpack_from("<H", b, o)[0]
def u32(b, o): return struct.unpack_from("<I", b, o)[0]
def u64(b, o): return struct.unpack_from("<Q", b, o)[0]


def lz4(src: bytes, maximo: int) -> bytes:
    """Un bloque LZ4 (sin marco), como lz4_flex::decompress_into"""
    out = bytearray()
    i = 0
    while i < len(src):
        token = src[i]; i += 1
        n = token >> 4
        if n == 15:
            while True:
                x = src[i]; i += 1; n += x
                if x != 255:
                    break
        out += src[i:i + n]; i += n
        if i >= len(src):
            break
        off = src[i] | (src[i + 1] << 8); i += 2
        if off == 0 or off > len(out):
            raise Roto("lz4: desplazamiento malo")
        m = token & 15
        if m == 15:
            while True:
                x = src[i]; i += 1; m += x
                if x != 255:
                    break
        m += 4
        for _ in range(m):
            out.append(out[-off])
    if len(out) > maximo:
        raise Roto("lz4: más de lo que cabe")
    return bytes(out)


class Ptr:
    """Un BlockPtr: dirección (nivel, nivel descomprimido, índice, época) y suma"""
    def __init__(self, b, o):
        self.raw = u64(b, o)
        self.hash = u64(b, o + 8)
        self.level = self.raw & 15
        self.decomp = (self.raw >> 4) & 15
        self.index = (self.raw >> 8) & ((1 << 36) - 1)

    def null(self):
        return self.index == 0

    def marker(self):
        return (self.raw | 15) == (1 << 64) - 1 and self.hash == (1 << 64) - 1


class DashFS:
    def __init__(self, path, volumen=None, instantanea=None):
        self.f = open(path, "rb")
        self.cabecera()
        if volumen:
            self.entrar_volumen(volumen)
        if instantanea:
            self.entrar_instantanea(instantanea)

    def leer(self, index, n=BLOCK):
        self.f.seek(index * BLOCK)
        return self.f.read(n)

    def bloque(self, p: Ptr) -> bytes:
        if p.null():
            raise Roto("puntero nulo")
        data = self.leer(p.index, BLOCK << p.level)
        if seahash(data) != p.hash:
            raise Roto(f"suma mala en el bloque {p.index}")
        return data

    def registro(self, p: Ptr, level: int) -> bytes:
        """Un registro de datos: descomprimido y del tamaño de su nivel (lo que falta, a ceros)"""
        if p.null():
            return bytes(BLOCK << level)
        data = self.bloque(p)
        if p.decomp:
            n = u16(data, 0)
            data = lz4(data[2:2 + n], BLOCK << p.decomp)
            data = data.ljust(BLOCK << p.decomp, b"\0")
        return data.ljust(BLOCK << level, b"\0")

    def cabecera(self):
        mejor = None
        for i in range(HEADER_RING):
            h = self.leer(i)
            if h[:8] not in (b"DashFS\0\0", b"RedoxFS\0"):
                continue
            gen = u64(h, 40)
            if mejor is None or gen > mejor[0]:
                if seahash(h[:4072]) == u64(h, 4088):
                    mejor = (gen, h)
        if not mejor:
            raise Roto("no hay cabecera DashFS")
        h = mejor[1]
        self.version = u64(h, 8)
        self.size = u64(h, 32)
        self.tree = Ptr(h, 48)
        # alloc 64, key_slots 80: 64 huecos de 48 bytes (salt 16 + key 16? ) -> ver más abajo
        o = 80 + 64 * self.tamano_hueco()
        self.release = Ptr(h, o)
        self.epoch = u64(h, o + 16)
        self.latest = u64(h, o + 24)
        self.snapshots = Ptr(h, o + 32)
        self.dead = Ptr(h, o + 48)
        self.volumes = Ptr(h, o + 64)

    @staticmethod
    def tamano_hueco():
        return 48   # KeySlot: salt [u8;32] + encrypted_key [u8;16] (key.rs)

    def entrar_volumen(self, nombre):
        p = self.volumes
        while not p.null():
            b = self.bloque(p)
            for k in range((BLOCK - 16) // 208):
                o = 16 + k * 208
                n = b[o + 136]
                nom = b[o + 144:o + 144 + n].decode()
                if n and nom == nombre:
                    if u32(b, o + 100) & 1:
                        raise Roto("volumen cifrado")
                    self.tree = Ptr(b, o + 8)
                    self.snapshots = Ptr(b, o + 48)
                    return
            p = Ptr(b, 0)
        raise Roto(f"no hay volumen {nombre}")

    def entrar_instantanea(self, nombre):
        p = self.snapshots
        while not p.null():
            b = self.bloque(p)
            for k in range((BLOCK - 16) // 136):
                o = 16 + k * 136
                n = b[o + 20]
                if n and b[o + 72:o + 72 + n].decode() == nombre:
                    self.tree = Ptr(b, o + 24)
                    return
            p = Ptr(b, 0)
        raise Roto(f"no hay instantánea {nombre}")

    def nodo(self, nid: int) -> bytes:
        """El nodo nid (TreePtr): cuatro niveles de TreeList, de 8 bits cada uno"""
        b = self.bloque(self.tree)
        for shift in (24, 16, 8):
            b = self.bloque(Ptr(b, ((nid >> shift) & 255) * 16))
        return self.bloque(Ptr(b, (nid & 255) * 16))

    def entradas(self, nid):
        """(nombre, nodo) de una carpeta, recorriendo todo su H-tree"""
        n = self.nodo(nid)
        if u16(n, 0) & 0xF000 != 0x4000:
            raise Roto("no es una carpeta")
        marca = Ptr(n, 128)
        if not marca.marker():
            return []
        niveles = marca.level
        raiz = Ptr(n, 144)
        out = []

        def hojas(p, nivel):
            if nivel == 0:
                d = self.bloque(p)
                cuenta = u16(d, 4092)
                o = 0
                for _ in range(cuenta):
                    hijo = u32(d, o)
                    largo = d[o + 4]
                    out.append((d[o + 5:o + 5 + largo].decode("utf-8", "replace"), hijo))
                    o += 5 + largo
            else:
                b = self.bloque(p)
                for k in range(BLOCK // 20):
                    q = Ptr(b, k * 20 + 4)
                    if not q.null():
                        hojas(q, nivel - 1)
        hojas(raiz, niveles)
        return out

    def datos(self, nid) -> bytes:
        n = self.nodo(nid)
        size = u64(n, 14)
        flags = u32(n, 70)
        if flags & 1:   # INLINE_DATA
            return n[128:128 + size]
        level = u32(n, 66)
        rsize = BLOCK << level
        out = bytearray()
        r = 0
        while len(out) < size:
            out += self.registro(self.puntero_registro(n, r), level)
            r += 1
        return bytes(out[:size])

    def puntero_registro(self, n, r) -> Ptr:
        """El BlockPtr del registro r: 128 directos, luego listas de 1 a 4 niveles (NodeLevel::new)"""
        base = 128
        if r < 128:
            return Ptr(n, base + r * 16)
        r -= 128
        for nivel, cuantos, sitio in ((1, 64, 128), (2, 32, 192), (3, 16, 224), (4, 8, 240)):
            alcance = cuantos << (8 * nivel)
            if r < alcance:
                p = Ptr(n, base + (sitio + (r >> (8 * nivel))) * 16)
                for k in range(nivel - 1, -1, -1):
                    if p.null():
                        return p
                    b = self.bloque(p)
                    p = Ptr(b, ((r >> (8 * k)) & 255) * 16)
                return p
            r -= alcance
        raise Roto("fichero demasiado grande")

    def atributo(self, nid, clave=b"amiga.comment"):
        n = self.nodo(nid)
        p = Ptr(n, 78)
        if p.null():
            return None
        b = self.bloque(p)
        largo = u16(b, 0)
        o = 2
        while o + 3 <= 2 + largo:
            kl = b[o]; vl = u16(b, o + 1)
            k = b[o + 3:o + 3 + kl]; v = b[o + 3 + kl:o + 3 + kl + vl]
            if k == clave:
                return v
            o += 3 + kl + vl
        return None

    def buscar(self, ruta):
        nid = 1
        for parte in [p for p in ruta.split("/") if p]:
            n = self.nodo(nid)
            sin_mayus = u32(n, 70) & 2
            for nombre, hijo in self.entradas(nid):
                if nombre == parte or (sin_mayus and nombre.casefold() == parte.casefold()):
                    nid = hijo
                    break
            else:
                raise Roto(f"no existe {parte}")
        return nid


def main():
    args = sys.argv[1:]
    vol = inst = None
    if "--volumen" in args:
        i = args.index("--volumen"); vol = args[i + 1]; del args[i:i + 2]
    if "--instantanea" in args:
        i = args.index("--instantanea"); inst = args[i + 1]; del args[i:i + 2]
    fs = DashFS(args[0], vol, inst)
    orden = args[1]
    if orden == "ls":
        for nombre, hijo in fs.entradas(fs.buscar(args[2] if len(args) > 2 else "")):
            n = fs.nodo(hijo)
            print(("D " if u16(n, 0) & 0xF000 == 0x4000 else "F ") + nombre, u64(n, 14))
    elif orden == "cat":
        sys.stdout.buffer.write(fs.datos(fs.buscar(args[2])))
    elif orden == "nota":
        print(fs.atributo(fs.buscar(args[2])))


if __name__ == "__main__":
    main()
