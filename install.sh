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
            pkg_install python3 python3-pip python3-full
            ;;
        dnf) pkg_install python3 python3-pip ;;
        yum) pkg_install python3 python3-pip ;;
        *)   die "Python3 no encontrado y no se puede instalar automáticamente. Instálalo manualmente." ;;
    esac
fi
ok "Python $(python3 --version 2>&1 | grep -oP '\d+\.\d+\.\d+' || python3 --version 2>&1)"

# En Debian/Ubuntu el paquete venv es específico de versión: python3.12-venv, python3.11-venv, etc.
# python3-venv es un metapaquete que no siempre instala ensurepip correctamente.
if [[ "$PKG" == "apt" ]]; then
    PY_MINOR=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    info "Instalando python${PY_MINOR}-venv..."
    $SUDO apt-get install -y -q "python${PY_MINOR}-venv" 2>/dev/null || pkg_install python3-venv python3-full
elif ! python3 -m venv --help &>/dev/null 2>&1; then
    case $PKG in
        dnf) pkg_install python3 ;;
        yum) pkg_install python3 ;;
        *)   die "Módulo venv no disponible. Instala python3-venv manualmente." ;;
    esac
fi

# ══════════════════════════════════════════════════════════════════════════════
# 1. MODO DE INSTALACIÓN
# ══════════════════════════════════════════════════════════════════════════════
sep "Modo de instalación"

# En re-ejecuciones (ej. reinicio del contenedor) leer el modo guardado
SAVED_MODE_FILE="$HOME/.mc-deployer-mode"
if [[ -f "$SAVED_MODE_FILE" ]]; then
    INSTALL_MODE=$(cat "$SAVED_MODE_FILE")
    ok "Modo anterior detectado: $( [[ "$INSTALL_MODE" == "1" ]] && echo "Contenedor" || echo "Nativo" )"
else
    echo "  ¿Cómo quieres instalar Minecraft Server Deployer?"
    echo ""
    echo "    1) Contenedor  — estás dentro de un contenedor Docker"
    echo "    2) Nativo      — directo en el sistema con systemd"
    echo ""

    while true; do
        prompt "  Elige una opción [1/2]: "
        read -r INSTALL_MODE
        [[ "$INSTALL_MODE" == "1" || "$INSTALL_MODE" == "2" ]] && break
        warn "Introduce 1 o 2."
    done

    echo "$INSTALL_MODE" > "$SAVED_MODE_FILE"
fi

if [[ "$INSTALL_MODE" == "1" ]] && [[ ! -f "/.dockerenv" ]]; then
    die "No estás dentro de un contenedor Docker. Elige el modo nativo (opción 2) o ejecuta el instalador desde dentro de un contenedor."
fi

# ══════════════════════════════════════════════════════════════════════════════
# 2. DIRECTORIO E INSTALACIÓN / ACTUALIZACIÓN DEL CÓDIGO
# ══════════════════════════════════════════════════════════════════════════════
sep "Directorio de instalación"

prompt "  Carpeta donde instalar la app [${DEFAULT_INSTALL_DIR}]: "
read -r INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"

VENV_DIR="$INSTALL_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

ALREADY_INSTALLED=false
if [[ -f "$INSTALL_DIR/main.py" ]]; then
    ALREADY_INSTALLED=true

    if command -v git &>/dev/null && [[ -d "$INSTALL_DIR/.git" ]]; then
        info "Comprobando actualizaciones en GitHub..."
        git -C "$INSTALL_DIR" fetch --quiet origin 2>/dev/null || true
        BEHIND=$(git -C "$INSTALL_DIR" rev-list HEAD..origin/main --count 2>/dev/null || echo "0")

        if (( BEHIND > 0 )); then
            warn "Hay ${BEHIND} commit(s) nuevos disponibles."
            prompt "  ¿Actualizar ahora? [s/N]: "
            read -r DO_UPDATE
            if [[ "${DO_UPDATE,,}" == "s" ]]; then
                git -C "$INSTALL_DIR" pull --quiet && ok "Código actualizado"
            else
                info "Saltando actualización."
            fi
        else
            ok "El código está al día"
            # Sin cambios: arrancar directamente si el entorno ya está listo
            if [[ -d "$VENV_DIR" ]] && [[ -f "$INSTALL_DIR/.env" ]]; then
                if [[ "$INSTALL_MODE" == "1" ]]; then
                    info "Sin cambios. Arrancando la app..."
                    cd "$INSTALL_DIR"
                    exec "$VENV_PYTHON" main.py
                else
                    info "Sin cambios. Reiniciando el servicio..."
                    $SUDO systemctl restart minecraft-deployer
                    ok "Servicio reiniciado"
                    exit 0
                fi
            fi
            # Si el entorno no está listo (venv o .env faltan), cae al flujo normal
        fi
    else
        warn "No es un repositorio git. No se pueden comprobar actualizaciones."
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
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creando entorno virtual Python en .venv/ ..."
    if ! python3 -m venv "$VENV_DIR" 2>/dev/null; then
        PY_MINOR=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        warn "Fallo al crear venv. Instalando python${PY_MINOR}-venv..."
        case $PKG in
            apt) $SUDO apt-get install -y -q "python${PY_MINOR}-venv" ;;
            dnf) $SUDO dnf install -y "python${PY_MINOR}-venv" 2>/dev/null || $SUDO dnf install -y python3 ;;
            yum) $SUDO yum install -y python3 ;;
            *)   die "No se pudo crear el entorno virtual. Instala python3-venv manualmente." ;;
        esac
        python3 -m venv "$VENV_DIR"
    fi
    ok "Entorno virtual creado"
fi

"$VENV_PIP" install --quiet --upgrade pip

# .APP_CONSTANTS (ajustes no sensibles) no está en git (el panel de admin lo
# modifica en cada instalación) — se autogenera con valores por defecto al
# importar app_constants.py, pero se fuerza acá para que exista desde el
# primer arranque en vez de depender de un efecto colateral del import.
if [[ ! -f ".APP_CONSTANTS" ]]; then
    "$VENV_PYTHON" -c "import app_constants" 2>/dev/null || true
    [[ -f ".APP_CONSTANTS" ]] && ok ".APP_CONSTANTS generado"
fi

# ══════════════════════════════════════════════════════════════════════════════
# 3. CONFIGURACIÓN — solo en primera instalación
#    En actualizaciones se reutiliza el .env existente
# ══════════════════════════════════════════════════════════════════════════════
if [[ "$ALREADY_INSTALLED" == "false" ]] || [[ ! -f ".env" ]]; then

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

    sep "Dominio público"
    echo "  Dominio con el que los jugadores se conectarán al servidor Minecraft."
    echo "  Déjalo vacío si no tienes dominio (se mostrará la IP pública)."
    echo ""
    prompt "  Dominio Minecraft [ej: mc.tudominio.com]: "
    read -r MC_DOMAIN
    ok "Dominio: ${MC_DOMAIN:-no configurado}"

    sep "CurseForge (opcional)"
    echo "  Habilita buscar e instalar mods desde CurseForge además de Modrinth"
    echo "  (Modrinth funciona sin esto). Se consigue gratis en:"
    echo "  https://console.curseforge.com/#/api-keys"
    echo ""
    prompt "  API key de CurseForge [déjalo vacío para saltar]: "
    read -r CURSEFORGE_API_KEY
    if [[ -n "$CURSEFORGE_API_KEY" ]]; then
        ok "CurseForge configurado"
    else
        info "CurseForge deshabilitado (puedes añadirlo luego editando .env)"
    fi

    sep "Auto-actualización (opcional)"
    echo "  La app puede revisar sola cada tanto si hay una versión nueva en GitHub"
    echo "  y actualizarse + reiniciarse sola — pero SOLO cuando no haya ningún"
    echo "  servidor de Minecraft corriendo ni ninguna subida/instalación en curso;"
    echo "  si hay algo de eso, pospone la actualización al siguiente chequeo."
    echo ""
    prompt "  ¿Habilitar auto-actualización? [s/N]: "
    read -r AUTO_UPDATE_ANSWER
    if [[ "${AUTO_UPDATE_ANSWER,,}" == "s" ]]; then
        AUTO_UPDATE_ENABLED="true"
        while true; do
            prompt "  Revisar cada cuántos segundos [300]: "
            read -r AUTO_UPDATE_INTERVAL_SECONDS
            AUTO_UPDATE_INTERVAL_SECONDS="${AUTO_UPDATE_INTERVAL_SECONDS:-300}"
            [[ "$AUTO_UPDATE_INTERVAL_SECONDS" =~ ^[0-9]+$ ]] && (( AUTO_UPDATE_INTERVAL_SECONDS >= 30 )) && break
            warn "Introduce un número de segundos (mínimo 30)."
        done
        ok "Auto-actualización habilitada, revisando cada ${AUTO_UPDATE_INTERVAL_SECONDS}s"
    else
        AUTO_UPDATE_ENABLED="false"
        AUTO_UPDATE_INTERVAL_SECONDS="300"
        info "Auto-actualización deshabilitada (puedes activarla luego editando .env)"
    fi

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

    info "Instalando bcrypt..."
    "$VENV_PIP" install --quiet bcrypt

    JWT_SECRET=$("$VENV_PYTHON" -c "import secrets; print(secrets.token_hex(32))")

    APP_HASH=$("$VENV_PYTHON" - "$APP_PASS" <<'PYEOF'
import bcrypt, sys
print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode())
PYEOF
)

    cat > .env <<EOF
APP_USERNAME=${APP_USER}
APP_PASSWORD_HASH=${APP_HASH}
JWT_SECRET=${JWT_SECRET}
WEB_PORT=${WEB_PORT}
JAVA_VER=${JAVA_VER}
MC_DOMAIN=${MC_DOMAIN}
CURSEFORGE_API_KEY=${CURSEFORGE_API_KEY}
AUTO_UPDATE_ENABLED=${AUTO_UPDATE_ENABLED}
AUTO_UPDATE_INTERVAL_SECONDS=${AUTO_UPDATE_INTERVAL_SECONDS}
EOF
    ok ".env generado"

    if [[ ! -f "users.json" ]]; then
        echo "[]" > users.json
        ok "users.json creado"
    fi

else
    ok "Usando configuración existente (.env)"
    JAVA_VER=$(grep -oP '(?<=^JAVA_VER=).+' .env 2>/dev/null || echo "21")
    WEB_PORT=$(grep -oP '(?<=^WEB_PORT=).+' .env 2>/dev/null || echo "8000")
fi

# ══════════════════════════════════════════════════════════════════════════════
# 4A. MODO CONTENEDOR
# ══════════════════════════════════════════════════════════════════════════════
if [[ "$INSTALL_MODE" == "1" ]]; then

    sep "Ruta de servidores Minecraft"
    if ! grep -q '^SERVERS_PATH=' .env 2>/dev/null; then
        echo "  ¿Dónde se guardarán los modpacks y servidores dentro del contenedor?"
        echo ""
        prompt "  Ruta [/servers]: "
        read -r SERVERS_PATH
        SERVERS_PATH="${SERVERS_PATH:-/servers}"
        echo "SERVERS_PATH=${SERVERS_PATH}" >> .env
    else
        SERVERS_PATH=$(grep -oP '(?<=^SERVERS_PATH=).+' .env)
    fi
    mkdir -p "$SERVERS_PATH"
    ok "Carpeta de servidores: $SERVERS_PATH"

    sep "Instalando dependencias Python"
    "$VENV_PIP" install --quiet -r requirements.txt
    ok "Dependencias Python instaladas"

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
    echo ""
    echo "  Arrancando la app (Ctrl+C para parar)..."
    echo ""
    exec "$VENV_PYTHON" main.py

# ══════════════════════════════════════════════════════════════════════════════
# 4B. MODO NATIVO
# ══════════════════════════════════════════════════════════════════════════════
else

    sep "Ruta de servidores Minecraft"
    if ! grep -q '^SERVERS_PATH=' .env 2>/dev/null; then
        echo "  ¿Dónde se guardarán los modpacks y servidores?"
        echo ""
        prompt "  Ruta [${HOME}/servers-minecraft]: "
        read -r SERVERS_PATH
        SERVERS_PATH="${SERVERS_PATH:-${HOME}/servers-minecraft}"
        SERVERS_PATH="${SERVERS_PATH/#\~/$HOME}"
        echo "SERVERS_PATH=${SERVERS_PATH}" >> .env
    else
        SERVERS_PATH=$(grep -oP '(?<=^SERVERS_PATH=).+' .env)
    fi
    mkdir -p "$SERVERS_PATH"
    ok "Carpeta de servidores: $SERVERS_PATH"

    sep "Instalando dependencias Python"
    "$VENV_PIP" install --quiet -r requirements.txt
    ok "Dependencias Python instaladas"

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
    echo -e "  Usuario:               ${BOLD}$(grep -oP '(?<=^APP_USERNAME=).+' .env || echo 'admin')${NC}"
    echo ""
    echo "  Comandos útiles:"
    echo "    Ver logs:     sudo journalctl -u minecraft-deployer -f"
    echo "    Parar:        sudo systemctl stop minecraft-deployer"
    echo "    Arrancar:     sudo systemctl start minecraft-deployer"
    echo "    Reconfigurar: bash '${INSTALL_DIR}/install.sh'"
    echo ""

fi
