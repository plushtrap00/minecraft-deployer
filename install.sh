#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  Minecraft Server Deployer — Instalador / Installer
#  Uso / Usage: bash install.sh
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

# Idioma del instalador (y el del panel por defecto): L "español" "english"
UI_LANG="es"
L() { if [[ "$UI_LANG" == "en" ]]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }
# «sí» en los dos idiomas: s/S en español, y/Y en inglés (se aceptan ambos)
is_yes() { [[ "${1,,}" == "s" || "${1,,}" == "y" || "${1,,}" == "si" || "${1,,}" == "sí" || "${1,,}" == "yes" ]]; }

# ── Banner ─────────────────────────────────────────────────────────────────────
clear
echo -e "${BOLD}${CYAN}"
cat <<'BANNER'
  ╔═══════════════════════════════════════════════════╗
  ║       Minecraft Server Deployer — Installer       ║
  ╚═══════════════════════════════════════════════════╝
BANNER
echo -e "${NC}"

[[ "$(uname -s)" == "Linux" ]] || die "Este instalador solo funciona en Linux. / This installer only works on Linux."

# ── Idioma ─────────────────────────────────────────────────────────────────────
# En re-ejecuciones (ej. reinicio del contenedor) se usa el elegido la primera vez.
SAVED_LANG_FILE="$HOME/.mc-deployer-lang"
if [[ -f "$SAVED_LANG_FILE" ]]; then
    UI_LANG=$(cat "$SAVED_LANG_FILE")
    [[ "$UI_LANG" == "en" ]] || UI_LANG="es"
else
    echo "  Idioma / Language:"
    echo ""
    echo "    1) Español (España)"
    echo "    2) English"
    echo ""
    while true; do
        prompt "  [1/2]: "
        read -r LANG_CHOICE
        case "$LANG_CHOICE" in
            1) UI_LANG="es"; break ;;
            2) UI_LANG="en"; break ;;
        esac
        warn "1 / 2"
    done
    echo "$UI_LANG" > "$SAVED_LANG_FILE"
fi
ok "$(L "Idioma: español (también será el idioma por defecto del panel)" "Language: English (it will also be the panel's default language)")"

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
        *)   die "$(L "Gestor de paquetes no detectado. Instala manualmente:" "No package manager detected. Install by hand:") $*" ;;
    esac
}

# ══════════════════════════════════════════════════════════════════════════════
# 0. PYTHON — se necesita antes de cualquier otra cosa
# ══════════════════════════════════════════════════════════════════════════════
sep "$(L "Comprobando Python" "Checking Python")"

if ! command -v python3 &>/dev/null; then
    info "$(L "Python3 no encontrado. Instalando..." "Python3 not found. Installing...")"
    case $PKG in
        apt)
            $SUDO apt-get update -qq
            pkg_install python3 python3-pip python3-full
            ;;
        dnf) pkg_install python3 python3-pip ;;
        yum) pkg_install python3 python3-pip ;;
        *)   die "$(L "Python3 no encontrado y no se puede instalar automáticamente. Instálalo manualmente." "Python3 not found and it can't be installed automatically. Install it by hand.")" ;;
    esac
fi
ok "Python $(python3 --version 2>&1 | grep -oP '\d+\.\d+\.\d+' || python3 --version 2>&1)"

# En Debian/Ubuntu el paquete venv es específico de versión: python3.12-venv, python3.11-venv, etc.
# python3-venv es un metapaquete que no siempre instala ensurepip correctamente.
if [[ "$PKG" == "apt" ]]; then
    PY_MINOR=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    info "$(L "Instalando" "Installing") python${PY_MINOR}-venv..."
    $SUDO apt-get install -y -q "python${PY_MINOR}-venv" 2>/dev/null || pkg_install python3-venv python3-full
elif ! python3 -m venv --help &>/dev/null 2>&1; then
    case $PKG in
        dnf) pkg_install python3 ;;
        yum) pkg_install python3 ;;
        *)   die "$(L "Módulo venv no disponible. Instala python3-venv manualmente." "The venv module isn't available. Install python3-venv by hand.")" ;;
    esac
fi

# ══════════════════════════════════════════════════════════════════════════════
# 1. MODO DE INSTALACIÓN
# ══════════════════════════════════════════════════════════════════════════════
sep "$(L "Modo de instalación" "Installation mode")"

# En re-ejecuciones (ej. reinicio del contenedor) leer el modo guardado
SAVED_MODE_FILE="$HOME/.mc-deployer-mode"
if [[ -f "$SAVED_MODE_FILE" ]]; then
    INSTALL_MODE=$(cat "$SAVED_MODE_FILE")
    ok "$(L "Modo anterior detectado:" "Previous mode detected:") $( [[ "$INSTALL_MODE" == "1" ]] && L "Contenedor" "Container" || L "Nativo" "Native" )"
else
    echo "  $(L "¿Cómo quieres instalar Minecraft Server Deployer?" "How do you want to install Minecraft Server Deployer?")"
    echo ""
    echo "    1) $(L "Contenedor  — estás dentro de un contenedor Docker" "Container   — you're inside a Docker container")"
    echo "    2) $(L "Nativo      — directo en el sistema con systemd" "Native      — straight on the system with systemd")"
    echo ""

    while true; do
        prompt "  $(L "Elige una opción [1/2]: " "Choose an option [1/2]: ")"
        read -r INSTALL_MODE
        [[ "$INSTALL_MODE" == "1" || "$INSTALL_MODE" == "2" ]] && break
        warn "$(L "Introduce 1 o 2." "Enter 1 or 2.")"
    done

    echo "$INSTALL_MODE" > "$SAVED_MODE_FILE"
fi

if [[ "$INSTALL_MODE" == "1" ]] && [[ ! -f "/.dockerenv" ]]; then
    die "$(L "No estás dentro de un contenedor Docker. Elige el modo nativo (opción 2) o ejecuta el instalador desde dentro de un contenedor." "You're not inside a Docker container. Choose native mode (option 2) or run the installer from inside a container.")"
fi

# ══════════════════════════════════════════════════════════════════════════════
# 2. DIRECTORIO E INSTALACIÓN / ACTUALIZACIÓN DEL CÓDIGO
# ══════════════════════════════════════════════════════════════════════════════
sep "$(L "Directorio de instalación" "Installation folder")"

prompt "  $(L "Carpeta donde instalar la app" "Folder to install the app in") [${DEFAULT_INSTALL_DIR}]: "
read -r INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"

VENV_DIR="$INSTALL_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# Instalaciones anteriores a la 3.0 no tienen APP_LANGUAGE: se añade el elegido.
ensure_app_language() {
    if [[ -f "$INSTALL_DIR/.env" ]] && ! grep -q '^APP_LANGUAGE=' "$INSTALL_DIR/.env"; then
        echo "APP_LANGUAGE=${UI_LANG}" >> "$INSTALL_DIR/.env"
        ok "$(L "Idioma por defecto del panel: español" "Panel default language: English")"
    fi
}

ALREADY_INSTALLED=false
if [[ -f "$INSTALL_DIR/main.py" ]]; then
    ALREADY_INSTALLED=true

    if command -v git &>/dev/null && [[ -d "$INSTALL_DIR/.git" ]]; then
        info "$(L "Comprobando actualizaciones en GitHub..." "Checking GitHub for updates...")"
        git -C "$INSTALL_DIR" fetch --quiet origin 2>/dev/null || true
        BEHIND=$(git -C "$INSTALL_DIR" rev-list HEAD..origin/main --count 2>/dev/null || echo "0")

        if (( BEHIND > 0 )); then
            warn "$(L "Hay ${BEHIND} commit(s) nuevos disponibles." "${BEHIND} new commit(s) available.")"
            prompt "  $(L "¿Actualizar ahora? [s/N]: " "Update now? [y/N]: ")"
            read -r DO_UPDATE
            if is_yes "$DO_UPDATE"; then
                git -C "$INSTALL_DIR" pull --quiet && ok "$(L "Código actualizado" "Code updated")"
            else
                info "$(L "Saltando actualización." "Skipping the update.")"
            fi
        else
            ok "$(L "El código está al día" "The code is up to date")"
            # Sin cambios: arrancar directamente si el entorno ya está listo
            if [[ -d "$VENV_DIR" ]] && [[ -f "$INSTALL_DIR/.env" ]]; then
                ensure_app_language
                if [[ "$INSTALL_MODE" == "1" ]]; then
                    info "$(L "Sin cambios. Arrancando la app..." "No changes. Starting the app...")"
                    cd "$INSTALL_DIR"
                    exec "$VENV_PYTHON" main.py
                else
                    info "$(L "Sin cambios. Reiniciando el servicio..." "No changes. Restarting the service...")"
                    $SUDO systemctl restart minecraft-deployer
                    ok "$(L "Servicio reiniciado" "Service restarted")"
                    exit 0
                fi
            fi
            # Si el entorno no está listo (venv o .env faltan), cae al flujo normal
        fi
    else
        warn "$(L "No es un repositorio git. No se pueden comprobar actualizaciones." "It isn't a git repository. Updates can't be checked.")"
    fi
else
    mkdir -p "$INSTALL_DIR"
    if command -v git &>/dev/null; then
        info "$(L "Clonando repositorio..." "Cloning the repository...")"
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    else
        info "$(L "git no encontrado. Instalando curl y descargando ZIP..." "git not found. Installing curl and downloading the ZIP...")"
        pkg_install curl unzip
        TMP_ZIP=$(mktemp /tmp/mc-deployer-XXXXXX.zip)
        TMP_DIR=$(mktemp -d /tmp/mc-deployer-XXXXXX)
        curl -fsSL "${REPO_URL}/archive/refs/heads/main.zip" -o "$TMP_ZIP"
        unzip -q "$TMP_ZIP" -d "$TMP_DIR"
        cp -r "$TMP_DIR"/*/. "$INSTALL_DIR/"
        rm -rf "$TMP_ZIP" "$TMP_DIR"
    fi
    ok "$(L "Proyecto descargado en" "Project downloaded to") '$INSTALL_DIR'"
fi

cd "$INSTALL_DIR"

# ── Entorno virtual Python ─────────────────────────────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
    info "$(L "Creando entorno virtual Python en .venv/ ..." "Creating a Python virtual environment in .venv/ ...")"
    if ! python3 -m venv "$VENV_DIR" 2>/dev/null; then
        PY_MINOR=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        warn "$(L "Fallo al crear venv. Instalando" "Couldn't create the venv. Installing") python${PY_MINOR}-venv..."
        case $PKG in
            apt) $SUDO apt-get install -y -q "python${PY_MINOR}-venv" ;;
            dnf) $SUDO dnf install -y "python${PY_MINOR}-venv" 2>/dev/null || $SUDO dnf install -y python3 ;;
            yum) $SUDO yum install -y python3 ;;
            *)   die "$(L "No se pudo crear el entorno virtual. Instala python3-venv manualmente." "Couldn't create the virtual environment. Install python3-venv by hand.")" ;;
        esac
        python3 -m venv "$VENV_DIR"
    fi
    ok "$(L "Entorno virtual creado" "Virtual environment created")"
fi

"$VENV_PIP" install --quiet --upgrade pip

# .APP_CONSTANTS (ajustes no sensibles) no está en git (el panel de admin lo
# modifica en cada instalación) — se autogenera con valores por defecto al
# importar app_constants.py, pero se fuerza aquí para que exista desde el
# primer arranque en vez de depender de un efecto colateral del import.
if [[ ! -f ".APP_CONSTANTS" ]]; then
    "$VENV_PYTHON" -c "import app_constants" 2>/dev/null || true
    [[ -f ".APP_CONSTANTS" ]] && ok "$(L ".APP_CONSTANTS generado" ".APP_CONSTANTS generated")"
fi

# ══════════════════════════════════════════════════════════════════════════════
# 3. CONFIGURACIÓN — solo en primera instalación
#    En actualizaciones se reutiliza el .env existente
# ══════════════════════════════════════════════════════════════════════════════
if [[ "$ALREADY_INSTALLED" == "false" ]] || [[ ! -f ".env" ]]; then

    sep "$(L "Credenciales de acceso" "Sign-in details")"
    echo "  $(L "Usuario y contraseña para entrar a la interfaz web." "Username and password to sign in to the web panel.")"
    echo ""

    prompt "  $(L "Usuario" "Username") [admin]: "
    read -r APP_USER
    APP_USER="${APP_USER:-admin}"

    while true; do
        prompt "  $(L "Contraseña (mín. 8 caracteres): " "Password (at least 8 characters): ")"
        read -rs APP_PASS; echo ""
        if [[ ${#APP_PASS} -lt 8 ]]; then warn "$(L "Mínimo 8 caracteres." "At least 8 characters.")"; continue; fi
        prompt "  $(L "Confirmar contraseña: " "Confirm password: ")"
        read -rs APP_PASS2; echo ""
        [[ "$APP_PASS" == "$APP_PASS2" ]] && break
        warn "$(L "Las contraseñas no coinciden." "The passwords don't match.")"
    done
    ok "$(L "Credenciales configuradas" "Sign-in details set")"

    sep "$(L "Puertos" "Ports")"
    while true; do
        prompt "  $(L "Puerto interfaz web" "Web panel port") [8000]: "
        read -r WEB_PORT; WEB_PORT="${WEB_PORT:-8000}"
        [[ "$WEB_PORT" =~ ^[0-9]+$ ]] && (( WEB_PORT >= 1 && WEB_PORT <= 65535 )) && break
        warn "$(L "Puerto inválido (1-65535)." "Invalid port (1-65535).")"
    done

    while true; do
        prompt "  $(L "Puerto Minecraft" "Minecraft port") [25565]: "
        read -r MC_PORT; MC_PORT="${MC_PORT:-25565}"
        [[ "$MC_PORT" =~ ^[0-9]+$ ]] && (( MC_PORT >= 1 && MC_PORT <= 65535 )) && break
        warn "$(L "Puerto inválido (1-65535)." "Invalid port (1-65535).")"
    done

    sep "$(L "Dominio público" "Public domain")"
    echo "  $(L "Dominio con el que los jugadores se conectarán al servidor Minecraft." "Domain players will use to connect to the Minecraft server.")"
    echo "  $(L "Déjalo vacío si no tienes dominio (se mostrará la IP pública)." "Leave it empty if you don't have one (the public IP will be shown).")"
    echo ""
    prompt "  $(L "Dominio Minecraft [ej: mc.tudominio.com]: " "Minecraft domain [e.g. mc.yourdomain.com]: ")"
    read -r MC_DOMAIN
    ok "$(L "Dominio:" "Domain:") ${MC_DOMAIN:-$(L "no configurado" "not set")}"

    sep "$(L "CurseForge (opcional)" "CurseForge (optional)")"
    echo "  $(L "Habilita buscar e instalar mods desde CurseForge además de Modrinth" "Lets you search and install mods from CurseForge as well as Modrinth")"
    echo "  $(L "(Modrinth funciona sin esto). Se consigue gratis en:" "(Modrinth works without it). Get one free at:")"
    echo "  https://console.curseforge.com/#/api-keys"
    echo ""
    prompt "  $(L "API key de CurseForge [déjalo vacío para saltar]: " "CurseForge API key [leave empty to skip]: ")"
    read -r CURSEFORGE_API_KEY
    if [[ -n "$CURSEFORGE_API_KEY" ]]; then
        ok "$(L "CurseForge configurado" "CurseForge set up")"
    else
        info "$(L "CurseForge deshabilitado (puedes añadirlo luego editando .env)" "CurseForge disabled (you can add it later by editing .env)")"
    fi

    sep "$(L "Auto-actualización (opcional)" "Auto-update (optional)")"
    echo "  $(L "La app puede revisar sola cada tanto si hay una versión nueva en GitHub" "The app can check GitHub for a new version every so often")"
    echo "  $(L "y actualizarse + reiniciarse sola — pero SOLO cuando no haya ningún" "and update + restart itself — but ONLY when no Minecraft server is")"
    echo "  $(L "servidor de Minecraft corriendo ni ninguna subida/instalación en curso;" "running and no upload/installation is in progress;")"
    echo "  $(L "si hay algo de eso, pospone la actualización a la siguiente comprobación." "if there is, it puts the update off until the next check.")"
    echo ""
    prompt "  $(L "¿Habilitar auto-actualización? [s/N]: " "Enable auto-update? [y/N]: ")"
    read -r AUTO_UPDATE_ANSWER
    if is_yes "$AUTO_UPDATE_ANSWER"; then
        AUTO_UPDATE_ENABLED="true"
        while true; do
            prompt "  $(L "Revisar cada cuántos segundos" "Check every how many seconds") [300]: "
            read -r AUTO_UPDATE_INTERVAL_SECONDS
            AUTO_UPDATE_INTERVAL_SECONDS="${AUTO_UPDATE_INTERVAL_SECONDS:-300}"
            [[ "$AUTO_UPDATE_INTERVAL_SECONDS" =~ ^[0-9]+$ ]] && (( AUTO_UPDATE_INTERVAL_SECONDS >= 30 )) && break
            warn "$(L "Introduce un número de segundos (mínimo 30)." "Enter a number of seconds (at least 30).")"
        done
        ok "$(L "Auto-actualización habilitada, revisando cada ${AUTO_UPDATE_INTERVAL_SECONDS}s" "Auto-update enabled, checking every ${AUTO_UPDATE_INTERVAL_SECONDS}s")"
    else
        AUTO_UPDATE_ENABLED="false"
        AUTO_UPDATE_INTERVAL_SECONDS="300"
        info "$(L "Auto-actualización deshabilitada (puedes activarla luego editando .env)" "Auto-update disabled (you can turn it on later by editing .env)")"
    fi

    sep "$(L "Avisos por Telegram (opcional)" "Telegram notifications (optional)")"
    echo "  $(L "El panel puede avisarte por Telegram cuando el servidor arranca, se cae," "The panel can message you on Telegram when the server starts, crashes,")"
    echo "  $(L "entra alguien... Cada instalación usa su propio bot, así que solo te" "someone joins... Each installation uses its own bot, so only your")"
    echo "  $(L "llegan tus avisos. Para crearlo:" "notifications reach you. To create it:")"
    echo "    $(L "1. En Telegram, abre @BotFather y escríbele /newbot." "1. In Telegram, open @BotFather and send it /newbot.")"
    echo "    $(L "2. Elige un nombre; te dará un token (algo como 123456:ABC-DEF...)." "2. Pick a name; it will give you a token (something like 123456:ABC-DEF...).")"
    echo "  $(L "También se puede configurar más tarde en Configuración → Avisos." "You can also set it up later in Settings → Notifications.")"
    echo ""
    TELEGRAM_BOT_TOKEN=""
    TELEGRAM_CHAT_ID=""
    prompt "  $(L "Token del bot [déjalo vacío para saltar]: " "Bot token [leave empty to skip]: ")"
    read -r TELEGRAM_BOT_TOKEN
    TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN// /}"
    if [[ -n "$TELEGRAM_BOT_TOKEN" ]]; then
        echo "  $(L "Ahora abre tu bot en Telegram y escríbele cualquier cosa (por ejemplo /start)." "Now open your bot in Telegram and send it anything (for example /start).")"
        prompt "  $(L "Pulsa Enter cuando lo hayas hecho... " "Press Enter when you've done it... ")"
        read -r _
        TELEGRAM_CHAT_ID=$("$VENV_PYTHON" - "$TELEGRAM_BOT_TOKEN" <<'PYEOF2'
import json, sys, urllib.request
try:
    with urllib.request.urlopen(f"https://api.telegram.org/bot{sys.argv[1]}/getUpdates", timeout=10) as r:
        updates = json.load(r).get("result") or []
    for update in reversed(updates):
        chat = (update.get("message") or update.get("channel_post") or {}).get("chat") or {}
        if "id" in chat:
            print(chat["id"])
            break
except Exception:
    pass
PYEOF2
)
        if [[ -z "$TELEGRAM_CHAT_ID" ]]; then
            warn "$(L "No se encontró ningún mensaje (¿token correcto? ¿le escribiste al bot?)." "No message found (is the token right? did you message the bot?).")"
            prompt "  $(L "Chat ID a mano [déjalo vacío para configurarlo luego]: " "Chat ID by hand [leave empty to set it up later]: ")"
            read -r TELEGRAM_CHAT_ID
        fi
        if [[ -n "$TELEGRAM_CHAT_ID" ]]; then
            ok "$(L "Telegram configurado (chat ${TELEGRAM_CHAT_ID})" "Telegram set up (chat ${TELEGRAM_CHAT_ID})")"
        else
            TELEGRAM_BOT_TOKEN=""
            info "$(L "Telegram sin configurar (puedes hacerlo luego en Configuración → Avisos)" "Telegram not set up (you can do it later in Settings → Notifications)")"
        fi
    else
        info "$(L "Avisos por Telegram deshabilitados (puedes activarlos luego en Configuración → Avisos)" "Telegram notifications disabled (you can turn them on later in Settings → Notifications)")"
    fi

    sep "$(L "Versión de Java" "Java version")"
    echo "    21 → Minecraft $(L "1.20.5 o superior  (NeoForge, Fabric moderno)" "1.20.5 or newer  (NeoForge, modern Fabric)")"
    echo "    17 → Minecraft 1.17 – 1.20.4"
    echo ""
    while true; do
        prompt "  $(L "Versión de Java" "Java version") [21]: "
        read -r JAVA_VER; JAVA_VER="${JAVA_VER:-21}"
        [[ "$JAVA_VER" == "17" || "$JAVA_VER" == "21" ]] && break
        warn "$(L "Introduce 17 o 21." "Enter 17 or 21.")"
    done

    info "$(L "Instalando bcrypt..." "Installing bcrypt...")"
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
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
APP_LANGUAGE=${UI_LANG}
EOF
    # Lleva JWT_SECRET y el hash de la contraseña: solo lo lee el dueño.
    chmod 600 .env
    ok "$(L ".env generado" ".env generated")"

    if [[ ! -f "users.json" ]]; then
        echo "[]" > users.json
        chmod 600 users.json
        ok "$(L "users.json creado" "users.json created")"
    fi

else
    ok "$(L "Usando configuración existente (.env)" "Using the existing configuration (.env)")"
    ensure_app_language
    JAVA_VER=$(grep -oP '(?<=^JAVA_VER=).+' .env 2>/dev/null || echo "21")
    WEB_PORT=$(grep -oP '(?<=^WEB_PORT=).+' .env 2>/dev/null || echo "8000")
fi

# ── Pasos comunes a los dos modos ──────────────────────────────────────────────
ask_servers_path() {
    sep "$(L "Ruta de servidores Minecraft" "Minecraft servers folder")"
    if ! grep -q '^SERVERS_PATH=' .env 2>/dev/null; then
        if [[ "$INSTALL_MODE" == "1" ]]; then
            echo "  $(L "¿Dónde se guardarán los modpacks y servidores dentro del contenedor?" "Where should modpacks and servers be stored inside the container?")"
            DEFAULT_SERVERS_PATH="/servers"
        else
            echo "  $(L "¿Dónde se guardarán los modpacks y servidores?" "Where should modpacks and servers be stored?")"
            DEFAULT_SERVERS_PATH="${HOME}/servers-minecraft"
        fi
        echo ""
        prompt "  $(L "Ruta" "Path") [${DEFAULT_SERVERS_PATH}]: "
        read -r SERVERS_PATH
        SERVERS_PATH="${SERVERS_PATH:-$DEFAULT_SERVERS_PATH}"
        SERVERS_PATH="${SERVERS_PATH/#\~/$HOME}"
        echo "SERVERS_PATH=${SERVERS_PATH}" >> .env
    else
        SERVERS_PATH=$(grep -oP '(?<=^SERVERS_PATH=).+' .env)
    fi
    mkdir -p "$SERVERS_PATH"
    ok "$(L "Carpeta de servidores:" "Servers folder:") $SERVERS_PATH"
}

install_python_deps() {
    sep "$(L "Instalando dependencias Python" "Installing Python dependencies")"
    "$VENV_PIP" install --quiet -r requirements.txt
    ok "$(L "Dependencias Python instaladas" "Python dependencies installed")"
}

check_java() {
    sep "$(L "Comprobando Java" "Checking Java")"
    if ! command -v java &>/dev/null; then
        warn "$(L "Java no encontrado. Instalando OpenJDK ${JAVA_VER}..." "Java not found. Installing OpenJDK ${JAVA_VER}...")"
        case $PKG in
            apt) pkg_install "openjdk-${JAVA_VER}-jre-headless" ;;
            dnf|yum) pkg_install "java-${JAVA_VER}-openjdk-headless" ;;
            *) warn "$(L "Instala Java ${JAVA_VER} manualmente para poder arrancar servidores." "Install Java ${JAVA_VER} by hand to be able to start servers.")" ;;
        esac
    fi
    java -version 2>&1 | head -1 | { read v; ok "Java: $v"; } || true
}

success_banner() {
    echo ""
    echo -e "${GREEN}${BOLD}"
    if [[ "$UI_LANG" == "en" ]]; then
        cat <<'SUCCESS'
  ╔═══════════════════════════════════════════════════╗
  ║            Installation complete!                 ║
  ╚═══════════════════════════════════════════════════╝
SUCCESS
    else
        cat <<'SUCCESS'
  ╔═══════════════════════════════════════════════════╗
  ║           ¡Instalación completada!                ║
  ╚═══════════════════════════════════════════════════╝
SUCCESS
    fi
    echo -e "${NC}"
}

# ══════════════════════════════════════════════════════════════════════════════
# 4A. MODO CONTENEDOR
# ══════════════════════════════════════════════════════════════════════════════
if [[ "$INSTALL_MODE" == "1" ]]; then

    ask_servers_path
    install_python_deps
    check_java

    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
    success_banner
    echo -e "  $(L "Abre en tu navegador: " "Open in your browser: ") ${BOLD}http://${LOCAL_IP}:${WEB_PORT}${NC}"
    echo ""
    echo "  $(L "Arrancando la app (Ctrl+C para parar)..." "Starting the app (Ctrl+C to stop)...")"
    echo ""
    exec "$VENV_PYTHON" main.py

# ══════════════════════════════════════════════════════════════════════════════
# 4B. MODO NATIVO
# ══════════════════════════════════════════════════════════════════════════════
else

    ask_servers_path
    install_python_deps
    check_java

    sep "$(L "Creando servicio systemd" "Creating the systemd service")"

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
    ok "$(L "Servicio minecraft-deployer activo" "minecraft-deployer service running")"

    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
    success_banner
    echo -e "  $(L "Abre en tu navegador: " "Open in your browser: ") ${BOLD}http://${LOCAL_IP}:${WEB_PORT}${NC}"
    echo -e "  $(L "Usuario:              " "Username:             ") ${BOLD}$(grep -oP '(?<=^APP_USERNAME=).+' .env || echo 'admin')${NC}"
    echo ""
    echo "  $(L "Comandos útiles:" "Useful commands:")"
    echo "    $(L "Ver logs:    " "View logs:   ") sudo journalctl -u minecraft-deployer -f"
    echo "    $(L "Parar:       " "Stop:        ") sudo systemctl stop minecraft-deployer"
    echo "    $(L "Arrancar:    " "Start:       ") sudo systemctl start minecraft-deployer"
    echo "    $(L "Reconfigurar:" "Reconfigure: ") bash '${INSTALL_DIR}/install.sh'"
    echo ""

fi
