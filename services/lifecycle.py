"""
services/lifecycle.py - Señal de apagado compartida por los endpoints SSE.

shutdown_event se activa desde el hook de apagado de FastAPI (main.py), y cada
bucle SSE lo comprueba para salir en cuanto se activa. OJO: uvicorn dispara
ese hook recién DESPUÉS de esperar a que las conexiones existentes se cierren
solas (hasta timeout_graceful_shutdown, ver main.py), así que para el caso de
un `systemctl restart` esta señal llega tarde para acortar esa espera — lo que
realmente la acota es ese timeout bajo. Esta señal sigue siendo útil para que
los bucles corten limpio (en vez de por una CancelledError abrupta) en el
resto de casos en que sí llegan a tiempo, por ejemplo si las conexiones ya se
habían cerrado solas antes de que se cumpla el timeout.
"""
import asyncio

shutdown_event = asyncio.Event()
