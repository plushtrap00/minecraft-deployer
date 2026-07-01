"""
services/lifecycle.py - Señal de apagado compartida por los endpoints SSE.

Los streams de la consola y del panel de sistema son bucles que nunca terminan
por sí solos. Sin esto, un `systemctl restart` tiene que esperar a que systemd
agote su timeout y mande SIGKILL, porque uvicorn no puede saber que esas
conexiones deben cortarse. shutdown_event se activa desde el hook de apagado
de FastAPI (main.py) y cada bucle lo comprueba para salir en cuanto se activa.
"""
import asyncio

shutdown_event = asyncio.Event()
