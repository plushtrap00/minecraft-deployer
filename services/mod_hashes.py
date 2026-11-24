"""
mod_hashes.py - Huella (fingerprint) de CurseForge de un archivo.

La usan la búsqueda de actualizaciones (services/mod_updates.py) y la de
dependencias que faltan (services/mod_dependencies.py) para reconocer cada jar
con POST /v1/fingerprints/{gameId}.
"""
import sys
from array import array


def curseforge_fingerprint(data: bytes) -> int:
    """
    MurmurHash2 (32 bits, semilla 1) del archivo sin los bytes de espacio en
    blanco 9/10/13/32: así lo calcula el propio cliente de CurseForge.
    """
    data = data.translate(None, b"\t\n\r ")
    n = len(data)
    m, mask = 0x5BD1E995, 0xFFFFFFFF
    h = (1 ^ n) & mask
    body = n - (n & 3)
    # Los bloques de 4 bytes se leen de golpe como enteros little-endian:
    # bastante más rápido que montarlos byte a byte en un jar de varios MB.
    words = array("I")
    words.frombytes(data[:body])
    if sys.byteorder != "little":
        words.byteswap()
    for k in words:
        k = (k * m) & mask
        k ^= k >> 24
        k = (k * m) & mask
        h = ((h * m) & mask) ^ k
    tail, rest = data[body:], n & 3
    if rest == 3:
        h ^= tail[2] << 16
    if rest >= 2:
        h ^= tail[1] << 8
    if rest >= 1:
        h ^= tail[0]
        h = (h * m) & mask
    h ^= h >> 13
    h = (h * m) & mask
    h ^= h >> 15
    return h
