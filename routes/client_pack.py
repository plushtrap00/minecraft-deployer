"""
routes/client_pack.py - Paquete para jugadores (services/client_pack.py).

Rutas:
- GET  /api/modpacks/{modpack}/client-pack                   → paquetes generados y progreso
- POST /api/modpacks/{modpack}/client-pack?format=...        → generar (en segundo plano)
- GET  /api/modpacks/{modpack}/client-pack/download?format=  → descargar

Las cuentas limitadas también pueden generarlo y descargarlo (services/permissions.py):
es justo lo que necesita un amigo para poder entrar.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from routes.deps import valid_modpack
from services import client_pack

router = APIRouter(prefix="/api/modpacks", tags=["client-pack"], dependencies=[Depends(valid_modpack)])


@router.get("/{modpack}/client-pack")
def client_pack_status(modpack: str):
    return JSONResponse(client_pack.status(modpack))


@router.post("/{modpack}/client-pack")
def client_pack_build(request: Request, modpack: str, format: str):
    if format not in client_pack.FORMATS:
        raise HTTPException(status_code=400, detail="Formato de paquete desconocido")
    request.state.activity_detail = format
    client_pack.start(modpack, format)
    return JSONResponse(client_pack.status(modpack))


@router.get("/{modpack}/client-pack/download")
def client_pack_download(modpack: str, format: str):
    path = client_pack.file_for_download(modpack, format)
    if not path:
        raise HTTPException(status_code=404, detail="Ese paquete todavía no se ha generado")
    media = "application/zip" if format == "curseforge" else "application/x-modrinth-modpack+zip"
    return FileResponse(path, media_type=media, filename=client_pack.download_name(modpack, format))
