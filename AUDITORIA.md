# Auditoría — Minecraft Server Deployer

Informe priorizado (crítico / alto / medio / bajo) de backend, frontend, arquitectura,
infraestructura, seguridad y estilo. Generado repasando `main.py`, `config.py`, todo
`routes/` y `services/`, todo `static/js/` y `static/css/`, scripts de despliegue
(`Dockerfile`, `docker-compose.yml`, `install.sh`, `setup.py`) e historial de git.

**No se modificó ningún archivo del proyecto para este informe.** Solo el bloque 6
(estilo) queda pendiente de aplicar tras confirmación explícita.

---

## Crítico (arreglar ya)

### 1. El JWT_SECRET de ejemplo es una clave real y sirve para forjar tokens
**Archivos:** `.env.example:5`, `routes/auth.py` · **Esfuerzo:** bajo

`.env.example` trae un secreto ya generado (64 hex reales), commiteado, con un
comentario de "no cambiar en producción". Cualquier instalación que no lo sobrescriba
comparte una clave de firma pública — cualquiera puede forjar un JWT con `role: admin`
sin saber la contraseña de nadie.

### 2. `server_start` ejecuta un script sin validar el nombre de modpack
**Archivos:** `routes/server.py:51-118` · **Esfuerzo:** alto

`modpack` llega como segmento de path arbitrario y arma `server_dir` sin ningún
`.resolve().relative_to()` — el único endpoint de la app que se saltó ese chequeo.
Con `modpack=".."` (u otro nombre de carpeta hermana), el server arranca cualquier
`startserver.sh`/`start.sh`/`run.sh` que encuentre fuera de `DEFAULT_SERVERS_PATH`.
Es el hallazgo más grave de toda la auditoría.

### 3. Casi ningún endpoint comprueba el rol de admin
**Archivos:** `routes/modpacks.py` (firewall_router), `routes/server.py`, `routes/users.py` (única excepción) · **Esfuerzo:** medio

Solo `routes/users.py` revisa `request.state.role`. Prender/apagar el server, borrar
mundos, instalar mods, cambiar de modloader y — el más serio — abrir el firewall al
público, están disponibles para cualquier cuenta con rol `"user"`.

### 4. Inyección de comandos de consola vía gestión de jugadores
**Archivos:** `routes/players.py` (add_op, ban_player, ban_ip, etc.), `services/players.py:109-127` · **Esfuerzo:** medio

`name`/`ip`/`reason` nunca se validan. Un valor con salto de línea se cuela como
comando adicional al stdin del proceso de Minecraft — cualquier usuario autenticado
puede inyectar `stop`, banear a un admin, o cualquier otro comando de consola.

### 5. Minecraft se mata con SIGKILL cada vez que el panel se reinicia
**Archivos:** `main.py:139-173` (kill_orphan_servers), `routes/server.py:138-152` (stop), `main.py:99-132` (kill_port) · **Esfuerzo:** medio

Tres sitios distintos matan el proceso con `-9` sin intentar `save-all`/`stop` antes.
El más grave: `kill_orphan_servers` corre en **cada arranque del panel**, así que
reiniciar el panel (un `systemctl restart` normal) mata en frío cualquier partida en
curso — riesgo real de corrupción de mundo.

### 6. Sin protección de fuerza bruta y contraseñas de 3 caracteres
**Archivos:** `routes/auth.py:56-62` (login), `routes/users.py:44` (create_user) · **Esfuerzo:** bajo-medio

El login no tiene límite de intentos, bloqueo ni demora. Combinado con que
`create_user` acepta contraseñas de solo 3 caracteres (el admin exige 8 vía
`install.sh`/`setup.py`, las cuentas normales no), una cuenta "user" es trivial de
adivinar por fuerza bruta.

### 7. El fallback de extracción RAR arma un comando de shell con paths sin sanitizar
**Archivos:** `services/utils.py:206` · **Esfuerzo:** medio

`os.system(f"unrar x '{archive_path}' ...")` interpola `folder_name` (input de
usuario) directo en un string de shell. Un valor con una comilla simple rompe el
escapado. Solo se dispara si falta el paquete `rarfile`, pero cuando se dispara es
inyección de shell real.

---

## Alto (siguiente en la cola)

### 8. E/S bloqueante en rutas async, incluidas TODAS las llamadas HTTP salientes
**Archivos:** `routes/modpacks.py`, `routes/server.py`, `routes/system.py`, `services/mod_search.py`, `services/modloader.py` · **Esfuerzo:** medio

Decenas de sitios hacen lectura/escritura de disco o `urllib.request` síncrono dentro
de `async def` sin `asyncio.to_thread` — incluida **cada** llamada a
Modrinth/CurseForge/Forge/Fabric/Quilt. Uvicorn corre en un solo proceso: una API
externa lenta congela toda la app, incluida la consola en vivo de otros usuarios.

### 9. Cero tests automatizados en todo el proyecto
**Archivos:** — (no existe carpeta `tests/`, ni pytest en `requirements.txt`) · **Esfuerzo:** medio (base) / alto (cobertura real)

Las guardas de path-traversal, el manejo de RCON/procesos, y el parseo de
compatibilidad de versiones (la lógica más intrincada del repo, en
`services/modpack.py`) dependen 100% de que se pruebe a mano cada vez.

### 10. Sin rate limiting en ningún endpoint
**Archivos:** — (ninguna dependencia de rate limiting en `requirements.txt`) · **Esfuerzo:** medio

Login, SSE, y el proxy a las APIs de mods no tienen límite alguno, expuesto vía
túnel público.

### 11. `routes/modpacks.py` es un god-file de 6 dominios sin relación
**Archivos:** `routes/modpacks.py` (799 líneas, 3 routers) · **Esfuerzo:** medio

Server.properties, config files, KubeJS, subida de mods, mundos, y firewall conviven
en un archivo. El firewall en particular no tiene nada que ver conceptualmente con
"modpacks" — probablemente por eso se le olvidó el chequeo de rol de admin (ver
crítico #3).

### 12. Duplicación pesada en el backend
**Archivos:** `routes/modpacks.py` (guarda de path repetida 15 veces), `services/utils.py` + `services/modpack.py` (caché por mtime repetida 4 veces), `services/modpack.py` (iteración de jars repetida 5+ veces) · **Esfuerzo:** bajo-medio por caso

La misma guarda de path-traversal (`.resolve().relative_to()` + `except ValueError`)
está copiada literalmente 15 veces. Un bug en esa lógica (o un futuro endpoint que la
copie mal) reabre el traversal en cualquier sitio nuevo.

### 13. Triplicación de la lógica de árbol/filtro/paginación en el frontend
**Archivos:** `static/js/manage.js:583-691` (configs y KubeJS), `static/js/worlds.js:234-399` (archivos de mundo) · **Esfuerzo:** alto

La misma ~90 líneas de estado (claves filtradas, página activa, filtro activo) y
funciones (ordenar, filtrar, renderizar página) están reimplementadas una tercera vez
casi idéntica. La limpieza de mayor valor en todo el frontend.

### 14. Sin logging estructurado en absoluto
**Archivos:** — (cero `import logging` en todo el proyecto) · **Esfuerzo:** medio

Solo `print()` sueltos, y docenas de `except Exception: pass` silenciosos que borran
cualquier rastro de un fallo real de ufw, RCON, o escritura de archivo. Depurar
producción es prácticamente imposible así.

### 15. `server.py` en la raíz (1734 líneas) es código muerto
**Archivos:** `server.py` · **Esfuerzo:** bajo

Confirmado de forma independiente por dos revisiones distintas: nadie lo importa, y
Dockerfile/start.sh/install.sh arrancan todos `main.py`. Duplica peor (sin auth, sin
threading, sin caché) lo que ya vive en `services/`. Candidato claro a borrar —
pendiente confirmación, no se tocó.

### 16. Sin cabeceras de seguridad
**Archivos:** `main.py` · **Esfuerzo:** bajo

Nada de CSP, HSTS, X-Frame-Options ni X-Content-Type-Options, pese a estar expuesto
por Cloudflare Tunnel con dominio propio.

### 17. Sin reataduración de proceso si el panel se reinicia con el server vivo
**Archivos:** `services/process.py`, `main.py:139-173` · **Esfuerzo:** alto

El estado del proceso vive solo en memoria (sin PID file). Si el panel se reinicia,
pierde todo rastro del proceso — la única "recuperación" es el SIGKILL de
`kill_orphan_servers` (mismo problema que el crítico #5, misma causa raíz).

---

## Medio (vale la pena, sin urgencia)

### 18. Faltan cachés donde el mismo patrón ya existe al lado
**Archivos:** `services/modpack.py` (get_worlds, find_possible_duplicate_mods), `routes/modpacks.py` (list_mods, detected-mods) · **Esfuerzo:** bajo-medio

`get_worlds()` recalcula un tamaño recursivo de disco en cada llamada;
`find_possible_duplicate_mods` re-parsea todos los jars sin caché pese a que
`build_mod_id_index` (usado por la búsqueda de mods) cachea datos casi idénticos al
lado.

### 19. Caché de frontend inconsistente entre secciones
**Archivos:** `static/js/manage.js`, `players.js`, `users.js`, `worlds.js` (sin caché) vs. `mods.js` (LRU + blobs) · **Esfuerzo:** bajo-medio

La búsqueda de mods tiene un LRU y una caché de bytes de íconos bien pensados;
modpacks, jugadores, usuarios y mundos se re-piden enteros en cada click de pestaña
sin ningún equivalente.

### 20. Debounce faltante en varios buscadores del panel
**Archivos:** `#mods-search`, `#mod-search` (árbol de configs), `#wf-search`, `#kubejs-search` · **Esfuerzo:** bajo

Re-renderizan la lista completa en cada tecla, a diferencia de la búsqueda online
(400ms) y de logs (200ms). Con un modpack de 300-500 mods se nota al escribir.

### 21. players.js y users.js divergen del patrón de loading/error establecido
**Archivos:** `static/js/players.js:2-14`, `static/js/users.js:29-43`, `static/js/server.js:124-132` · **Esfuerzo:** bajo-medio

Sin reset de "cargando" al refrescar; `deleteUser` no tiene ningún `.catch` (rechazo
sin manejar); el chequeo de estado de firewall en server.js falla en silencio.

### 22. El panel de sistema es el único stream SSE sin reconexión
**Archivos:** `static/js/sysmon.js:42` · **Esfuerzo:** bajo

Todos los demás consumidores de SSE (consola, subida masiva, instalador de modloader)
tienen `onerror` con reintento. Este no — si se corta, el panel de sistema se
congela para siempre en los últimos valores.

### 23. La subida de modpacks no avisa antes de cerrar la pestaña
**Archivos:** `static/js/deploy.js` · **Esfuerzo:** bajo

A diferencia de `mods.js`, nada impide cerrar o navegar fuera mientras se sube/extrae
un modpack de cientos de MB — la acción más disruptiva de interrumpir de toda la app.

### 24. Crear/borrar mundo sin spinner ni bloqueo de botón
**Archivos:** `static/js/worlds.js:93-113, 170-216` · **Esfuerzo:** bajo

Borrar un mundo puede tardar varios segundos (borra potencialmente varios GB de
región) sin ningún feedback visual del progreso.

### 25. Huecos de responsive fuera del modal de mods
**Archivos:** `static/css/logs.css` (.log-layout), `static/css/sysmon.css` (#sysmon-panel) · **Esfuerzo:** bajo-medio

El visor de logs (sidebar de 220px + visor) no tiene ninguna regla mobile — se rompe
fuerte en un celular. El panel de sistema (380px fijo) es literalmente más ancho que
la mayoría de pantallas de celular, sin media query.

### 26. Configuración hardcodeada que debería ser variable de entorno
**Archivos:** `main.py`, `routes/modpacks.py` (firewall_router), `services/modpack.py`, `services/mod_search.py` · **Esfuerzo:** bajo (mayoría) / medio (firewall)

Puerto 25565, CIDR de LAN `192.168.1.0/24`, puerto web 8000, puerto RCON por defecto,
timeouts HTTP, factor de RAM 0.8. El firewall queda literalmente atado a una sola
topología de red doméstica.

### 27. Dos instaladores independientes que pueden desincronizarse
**Archivos:** `install.sh`, `setup.py` · **Esfuerzo:** medio

Ambos generan `.env` por separado; `setup.py` no ofrece `MC_DOMAIN`/`SERVERS_PATH`
que `install.sh` sí, así que hay que mantenerlos sincronizados a mano.

### 28. `.env.example` desactualizado
**Archivos:** `.env.example` · **Esfuerzo:** bajo

Referencia `PABLO_PASSWORD_HASH` en vez de `APP_PASSWORD_HASH` (lo que de verdad lee
`services/users.py`), y le faltan varias variables que `install.sh` sí escribe.

### 29. Sin README en todo el repo
**Archivos:** — (no existe README.md) · **Esfuerzo:** bajo-medio

No hay ningún documento explicando qué hace el panel, cómo instalarlo, o qué
funciones tiene (búsqueda de mods, key de CurseForge, Docker vs. nativo) más allá de
leer los scripts directamente.

### 30. Sin backup/rollback si un `git pull` rompe el panel
**Archivos:** `install.sh:149-163` · **Esfuerzo:** medio

El flujo de actualización hace `git pull` + `systemctl restart` sin respaldar antes
`.env`/usuarios, y sin ningún camino de vuelta si el código actualizado no arranca.

### 31. CORS no configurado, pero hay código muerto que insinúa que se planeó
**Archivos:** `main.py:48-50` · **Esfuerzo:** bajo

El paso explícito de peticiones OPTIONS en `AuthMiddleware` sugiere que se pensó
configurar CORS y nunca se conectó. No es una vulnerabilidad activa (sin política, el
navegador bloquea todo cross-origin por defecto), pero es código confuso.

### 32. Archivo sospechoso sin trackear en el repo
**Archivos:** `icon/The iTero Companion App.exe` · **Esfuerzo:** bajo

Un ejecutable de Windows sin relación aparente con el proyecto, sentado en la
carpeta `icon/`. No está commiteado, pero vale investigar su origen antes de que
alguien haga `git add -A` sin fijarse.

### 33. Sin límite de clientes SSE concurrentes en el stream de estadísticas
**Archivos:** `routes/system.py:96-124` · **Esfuerzo:** bajo-medio

Combinado con la falta de rate limiting, cada pestaña abierta del panel es un loop de
sondeo de `psutil` indefinido, sin tope.

---

## Bajo (pulido, cuando haya tiempo)

### 34. El visor de logs no tiene tope de líneas
**Archivos:** `static/js/logs.js:95-152` · **Esfuerzo:** medio

A diferencia de la consola en vivo (tope de 800 líneas), reconstruye el archivo
completo en cada búsqueda — con crash reports de varios MB se nota al escribir en el
buscador.

### 35. IDs de DOM confusamente parecidos
**Archivos:** `#mod-search`, `#mods-search`, `#mod-search-input` · **Esfuerzo:** bajo

Los tres coexisten con la pestaña de mods abierta. No es un bug (cada archivo usa su
id exacto), pero es fácil agarrar el elemento equivocado al editar por parecido de
nombre.

### 36. players.js no usa el helper de fetch compartido
**Archivos:** `static/js/players.js:87-104` · **Esfuerzo:** bajo

Tiene su propio `apiCall()` con `fetch` crudo en vez de `apiFetch`, perdiendo el
auto-logout en 401 y la deduplicación de peticiones en vuelo que sí tiene el resto de
la app.

### 37. Nombres de variables globales confusamente parecidos
**Archivos:** `currentModpack`, `currentModpackVersion`, `modloaderInfo` · **Esfuerzo:** bajo

Un string y dos objetos distintos con nombres que invitan a confundirlos al leer
código en diagonal.

### 38. Dependencia oculta entre archivos vía orden de carga
**Archivos:** `static/js/manage.js:225` (declara PAGE_SIZE), `static/js/worlds.js:351` (lo usa) · **Esfuerzo:** bajo, pero frágil

Solo funciona porque `manage.js` se carga antes que `worlds.js` en index.html. Nada
impide reordenar esos `<script>` algún día y romper la paginación de archivos de
mundo en silencio.

### 39. Carga de los 12 archivos JS sin condicionar por pestaña
**Archivos:** `static/index.html:888-900` · **Esfuerzo:** no aplica

Se revisó porque se pidió, pero no es un problema real a esta escala (~156KB sin
comprimir, sin bundler). Separar por pestaña sería sobre-ingeniería para un panel de
un solo usuario.

---

## Bloque 6 — Legibilidad y estilo

Solo reporte por ahora. Se aplica directamente tras confirmación explícita —
mecánico y de bajo riesgo, salvo lo señalado aparte para revisión manual.

### Operadores ternarios a reemplazar por if/else
**Esfuerzo:** bajo-medio, mecánico

JS:

| Archivo | Ternarios |
|---|---|
| manage.js | 29 |
| mods.js | 20 |
| worlds.js | 12 |
| server.js | 9 |
| players.js | 6 |
| deploy.js | 4 |
| users.js | 3 |
| modloader.js | 2 |
| auth.js | 1 |

Python (excluyendo `server.py`, código muerto — mejor borrarlo que reformatearlo):

| Archivo | Ternarios |
|---|---|
| services/modpack.py | 17 |
| routes/system.py | 7 |
| routes/modpacks.py | 5 |
| services/utils.py | 4 |
| routes/mod_search.py | 3 |
| services/mod_search.py | 3 |
| main.py / setup.py / routes/server.py / services/metrics.py | 1 c/u |

### Llaves en la misma línea o vacías
**Archivos:** auth.js, manage.js, mods.js, server.js, utils.js, worlds.js, server.css, mods.css · **Esfuerzo:** bajo, mecánico

~25 casos en JS, casi todos objetos/callbacks vacíos (`var x = {}`,
`.catch(function() {})`). 3 reglas CSS de una sola línea. No se encontraron bloques
`if`/`for` con contenido pegado a la llave — el resto ya expande consistentemente.
Python no tiene equivalente literal (indentación, no llaves; tampoco hay ifs de una
sola línea).

### Nombres de variable poco descriptivos
**Archivos:** services/modpack.py, services/modloader.py, routes/modpacks.py, manage.js, routes/server.py · **Esfuerzo:** medio, revisión caso a caso

El patrón más extendido es la variable de una letra `m` para objetos de match de
regex — idiomático en Python, pero no está exento por la regla dada (no es índice de
bucle). También hay `val`/`tmp` sueltos en manage.js. Este es el punto donde más
fácil es confundir "solo renombrar" con "tocar la lógica" (sobre todo en los bloques
densos de regex de `services/modpack.py`), así que se trataría con cuidado,
dejando los casos dudosos aparte para revisión manual.
