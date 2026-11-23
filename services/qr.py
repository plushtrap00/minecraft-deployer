"""
services/qr.py - Códigos QR en SVG, sin dependencias.

Solo lo que hace falta para el enlace otpauth:// de la verificación en dos
pasos: modo byte, nivel de corrección M y versiones 1 a 10 (hasta 213
bytes). Sigue la norma ISO/IEC 18004; los tests lo comparan módulo a módulo
con la librería de referencia «qrcode» (solo instalada para comprobarlo, la
app no la necesita).
"""

# Por versión (nivel M): (codewords de corrección por bloque, [(bloques, datos por bloque), ...])
_BLOCKS_M = {
    1: (10, [(1, 16)]),
    2: (16, [(1, 28)]),
    3: (26, [(1, 44)]),
    4: (18, [(2, 32)]),
    5: (24, [(2, 43)]),
    6: (16, [(4, 27)]),
    7: (18, [(4, 31)]),
    8: (22, [(2, 38), (2, 39)]),
    9: (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}
_ALIGNMENT = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}
_REMAINDER_BITS = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}
_ECL_M_FORMAT_BITS = 0  # L=1, M=0, Q=3, H=2

# ── Reed-Solomon en GF(256) con el polinomio 0x11D ──────────────────────────
_EXP = [0] * 512
_LOG = [0] * 256
_value = 1
for _i in range(255):
    _EXP[_i] = _value
    _LOG[_value] = _i
    _value <<= 1
    if _value & 0x100:
        _value ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree: int) -> list:
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= coef
            nxt[j + 1] ^= _gf_mul(coef, _EXP[i])
        poly = nxt
    return poly


def _rs_remainder(data: list, degree: int) -> list:
    generator = _rs_generator(degree)
    result = [0] * degree
    for byte in data:
        factor = byte ^ result[0]
        result = result[1:] + [0]
        for i in range(degree):
            result[i] ^= _gf_mul(generator[i + 1], factor)
    return result


# ── Datos ──────────────────────────────────────────────────────────────────

def _choose_version(length: int) -> int:
    for version in range(1, 11):
        capacity = sum(count * size for count, size in _BLOCKS_M[version][1])
        count_bits = 8 if version < 10 else 16
        if 4 + count_bits + 8 * length <= capacity * 8:
            return version
    raise ValueError("Texto demasiado largo para el código QR")


def _codewords(data: bytes, version: int) -> list:
    ec_len, groups = _BLOCKS_M[version]
    capacity = sum(count * size for count, size in groups)
    bits = []

    def put(value: int, length: int) -> None:
        bits.extend((value >> i) & 1 for i in range(length - 1, -1, -1))

    put(0b0100, 4)
    put(len(data), 8 if version < 10 else 16)
    for byte in data:
        put(byte, 8)
    put(0, min(4, capacity * 8 - len(bits)))
    put(0, (-len(bits)) % 8)
    payload = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(payload) < capacity:
        payload.append(pad)
        pad ^= 0xEC ^ 0x11

    blocks, offset = [], 0
    for count, size in groups:
        for _ in range(count):
            block = payload[offset:offset + size]
            offset += size
            blocks.append((block, _rs_remainder(block, ec_len)))
    result = []
    for i in range(max(len(block) for block, _ in blocks)):
        result.extend(block[i] for block, _ in blocks if i < len(block))
    for i in range(ec_len):
        result.extend(ec[i] for _, ec in blocks)
    return result


# ── Matriz ─────────────────────────────────────────────────────────────────

class _Matrix:
    def __init__(self, version: int):
        self.version = version
        self.size = version * 4 + 17
        self.modules = [[False] * self.size for _ in range(self.size)]
        self.function = [[False] * self.size for _ in range(self.size)]

    def set_function(self, x: int, y: int, dark: bool) -> None:
        self.modules[y][x] = dark
        self.function[y][x] = True

    def draw_function_patterns(self) -> None:
        size = self.size
        for i in range(size):
            self.set_function(6, i, i % 2 == 0)
            self.set_function(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        self.set_function(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        positions = _ALIGNMENT[self.version]
        last = len(positions) - 1
        for i, px in enumerate(positions):
            for j, py in enumerate(positions):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_function(px + dx, py + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format_bits(0)
        if self.version >= 7:
            rem = self.version
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.version << 12 | rem
            for i in range(18):
                dark = (bits >> i) & 1 == 1
                a, b = size - 11 + i % 3, i // 3
                self.set_function(a, b, dark)
                self.set_function(b, a, dark)

    def draw_format_bits(self, mask: int) -> None:
        data = _ECL_M_FORMAT_BITS << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        size = self.size

        def bit(i: int) -> bool:
            return (bits >> i) & 1 == 1

        for i in range(6):
            self.set_function(8, i, bit(i))
        self.set_function(8, 7, bit(6))
        self.set_function(8, 8, bit(7))
        self.set_function(7, 8, bit(8))
        for i in range(9, 15):
            self.set_function(14 - i, 8, bit(i))
        for i in range(8):
            self.set_function(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_function(8, size - 15 + i, bit(i))
        self.set_function(8, size - 8, True)

    def draw_codewords(self, data: list) -> None:
        size = self.size
        total_bits = len(data) * 8
        i = 0
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = size - 1 - vert if upward else vert
                    if not self.function[y][x] and i < total_bits:
                        self.modules[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if self.function[y][x]:
                    continue
                if mask == 0:
                    invert = (x + y) % 2 == 0
                elif mask == 1:
                    invert = y % 2 == 0
                elif mask == 2:
                    invert = x % 3 == 0
                elif mask == 3:
                    invert = (x + y) % 3 == 0
                elif mask == 4:
                    invert = (x // 3 + y // 2) % 2 == 0
                elif mask == 5:
                    invert = x * y % 2 + x * y % 3 == 0
                elif mask == 6:
                    invert = (x * y % 2 + x * y % 3) % 2 == 0
                else:
                    invert = ((x + y) % 2 + x * y % 3) % 2 == 0
                if invert:
                    self.modules[y][x] = not self.modules[y][x]

    def penalty(self) -> int:
        """Puntuación de la norma para elegir la máscara (menos es mejor)."""
        size, modules, score = self.size, self.modules, 0
        lines = [row for row in modules] + [[modules[y][x] for y in range(size)] for x in range(size)]
        finder_a = [True, False, True, True, True, False, True, False, False, False, False]
        finder_b = finder_a[::-1]
        for line in lines:
            run, color = 1, line[0]
            for value in line[1:]:
                if value == color:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + run - 5
                    run, color = 1, value
            if run >= 5:
                score += 3 + run - 5
            for i in range(size - 10):
                window = line[i:i + 11]
                if window == finder_a or window == finder_b:
                    score += 40
        for y in range(size - 1):
            for x in range(size - 1):
                color = modules[y][x]
                if color == modules[y][x + 1] == modules[y + 1][x] == modules[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(row) for row in modules)
        total = size * size
        score += max(0, (abs(dark * 20 - total * 10) + total - 1) // total - 1) * 10
        return score


def matrix(text: str, mask: int | None = None, version: int | None = None) -> list:
    """Matriz de módulos (True = oscuro), sin margen. mask/version: forzarlos (tests)."""
    data = text.encode("utf-8")
    version = version or _choose_version(len(data))
    codewords = _codewords(data, version)
    best, best_score = None, None
    for candidate in ([mask] if mask is not None else range(8)):
        qr = _Matrix(version)
        qr.draw_function_patterns()
        qr.draw_codewords(codewords)
        qr.apply_mask(candidate)
        qr.draw_format_bits(candidate)
        score = qr.penalty() if mask is None else 0
        if best_score is None or score < best_score:
            best, best_score = qr, score
    # Los bits sobrantes del final (_REMAINDER_BITS) se quedan claros: ya lo están.
    return best.modules


def svg(text: str, border: int = 4) -> str:
    """El código QR como SVG (negro sobre blanco, para que cualquier cámara lo lea)."""
    modules = matrix(text)
    size = len(modules) + border * 2
    path = "".join(
        f"M{x + border},{y + border}h1v1h-1z"
        for y, row in enumerate(modules) for x, dark in enumerate(row) if dark
    )
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges" '
            f'role="img"><rect width="{size}" height="{size}" fill="#fff"/><path d="{path}" fill="#000"/></svg>')
