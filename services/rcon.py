"""
services/rcon.py - Cliente RCON minimalista (protocolo Source RCON usado por Minecraft).

Se usa para refrescar métricas (list, spark tps) sin escribir esos comandos en el
stdin de la consola interactiva: la respuesta de un comando ejecutado por RCON
viaja solo por este socket, así que no llena la consola en vivo con el reporte
de spark cada vez que se refrescan las métricas.

RconConnection mantiene un único socket autenticado reutilizado entre comandos
(en vez de abrir/cerrar uno por comando), porque Minecraft loguea una línea por
cada conexión/desconexión RCON en su consola/log ("Thread RCON Client ... started"
/ "shutting down") y con una conexión persistente eso pasa una sola vez por
sesión de servidor en vez de en cada refresco de métricas.
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


class RconConnection:
    """Conexión RCON persistente: autentica una vez y reutiliza el socket para
    sucesivos comandos, reconectando solo si la conexión se cae."""

    def __init__(self, host: str, port: int, password: str, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._req_id = 1

    def _authenticate(self):
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        try:
            _send_packet(sock, 1, SERVERDATA_AUTH, self.password.encode("utf-8"))
            req_id, ptype, _ = _read_packet(sock)
            if ptype != SERVERDATA_AUTH_RESPONSE:
                # Algunos servidores mandan un SERVERDATA_RESPONSE_VALUE vacío antes
                # del auth response; se lee un paquete extra para descartarlo.
                req_id, ptype, _ = _read_packet(sock)
            if req_id == -1:
                raise RconError("Autenticación RCON fallida (contraseña incorrecta)")
        except Exception:
            sock.close()
            raise
        self._sock = sock

    def _exec(self, command: str) -> str:
        self._req_id += 1
        _send_packet(self._sock, self._req_id, SERVERDATA_EXECCOMMAND, command.encode("utf-8"))
        _, _, body = _read_packet(self._sock)
        return body.decode("utf-8", errors="replace")

    def command(self, command: str) -> str:
        """Ejecuta un comando, reconectando de forma transparente si hace falta."""
        if self._sock is None:
            self._authenticate()
        try:
            return self._exec(command)
        except (OSError, RconError):
            self.close()
            self._authenticate()
            return self._exec(command)

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
