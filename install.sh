#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  Minecraft Server Deployer — Instalador
#  Uso: bash install.sh
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

REPO_URL="https://github.com/plushtrap00/minecraft-deployer"
DEFAULT_INSTALL_DIR="$HOME/minecraft-deployer"

# ── Colores ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()   { echo -e "${CYAN}  →${NC} $*"; }
ok()     { echo -e "${GREEN}  ✓${NC} $*"; }
warn()   { echo -e "${YELLOW}  ⚠${NC} $*"; }
die()    { echo -e "${RED}  ✗${NC} $*" >&2; exit 1; }
sep()    { echo -e "\n${BOLD}── $* $(printf '─%.0s' $(seq 1 $((46 - ${#1}))))${NC}\n"; }
prompt() { echo -en "${BOLD}  $*${NC}"; }

# ── Banner ─────────────────────────────────────────────────────────────────────
clear
echo -e "${BOLD}${CYAN}"
cat <<'BANNER'
  ╔═══════════════════════════════════════════════════╗
  ║       Minecraft Server Deployer — Installer       ║
  ╚═══════════════════════════════════════════════════╝
BANNER
echo -e "${NC}"

[[ "$(uname -s)" == "Linux" ]] || die "Este instalador solo funciona en Linux."

# ── Sudo o root ────────────────────────────────────────────────────────────────
# En contenedores Docker se ejecuta como root sin sudo
if [[ $EUID -eq 0 ]]; then
    SUDO=""
else
    SUDO="sudo"
fi

# ── Detectar gestor de paquetes ───────────────────────────────────────────────
if   command -v apt-get &>/dev/null; then PKG="apt"
elif command -v dnf     &>/dev/null; then PKG="dnf"
elif command -v yum     &>/dev/null; then PKG="yum"
else PKG="unknown"; fi

pkg_install() {
    case $PKG in
        apt) $SUDO apt-get install -y -q "$@" ;;
        dnf) $SUDO dnf install -y "$@" ;;
        yum) $SUDO yum install -y "$@" ;;
        *)   die "Gestor de paquetes no detectado. Instala manualmente: $*" ;;
    esac
}

# ══════════════════════════════════════════════════════════════════════════════
# 0. PYTHON — se necesita antes de cualquier otra cosa
# ══════════════════════════════════════════════════════════════════════════════
sep "Comprobando Python"

if ! command -v python3 &>/dev/null; then
    info "Python3 no encontrado. Instalando..."
    case $PKG in
        apt)
            $SUDO apt-get update -qq
            pkg_install python3 python3-pip python3-venv python3-full
            ;;
        dnf) pkg_install python3 python3-pip ;;
        yum) pkg_install python3 python3-pip ;;
        *)   die "Python3 no encontrado y no se puede instalar automáticamente. Instálalo manualmente." ;;
    esac
fi
ok "Python $(python3 --version 2>&1 | grep -oP '\d+\.\d+\.\d+' || python3 --version 2>&1)"

# Asegurarse de que el módulo venv está disponible (Debian lo separa)
if ! python3 -m venv --help &>/dev/null 2>&1; then
    info "Instalando módulo venv..."
    case $PKG in
        apt) pkg_install python3-venv python3-full ;;
        dnf) pkg_install python3 ;;
        yum) pkg_install python3 ;;
        *)   die "Módulo venv no disponible. Instala python3-venv manualmente." ;;
    esac
fi

# ══════════════════════════════════════════════════════════════════════════════
# 1. MODO DE INSTALACIÓN
# ══════════════════════════════════════════════════════════════════════════════
sep "Modo de instalación"
echo "  ¿Cómo quieres instalar Minecraft Server Deployer?"
echo ""
echo "    1) Docker   — todo en contenedores, más aislado y portable"
echo "    2) Nativo   — directo en el sistema, sin Docker"
echo ""

while true; do
    prompt "  Elige una opción [1/2]: "
    read -r INSTALL_MODE
    [[ "$INSTALL_MODE" == "1" || "$INSTALL_MODE" == "2" ]] && break
    warn "Introduce 1 o 2."
done

# ══════════════════════════════════════════════════════════════════════════════
# 2. DIRECTORIO DE INSTALACIÓN
# ══════════════════════════════════════════════════════════════════════════════
sep "Directorio de instalación"

prompt "  Carpeta donde instalar la app [${DEFAULT_INSTALL_DIR}]: "
read -r INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"

# ── Descargar proyecto ─────────────────────────────────────────────────────────
if [[ -f "$INSTALL_DIR/main.py" ]]; then
    warn "Ya existe una instalación en '$INSTALL_DIR'."
    prompt "  ¿Actualizar el código? [s/N]: "
    read -r DO_UPDATE
    if [[ "${DO_UPDATE,,}" == "s" ]]; then
        if command -v git &>/dev/null && [[ -d "$INSTALL_DIR/.git" ]]; then
            git -C "$INSTALL_DIR" pull --quiet && ok "Código actualizado"
        else
            warn "No es un repositorio git. Saltando actualización."
        fi
    fi
else
    mkdir -p "$INSTALL_DIR"
    if command -v git &>/dev/null; then
        info "Clonando repositorio..."
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    else
        info "git no encontrado. Instalando curl y descargando ZIP..."
        pkg_install curl unzip
        TMP_ZIP=$(mktemp /tmp/mc-deployer-XXXXXX.zip)
        TMP_DIR=$(mktemp -d /tmp/mc-deployer-XXXXXX)
        curl -fsSL "${REPO_URL}/archive/refs/heads/main.zip" -o "$TMP_ZIP"
        unzip -q "$TMP_ZIP" -d "$TMP_DIR"
        cp -r "$TMP_DIR"/*/. "$INSTALL_DIR/"
        rm -rf "$TMP_ZIP" "$TMP_DIR"
    fi
    ok "Proyecto descargado en '$INSTALL_DIR'"
fi

cd "$INSTALL_DIR"

# ── Entorno virtual Python ─────────────────────────────────────────────────────
VENV_DIR="$INSTALL_DIR/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creando entorno virtual Python en .venv/ ..."
    python3 -m venv "$VENV_DIR"
    ok "Entorno virtual creado"
fi
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# Actualizar pip dentro del venv silenciosamente
"$VENV_PIP" install --quiet --upgrade pip

# ══════════════════════════════════════════════════════════════════════════════
# 3. CONFIGURACIÓN COMÚN (credenciales + puertos)
# ══════════════════════════════════════════════════════════════════════════════
sep "Credenciales de acceso"
echo "  Usuario y contraseña para entrar a la interfaz web."
echo ""

prompt "  Usuario [admin]: "
read -r APP_USER
APP_USER="${APP_USER:-admin}"

while true; do
    prompt "  Contraseña (mín. 8 caracteres): "
    read -rs APP_PASS; echo ""
    if [[ ${#APP_PASS} -lt 8 ]]; then warn "Mínimo 8 caracteres."; continue; fi
    prompt "  Confirmar contraseña: "
    read -rs APP_PASS2; echo ""
    [[ "$APP_PASS" == "$APP_PASS2" ]] && break
    warn "Las contraseñas no coinciden."
done
ok "Credenciales configuradas"

sep "Puertos"
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

# ── Versión de Java ────────────────────────────────────────────────────────────
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

# ── Instalar bcrypt en el venv y generar hash ──────────────────────────────────
info "Instalando bcrypt..."
"$VENV_PIP" install --quiet bcrypt

JWT_SECRET=""
if [[ -f ".env" ]]; then
    JWT_SECRET=$(grep -oP '(?<=^JWT_SECRET=).+' .env 2>/dev/null || true)
fi
[[ -z "$JWT_SECRET" ]] && JWT_SECRET=$("$VENV_PYTHON" -c "import secrets; print(secrets.token_hex(32))")

APP_HASH=$("$VENV_PYTHON" - "$APP_PASS" <<'PYEOF'
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

# Crear users.json vacío si no existe (persistencia de usuarios normales)
if [[ ! -f "users.json" ]]; then
    echo "[]" > users.json
    ok "users.json creado"
fi

# ══════════════════════════════════════════════════════════════════════════════
# 4A. INSTALACIÓN CON DOCKER
# ══════════════════════════════════════════════════════════════════════════════
if [[ "$INSTALL_MODE" == "1" ]]; then

    sep "Instalando dependencias (Docker)"

    if ! command -v docker &>/dev/null; then
        warn "Docker no encontrado. Instalando..."
        curl -fsSL https://get.docker.com | sh
        [[ -n "$SUDO" ]] && sudo usermod -aG docker "$USER"
    fi
    ok "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)"

    if ! docker compose version &>/dev/null 2>&1; then
        warn "Docker Compose plugin no encontrado. Instalando..."
        pkg_install docker-compose-plugin
    fi
    ok "Docker Compose listo"

    # Los servidores se guardan en un volumen Docker gestionado
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
      - servers:/servers
      - ./.env:/app/.env:ro
      - ./users.json:/app/users.json
    environment:
      SERVERS_PATH: /servers
    restart: unless-stopped

volumes:
  servers:
EOF
    ok "docker-compose.yml generado"

    sep "Construyendo imagen Docker"
    echo "  (Puede tardar varios minutos la primera vez)"
    echo ""
    docker compose build

    sep "Arrancando la app"
    docker compose up -d

    MANAGE_STOP="docker compose -f '${INSTALL_DIR}/docker-compose.yml' down"
    MANAGE_START="docker compose -f '${INSTALL_DIR}/docker-compose.yml' up -d"
    MANAGE_LOGS="docker compose -f '${INSTALL_DIR}/docker-compose.yml' logs -f"

# ══════════════════════════════════════════════════════════════════════════════
# 4B. INSTALACIÓN NATIVA
# ══════════════════════════════════════════════════════════════════════════════
else

    sep "Ruta de servidores Minecraft"
    echo "  ¿Dónde se guardarán los modpacks y servidores?"
    echo ""
    prompt "  Ruta [${HOME}/servers-minecraft]: "
    read -r SERVERS_PATH
    SERVERS_PATH="${SERVERS_PATH:-${HOME}/servers-minecraft}"
    SERVERS_PATH="${SERVERS_PATH/#\~/$HOME}"
    mkdir -p "$SERVERS_PATH"
    ok "Carpeta de servidores: $SERVERS_PATH"

    echo "SERVERS_PATH=${SERVERS_PATH}" >> .env

    sep "Instalando dependencias Python (nativo)"

    info "Instalando paquetes de requirements.txt en el entorno virtual..."
    "$VENV_PIP" install --quiet -r requirements.txt
    ok "Dependencias Python instaladas"

    # Java
    sep "Comprobando Java"
    if ! command -v java &>/dev/null; then
        warn "Java no encontrado. Instalando OpenJDK ${JAVA_VER}..."
        case $PKG in
            apt) pkg_install "openjdk-${JAVA_VER}-jre-headless" ;;
            dnf|yum) pkg_install "java-${JAVA_VER}-openjdk-headless" ;;
            *) warn "Instala Java ${JAVA_VER} manualmente para poder arrancar servidores." ;;
        esac
    fi
    java -version 2>&1 | head -1 | { read v; ok "Java: $v"; } || true

    sep "Creando servicio systemd"

    SERVICE_FILE="/etc/systemd/system/minecraft-deployer.service"
    $SUDO tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Minecraft Server Deployer
After=network.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${VENV_DIR}/bin/python ${INSTALL_DIR}/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    $SUDO systemctl daemon-reload
    $SUDO systemctl enable minecraft-deployer
    $SUDO systemctl restart minecraft-deployer
    ok "Servicio minecraft-deployer activo"

    MANAGE_STOP="sudo systemctl stop minecraft-deployer"
    MANAGE_START="sudo systemctl start minecraft-deployer"
    MANAGE_LOGS="sudo journalctl -u minecraft-deployer -f"

fi

# ══════════════════════════════════════════════════════════════════════════════
# 5. ÉXITO
# ══════════════════════════════════════════════════════════════════════════════
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
echo "    Ver logs:   ${MANAGE_LOGS}"
echo "    Parar:      ${MANAGE_STOP}"
echo "    Arrancar:   ${MANAGE_START}"
echo "    Reconfigurar: bash '${INSTALL_DIR}/install.sh'"
echo ""
