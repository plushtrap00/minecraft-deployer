"""
services/rcon.py - Cliente RCON minimalista (protocolo Source RCON usado por Minecraft).

Se usa para refrescar métricas (list, spark tps) sin escribir esos comandos en el
stdin de la consola interactiva: la respuesta de un comando ejecutado por RCON
viaja solo por este socket, así que no llena la consola en vivo con el reporte
de spark cada vez que se refrescan las métricas.
"""
import socket
import struct

SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0


class RconError(Exception):
    pass


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RconError("Conexión RCON cerrada inesperadamente")
        buf += chunk
    return buf


def _read_packet(sock: socket.socket):
    length = struct.unpack("<i", _recv_exact(sock, 4))[0]
    payload = _recv_exact(sock, length)
    req_id, ptype = struct.unpack("<ii", payload[:8])
    body = payload[8:-2]  # quita los dos bytes nulos finales
    return req_id, ptype, body


def _send_packet(sock: socket.socket, req_id: int, ptype: int, body: bytes):
    payload = struct.pack("<ii", req_id, ptype) + body + b"\x00\x00"
    sock.sendall(struct.pack("<i", len(payload)) + payload)


def rcon_command(host: str, port: int, password: str, command: str, timeout: float = 5.0) -> str:
    """Ejecuta un único comando por RCON y devuelve la respuesta como texto."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)

        _send_packet(sock, 1, SERVERDATA_AUTH, password.encode("utf-8"))
        req_id, ptype, _ = _read_packet(sock)
        if ptype != SERVERDATA_AUTH_RESPONSE:
            # Algunos servidores mandan un SERVERDATA_RESPONSE_VALUE vacío antes
            # del auth response; se lee un paquete extra para descartarlo.
            req_id, ptype, _ = _read_packet(sock)
        if req_id == -1:
            raise RconError("Autenticación RCON fallida (contraseña incorrecta)")

        _send_packet(sock, 2, SERVERDATA_EXECCOMMAND, command.encode("utf-8"))
        _, _, body = _read_packet(sock)
        return body.decode("utf-8", errors="replace")
