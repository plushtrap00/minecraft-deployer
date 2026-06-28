#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  Minecraft Server Deployer — Instalador
#  Uso: bash install.sh
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── URL del repositorio (cámbiala por la tuya de GitHub) ──────────────────────
REPO_URL="https://github.com/plushtrap00/minecraft-deployer"
DEFAULT_INSTALL_DIR="$HOME/minecraft-deployer"

# ── Colores ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}  →${NC} $*"; }
ok()      { echo -e "${GREEN}  ✓${NC} $*"; }
warn()    { echo -e "${YELLOW}  ⚠${NC} $*"; }
die()     { echo -e "${RED}  ✗${NC} $*" >&2; exit 1; }
sep()     { echo -e "\n${BOLD}── $* $(printf '─%.0s' $(seq 1 $((46 - ${#1}))))${NC}\n"; }
prompt()  { echo -en "${BOLD}  $*${NC}"; }

# ── Banner ─────────────────────────────────────────────────────────────────────
clear
echo -e "${BOLD}${CYAN}"
cat <<'BANNER'
  ╔═══════════════════════════════════════════════════╗
  ║       Minecraft Server Deployer — Installer       ║
  ╚═══════════════════════════════════════════════════╝
BANNER
echo -e "${NC}"
echo "  Instala y configura Minecraft Server Deployer"
echo "  en tu servidor con un solo comando."
echo ""

# ── Verificar que corremos en Linux ───────────────────────────────────────────
[[ "$(uname -s)" == "Linux" ]] || die "Este instalador solo funciona en Linux."

# ── Detectar gestor de paquetes ───────────────────────────────────────────────
if   command -v apt-get &>/dev/null; then PKG="apt"
elif command -v dnf     &>/dev/null; then PKG="dnf"
elif command -v yum     &>/dev/null; then PKG="yum"
else PKG="unknown"; fi

pkg_install() {
    case $PKG in
        apt) sudo apt-get install -y -q "$@" ;;
        dnf) sudo dnf install -y "$@" ;;
        yum) sudo yum install -y "$@" ;;
        *)   die "No se detectó gestor de paquetes. Instala manualmente: $*" ;;
    esac
}

# ── 1. Dependencias ────────────────────────────────────────────────────────────
sep "Comprobando dependencias"

# Docker
if ! command -v docker &>/dev/null; then
    warn "Docker no encontrado. Instalando..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    warn "Docker instalado. Si el siguiente paso falla por permisos,"
    warn "cierra sesión, vuelve a entrar y ejecuta de nuevo el instalador."
    # Activar grupo docker sin cerrar sesión
    exec sg docker "$0 $*" 2>/dev/null || true
else
    ok "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)"
fi

# Docker Compose (plugin moderno)
if ! docker compose version &>/dev/null 2>&1; then
    warn "Docker Compose plugin no encontrado. Instalando..."
    case $PKG in
        apt) sudo apt-get install -y -q docker-compose-plugin ;;
        dnf|yum) sudo "$PKG" install -y docker-compose-plugin ;;
        *)   die "Instala el plugin de Docker Compose manualmente." ;;
    esac
fi
ok "Docker Compose $(docker compose version --short 2>/dev/null || echo 'OK')"

# Python3 (para hashear la contraseña)
if ! command -v python3 &>/dev/null; then
    warn "Python3 no encontrado. Instalando..."
    pkg_install python3
fi
ok "Python3 $(python3 --version | grep -oP '\d+\.\d+\.\d+')"

# bcrypt
if ! python3 -c "import bcrypt" &>/dev/null 2>&1; then
    info "Instalando bcrypt..."
    pip3 install --quiet bcrypt 2>/dev/null \
        || python3 -m pip install --quiet bcrypt 2>/dev/null \
        || { pkg_install python3-bcrypt 2>/dev/null || true; }
fi
python3 -c "import bcrypt" || die "No se pudo instalar bcrypt. Ejecuta: pip3 install bcrypt"
ok "bcrypt disponible"

# ── 2. Directorio de instalación ──────────────────────────────────────────────
sep "Directorio de instalación"

prompt "  Carpeta donde instalar [${DEFAULT_INSTALL_DIR}]: "
read -r INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"

# ── 3. Descargar el proyecto ───────────────────────────────────────────────────
if [[ -f "$INSTALL_DIR/main.py" ]]; then
    warn "Ya existe una instalación en '$INSTALL_DIR'."
    prompt "  ¿Actualizar a la última versión? [s/N]: "
    read -r DO_UPDATE
    if [[ "${DO_UPDATE,,}" == "s" ]]; then
        info "Actualizando..."
        if command -v git &>/dev/null && [[ -d "$INSTALL_DIR/.git" ]]; then
            git -C "$INSTALL_DIR" pull --quiet
            ok "Código actualizado"
        else
            warn "No es un repositorio git. Saltando actualización de código."
        fi
    fi
else
    sep "Descargando proyecto"
    mkdir -p "$INSTALL_DIR"
    if command -v git &>/dev/null; then
        info "Clonando repositorio..."
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    else
        info "git no encontrado. Descargando ZIP..."
        pkg_install curl unzip
        TMP_ZIP=$(mktemp /tmp/mc-deployer-XXXXXX.zip)
        curl -fsSL "${REPO_URL}/archive/refs/heads/main.zip" -o "$TMP_ZIP"
        TMP_DIR=$(mktemp -d /tmp/mc-deployer-XXXXXX)
        unzip -q "$TMP_ZIP" -d "$TMP_DIR"
        cp -r "$TMP_DIR"/*/. "$INSTALL_DIR/"
        rm -rf "$TMP_ZIP" "$TMP_DIR"
    fi
    ok "Proyecto descargado en '$INSTALL_DIR'"
fi

cd "$INSTALL_DIR"

# ── 4. Configuración ───────────────────────────────────────────────────────────
sep "Credenciales de acceso"
echo "  Elige el usuario y contraseña para entrar a la interfaz web."
echo ""

prompt "  Usuario [admin]: "
read -r APP_USER
APP_USER="${APP_USER:-admin}"

while true; do
    prompt "  Contraseña (mín. 8 caracteres): "
    read -rs APP_PASS; echo ""
    if [[ ${#APP_PASS} -lt 8 ]]; then
        warn "La contraseña debe tener al menos 8 caracteres."; continue
    fi
    prompt "  Confirmar contraseña: "
    read -rs APP_PASS2; echo ""
    [[ "$APP_PASS" == "$APP_PASS2" ]] && break
    warn "Las contraseñas no coinciden. Inténtalo de nuevo."
done
ok "Credenciales configuradas"

sep "Puertos"
echo "  Puertos que se abrirán en tu servidor."
echo ""

while true; do
    prompt "  Puerto interfaz web [8000]: "
    read -r WEB_PORT; WEB_PORT="${WEB_PORT:-8000}"
    [[ "$WEB_PORT" =~ ^[0-9]+$ ]] && (( WEB_PORT >= 1 && WEB_PORT <= 65535 )) && break
    warn "Puerto inválido (1-65535)."
done

while true; do
    prompt "  Puerto Minecraft [25565]: "
    read -r MC_PORT; MC_PORT="${MC_PORT:-25565}"
    [[ "$MC_PORT" =~ ^[0-9]+$ ]] && (( MC_PORT >= 1 && MC_PORT <= 65535 )) && break
    warn "Puerto inválido (1-65535)."
done

sep "Versión de Java"
echo "    21 → Minecraft 1.20.5 o superior  (NeoForge, Fabric moderno)"
echo "    17 → Minecraft 1.17 – 1.20.4"
echo ""
while true; do
    prompt "  Versión de Java [21]: "
    read -r JAVA_VER; JAVA_VER="${JAVA_VER:-21}"
    [[ "$JAVA_VER" == "17" || "$JAVA_VER" == "21" ]] && break
    warn "Introduce 17 o 21."
done

sep "Almacenamiento de modpacks"
echo "  ¿Dónde guardar los archivos de los servidores Minecraft?"
echo "  · Pulsa Enter → volumen Docker gestionado (recomendado)"
echo "  · Ruta absoluta → ej. /home/$USER/mis-servidores"
echo ""
prompt "  Ruta [volumen Docker]: "
read -r SERVERS_HOST_PATH

# ── 5. Resumen ─────────────────────────────────────────────────────────────────
sep "Resumen"
echo "  Usuario:          $APP_USER"
echo "  Puerto web:       $WEB_PORT"
echo "  Puerto Minecraft: $MC_PORT"
echo "  Java:             $JAVA_VER"
if [[ -z "$SERVERS_HOST_PATH" ]]; then
    echo "  Servidores:       volumen Docker gestionado"
else
    echo "  Servidores:       $SERVERS_HOST_PATH"
fi
echo ""
prompt "  ¿Continuar con la instalación? [S/n]: "
read -r CONFIRM
[[ "${CONFIRM,,}" =~ ^(s|si|sí|y|yes|)$ ]] || { echo "  Instalación cancelada."; exit 0; }

# ── 6. Generar .env ────────────────────────────────────────────────────────────
info "Generando .env..."

# Preservar JWT_SECRET si ya existe (no invalida sesiones activas en actualizaciones)
JWT_SECRET=""
if [[ -f ".env" ]]; then
    JWT_SECRET=$(grep -oP '(?<=^JWT_SECRET=).+' .env 2>/dev/null || true)
fi
if [[ -z "$JWT_SECRET" ]]; then
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
fi

APP_HASH=$(python3 - "$APP_PASS" <<'PYEOF'
import bcrypt, sys
print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode())
PYEOF
)

cat > .env <<EOF
APP_USERNAME=${APP_USER}
APP_PASSWORD_HASH=${APP_HASH}
JWT_SECRET=${JWT_SECRET}
EOF
ok ".env generado"

# ── 7. Generar docker-compose.yml ─────────────────────────────────────────────
info "Generando docker-compose.yml..."

if [[ -z "$SERVERS_HOST_PATH" ]]; then
    VOLUME_MOUNT="      - servers:/servers"
    VOLUMES_BLOCK=$'\nvolumes:\n  servers:'
else
    mkdir -p "$SERVERS_HOST_PATH"
    VOLUME_MOUNT="      - ${SERVERS_HOST_PATH}:/servers"
    VOLUMES_BLOCK=""
fi

cat > docker-compose.yml <<EOF
services:
  minecraft-deployer:
    build:
      context: .
      args:
        JAVA_VERSION: "${JAVA_VER}"
    ports:
      - "${WEB_PORT}:8000"
      - "${MC_PORT}:25565"
    volumes:
${VOLUME_MOUNT}
      - ./.env:/app/.env:ro
    environment:
      SERVERS_PATH: /servers
    restart: unless-stopped
${VOLUMES_BLOCK}
EOF
ok "docker-compose.yml generado"

# ── 8. Build + arranque ────────────────────────────────────────────────────────
sep "Construyendo imagen Docker"
echo "  (Esto puede tardar varios minutos la primera vez)"
echo ""
docker compose build

sep "Arrancando la app"
docker compose up -d

# ── 9. Éxito ───────────────────────────────────────────────────────────────────
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

echo ""
echo -e "${GREEN}${BOLD}"
cat <<'SUCCESS'
  ╔═══════════════════════════════════════════════════╗
  ║           ¡Instalación completada!                ║
  ╚═══════════════════════════════════════════════════╝
SUCCESS
echo -e "${NC}"
echo -e "  Abre en tu navegador:  ${BOLD}http://${LOCAL_IP}:${WEB_PORT}${NC}"
echo -e "  Usuario:               ${BOLD}${APP_USER}${NC}"
echo ""
echo "  Comandos útiles:"
echo "    Ver logs:   docker compose -f '${INSTALL_DIR}/docker-compose.yml' logs -f"
echo "    Parar:      docker compose -f '${INSTALL_DIR}/docker-compose.yml' down"
echo "    Arrancar:   docker compose -f '${INSTALL_DIR}/docker-compose.yml' up -d"
echo "    Reconfigurar: bash '${INSTALL_DIR}/install.sh'"
echo ""
