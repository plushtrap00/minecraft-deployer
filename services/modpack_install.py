"""
services/modpack_install.py - Búsqueda e instalación de MODPACKS completos
(no mods sueltos) desde Modrinth y CurseForge, creando un servidor nuevo.

A diferencia de services/mod_search.py (mods individuales sobre un modpack
YA existente) y services/server_create.py (servidor vacío elegido a mano),
esto resuelve TODO a partir del modpack: modloader + su versión, la lista
completa de mods del pack, y los overrides de configuración — reusando el
bootstrap de server_create.py para que el resultado quede igual de funcional
que un server creado a mano.

Formatos:
- Modrinth: .mrpack = zip con modrinth.index.json (dependencies: loader+mc,
  files: [{path, downloads: [url], env: {client, server}}]) + overrides/ y
  opcionalmente server-overrides/ (pisa a overrides/ para instalaciones de
  servidor). Los downloads YA son URLs directas.
- CurseForge: .zip con manifest.json (minecraft.version, minecraft.modLoaders,
  files: [{projectID, fileID}] — son REFERENCIAS, no URLs; hay que resolverlas
  con la API de CurseForge) + overrides/. Sin campo de client-only por archivo,
  así que todos los mods se instalan en mods/ sin filtrar (igual que hacen los
  demás launchers con este formato).

El código está repartido por temas; este módulo solo reúne lo que usan las
rutas (routes/modpack_install.py) y la actualización de modpacks:
- services/pack_install_common.py: errores, modloader, RAM, overrides, logo
  y la caché de «qué trae este modpack».
- services/pack_install_modrinth.py: Modrinth.
- services/pack_install_curseforge.py: CurseForge (incluido el server pack).
- services/pack_install_duplicates.py: aviso de modpack ya instalado.
"""
from services.pack_install_common import (  # noqa: F401
    CURSEFORGE_MODPACK_CLASS_ID,
    ModpackVersionUnavailable,
    ModpackDownloadBlocked,
)
from services.pack_install_modrinth import (  # noqa: F401
    search_modrinth_modpacks,
    get_modrinth_modpack_categories,
    get_modrinth_modpack_versions,
    get_modrinth_modpack_mods,
    install_modrinth_modpack_stream,
)
from services.pack_install_curseforge import (  # noqa: F401
    search_curseforge_modpacks,
    get_curseforge_modpack_categories,
    get_curseforge_modpack_versions,
    get_curseforge_modpack_mods,
    install_curseforge_modpack_stream,
)
from services.pack_install_duplicates import (  # noqa: F401
    find_similar_installed_modpacks,
)
