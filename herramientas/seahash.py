"""seahash 4.1 (el de RedoxFS/DashFS) en Python: la referencia de las pruebas del handler."""
M = (1 << 64) - 1
K = 0x6eed0e9da4d94a4f


def diffuse(x):
    x = (x * K) & M
    x ^= (x >> 32) >> (x >> 60)
    return (x * K) & M


def seahash(buf: bytes) -> int:
    st = [0x16f11fe89b0d677c, 0xb480a793d8e6c86c, 0x6fe2e5aaf078ebc9, 0x14f994a4c5259381]
    n = len(buf)
    lane = 0
    for i in range(0, n, 8):
        w = int.from_bytes(buf[i:i + 8].ljust(8, b"\0"), "little")
        st[lane] = diffuse(st[lane] ^ w)
        lane = (lane + 1) & 3
    a = st[0] ^ st[1] ^ st[2] ^ st[3] ^ n
    return diffuse(a)


if __name__ == "__main__":
    assert diffuse(94203824938) == 17289265692384716055
    assert diffuse(0xDEADBEEF) == 12110756357096144265
    assert diffuse(1) == 15197155197312260123
    import sys
    if len(sys.argv) > 1:   # la cabecera 0 de un disco: su suma es la de sus primeros 4072 bytes
        d = open(sys.argv[1], "rb").read(4096)
        print(hex(seahash(d[:4072])), hex(int.from_bytes(d[4088:4096], "little")))
    print("bien")
