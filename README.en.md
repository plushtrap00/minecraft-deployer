# Minecraft Server Deployer

[Español](README.md) · **English**

A web panel (FastAPI + framework-free JavaScript) to create and manage modded Minecraft servers: install complete modpacks from Modrinth/CurseForge, search for and update mods, manage players (ops/whitelist/bans), worlds, a live console with chat, metrics and history, the firewall, backups, automatic restarts when the server crashes, scheduled tasks, and Telegram or Discord notifications. Built to be self-hosted on your own Linux server or VPS.

The panel is available in **Spanish (Spain) and English**: each account picks its own (see [Languages](#languages)).

And since running a Minecraft server doesn't have to be dull: four themes with their own pixel-art backgrounds, a scene that goes from night to day when the server starts, player heads, celebrations and more than thirty achievements to unlock (some of them secret).

**Current version: 3.0.0** (shown in **System → App updates**). What's new in [Versions](#versions).

## Requirements

- Linux (native, or Docker on any operating system).
- `sudo` access for the native installation (it creates a `systemd` service).
- Docker + Docker Compose for the container installation.

Python 3.10 or newer is needed (Ubuntu 22.04 or Debian 12 onwards already ship it). Python and Java are installed automatically if missing (in the native installation and in the "Container" mode of `install.sh`); the Docker image already includes them.

## Native Linux installation (recommended)

Installs the app as a `systemd` service: it starts with the system and restarts itself if it crashes.

```bash
git clone https://github.com/plushtrap00/minecraft-deployer
cd minecraft-deployer
bash install.sh
```

The installer asks you, step by step:

- **Language** (Spanish or English): used by the installer itself and as the panel's default language.
- **Installation mode** → choose `2) Native`.
- Folder to install the app in.
- Username and password to sign in to the panel.
- Web panel port (`8000` by default) and Minecraft port (`25565`).
- Public domain (optional — so players connect with a name instead of an IP).
- CurseForge API key (optional — **Modrinth works without it**; get one free at [console.curseforge.com](https://console.curseforge.com/#/api-keys)).
- Auto-update (optional — the app checks GitHub for a new version on its own).
- Telegram notifications (optional — see [Telegram and Discord notifications](#telegram-and-discord-notifications)).
- Java version (`17` or `21`, depending on which Minecraft versions you'll host).
- Where modpacks/servers are stored on disk.

When it finishes, the app is reachable at `http://<server-IP>:<port>` and running as the `minecraft-deployer` service.

Running `bash install.sh` again later updates the code (if there are new commits on GitHub) and restarts the service, without asking for the configuration again.

Useful commands:

```bash
sudo journalctl -u minecraft-deployer -f   # follow the logs
sudo systemctl stop minecraft-deployer     # stop
sudo systemctl start minecraft-deployer    # start
bash ~/minecraft-deployer/install.sh       # update / reconfigure
```

## Docker installation

### Option A — `docker compose` (recommended)

```bash
git clone https://github.com/plushtrap00/minecraft-deployer
cd minecraft-deployer
```

Generate the configuration with the interactive `setup.py` wizard: it asks for the language (Spanish or English, also the panel's default language), the administrator username and password, ports, Java version, where to store modpacks (a Docker volume or a host folder) and the other options, and generates both `.env` and a `docker-compose.yml` already tailored to your answers (no hand editing needed).

If you don't have Python on the host, run it inside a throwaway container so nothing gets installed outside Docker:

```bash
docker run --rm -it -v "$PWD":/app -w /app python:3.12-slim bash -c "pip install -q bcrypt && python setup.py"
```

(if you already have Python 3 with `bcrypt` available, `python3 setup.py` is enough)

Build and start:

```bash
docker compose build
docker compose up -d
```

The app is then reachable at `http://<host-IP>:<the-port-you-chose>`.

Useful commands:

```bash
docker compose logs -f        # follow the logs
docker compose restart        # restart
docker compose down           # stop (data persists in the chosen volume/folder)
docker compose up -d --build  # rebuild after updating the code (git pull)
```

To change anything later (the port, the password, the Java version...), run `python3 setup.py` again: it detects the existing configuration and uses each current value as the default, so just press Enter on everything except what you want to change (the password can also be left empty to keep it). Then rebuild and restart:

```bash
docker compose up -d --build
```

If you only want to change the username/password, `python3 set_password.py` is the quick way (without the other questions).

`docker-compose.yml` isn't in git (`setup.py` generates it, and every installation customises it — versioning it would make `git pull` conflict as soon as someone changed, say, the port). If you'd rather not run the wizard, `docker-compose.example.yml` is the reference template: copy it to `docker-compose.yml` and adjust what you need by hand.

### Option B — `install.sh` inside an already running container

If you already have a shell inside a Docker container (for example, one given to you by a hosting panel) and you'd rather not touch the `Dockerfile`, you can use the same installer as on native Linux:

```bash
bash install.sh
```

Choose `1) Container` when asked. It does exactly the same as native mode (virtual environment, dependencies, `.env`...) but without creating a `systemd` service — when it finishes, it starts the app directly in the foreground inside the container.

## Updating

There are three ways, depending on how you installed it:

- **From the panel itself**: if you turned on auto-update, the panel checks GitHub for a new version every so often and shows it in **System**. It's applied with the **Update now** button, only when no Minecraft server is running and no other operation is in progress, and the panel restarts itself. If the new version goes wrong (it doesn't load, start or respond), the panel goes back to the previous one on its own and says so right there; and if any of the app's files were changed by hand, it won't update so as not to overwrite them.
- **Native Linux**: run `bash install.sh` again (it downloads the new code and restarts the service). If you'd rather `git pull` by hand, **restart the service afterwards** (`sudo systemctl restart minecraft-deployer`): until then the previous version, already loaded in memory, keeps running.
- **Docker**: `git pull` and `docker compose up -d --build`.

There's no need to clear the browser cache: every panel file carries its own version in the URL and the browser fetches the new one as soon as it changes.

## After installing

- **First sign-in**: with the username and password you set during the installation (in any of the options).
- **CurseForge**: if you didn't add the API key during the installation, you can add it later from **Settings** inside the app (administrator only), without touching the console.
- **In-app tutorial**: the **Help** tab explains every section of the panel.
- **Session**: the sign-in is kept in a browser cookie (HttpOnly). When an account's password is changed or the account is deleted, its open sessions stop working.
- **Passwords**: each user changes their own with the padlock button in the top bar. The administrator can set a new one for any other user from **Users** (in case they forget it).
- **Two-step verification** (optional, per account): from the same padlock button. It asks for a 6-digit code from an app (Google Authenticator, Aegis, 2FAS, Bitwarden...) besides the password, and gives 8 single-use recovery codes. If someone loses their phone and the codes, the administrator removes it from **Users**; the administrator's own is removed with `python3 set_password.py`. It's stored in `SERVERS_PATH/.global/two_factor.json` (permissions `600`).
- **Failed attempts**: after several in a row, the account is locked for a few minutes from that IP; the lock is saved to disk and survives a panel restart.
- **Upload limits**: by default, 8 GB per file and 32 GB extracted. They're changed in **Settings → App constants → Uploads**.
- **Appearance**: the **Appearance** button in the top bar. That's where you pick the language, the theme (Amethyst, Overworld, Nether or End), turn sounds on (off by default) and see the achievement list. Your language and achievements are saved in your account (the same wherever you log in from); theme and sounds in each browser.

## Languages

The whole panel is available in Spanish (Spain) and English: pages, messages, server errors, Help and achievements.

- **Each account has its own language**: it's picked in **Appearance** and applied on sign-in, from any device. An account that hasn't chosen yet keeps the sign-in screen's language.
- **Default language** (`APP_LANGUAGE` in `.env`): used for the sign-in screen and for accounts that haven't chosen. The installer asks for it, and it can be changed in **Settings → Environment variables**.
- **Telegram and Discord notifications**: the administrator picks their language in **Settings → Notifications** (`NOTIFY_LANGUAGE`), whatever each account uses. Restart warnings that players see in the in-game chat use the default language.

## Backups, automation and notifications

- **Backups**: in **Modpacks → Backups**, of the world or full (mods, config, scripts, player lists and the world; without `libraries/` or logs, which are regenerated). They can be made with the server running (the panel pauses saving while it copies), downloaded and restored (with the server stopped; a backup of the current state is saved first). They're stored in `SERVERS_PATH/.global/backups/<modpack>/`; a backup that won't fit on the disk isn't started, and the panel warns when space is running low. In **Automation** you can choose a **secondary destination** (another disk, a NAS or a mounted network folder; in Docker, mounted as a volume) where every backup is duplicated: if the main disk fails, they still show up in the list and are restored from there.
- **Automation**: the **Automation** section of the panel. Automatic restart when the server crashes (with a limit on attempts), automatic backups every N hours keeping the latest ones, and scheduled tasks (restart, stop, start, command or backup) with an advance warning to players. Settings live in `SERVERS_PATH/.global/automation.json` and work even when nobody has the panel open.
- **Updating a modpack** to another version (**Update modpack** button when managing it): full backup first, clean install of the new version in a separate folder and a merge that doesn't touch the world, `server.properties` or the player lists; the mods you added are kept. The origin is saved in `<modpack>/.pack_source.json` when installing from Modrinth/CurseForge (older installs are linked by searching for them once). It runs on the server even if the browser is closed.
- **Updating mods**: in **Modpacks → Mods → Check for updates**. Each jar is recognised by its hash on Modrinth (and on CurseForge with `CURSEFORGE_API_KEY`), the latest version for the server's Minecraft version and modloader is offered (never going from stable to beta) and the ones you pick are updated, checking the hash of the download. The old jars stay in `<modpack>/.mods-replaced/` (the last 3 batches) and «Undo» puts them back.
- **Clone** a modpack, player **statistics** (from the world files), 24 h / 7 day **performance charts** (`.global/history/`) and a **chat** view in the console.

### Telegram and Discord notifications

Optional. The panel can message you when the server is ready, stops, crashes, someone joins or leaves, a backup fails, an installation finishes or a scheduled task runs (you choose which).

Each installation uses **its own bot**, so notifications only reach whoever sets it up:

1. In Telegram, open **@BotFather**, send it `/newbot` and pick a name. It will give you a token.
2. Open your new bot and send it anything (for example `/start`).
3. Paste the token in **Settings → Notifications** and press **Detect**: the panel finds your chat by itself. Save, then use **Send test**.

The installer (`install.sh` / `setup.py`) asks for it too, and it can be left empty. For Discord, a channel webhook URL is enough (channel settings → Integrations → Webhooks). The message language is chosen on that same tab. Everything is stored in `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DISCORD_WEBHOOK_URL`, `NOTIFY_EVENTS`, `NOTIFY_LANGUAGE`), but it applies immediately, without restarting the panel.

## Versions

### 3.0.0 (November 2026)

The panel, in English:

- **Everything translated**: pages, dialogs, messages, dates and numbers, server errors and progress, Help, achievements and the sign-in screen phrases. Spanish remains the original.
- **Each account has its own language**, saved in the account rather than the browser.
- **Notification language** for Telegram and Discord, chosen by the administrator.
- **Bilingual installers**: `install.sh` and `setup.py` ask for the language first and set it as the panel's default language.
- Decimal numbers use the comma in Spanish (1,5 GB).

Between 2.0 and 3.0 the panel also gained backups, automation (restart after crashes, automatic backups and scheduled tasks), Telegram and Discord notifications, player statistics, performance charts and the console chat. The full history is in the panel itself (**System → App updates**, in Spanish).

### 2.0.0 (November 2026)

Security review and polish:

- **RAM validated on every path**: when creating a server or installing a modpack, the RAM was written to `run.sh` unchecked, and a tampered value could slip in commands. Now only a number with `M` or `G` is accepted.
- **Private `.env` and `users.json`**: the panel sets them to `600` permissions on start-up (and the installer when creating them). They hold the session secret and the password hashes.
- **Configurable upload limits**, which also stop "zip bombs": the extracted size of an archive is checked before extracting it, along with whether it fits on disk.
- **Harder-to-brute-force sign-in**: lockout per IP as well (with any username) and the same delay whether the user exists or not, so nobody can find out which users exist.
- **Change your own password** from the panel, and reset other users' passwords (admin). Changing the admin's password from Settings no longer waits for a restart.
- **Update now** for administrators only.
- Strict **Content-Security-Policy**: the browser only runs the panel's own scripts.
- **Atomic writes** for `server.properties`, configs, KubeJS scripts, world files and `users.json`: if something fails halfway, the previous file stays intact.
- Download names with quotes or accents encoded properly; clean-up of failed imports moved out of the main loop; a top bar that no longer gets cut off on medium screens.

### 1.x

Everything before, unnumbered.

## Development and tests

The tests use only the standard library and don't touch your servers (they point `SERVERS_PATH` at a temporary folder). From the repository root, with the dependencies from `requirements.txt` installed:

```bash
python -m unittest discover -s tests -t .
```

They cover path and name validation, safe archive extraction, sessions, firewall parsing, JVM RAM, player UUIDs, the page being assembled in full, the scripts in `static/js` not clashing on global names, and the translations.

### Back-end layout

- `main.py` creates the app and the session middleware and registers the routers; before starting, `services/startup_cleanup.py` frees ports and stops orphaned servers left by a previous run.
- `routes/` has one file per group of API routes (`server.py`, `mods.py`, `backups.py`, `automation.py`...) and only validates and translates requests; the logic lives in `services/`.
- In `services/`, modpack handling is split by topic: `modpack.py` (version, `server.properties`, worlds, logs), `mod_metadata.py` (reading a `.jar` and comparing versions), `mod_checks.py` (client-only mods, duplicates, what to do with each uploaded `.jar`), `pending_mods.py` (mods to install by hand) and `crash_analysis.py`. The running server lives in `process.py` (process and console) and `server_control.py` (start, stop, restart after a crash); automation in `automation.py` (settings) and `scheduler.py` (the thread that runs tasks, backups and history samples).

### Front-end layout

- `static/index.html` is just the skeleton: styles, scripts and one `<!-- include: ... -->` line per piece.
- `static/partials/` holds one HTML file per page (`pages/`), per Modpacks tab (`manage/`), per group of modals (`modals/`) and the shared blocks (for example `ram-fields.html`, which takes parameters). `services/frontend.py` joins them when serving `/`, so the browser still gets a single page.
- `static/js/` has one file per section or tab (`server_props.js`, `jvm_ram.js`, `file_editor.js`, `kubejs.js`...), all in the global scope and loaded in `index.html` order.
- **Translations**: all text is written in Spanish and `static/i18n/en.json` is a map of whole phrases ("Spanish phrase" → "English phrase"), with `{name}` placeholders for data. HTML is translated when served (`services/i18n.py`), JavaScript uses `t('Frase', {data})` (`static/js/i18n.js`) and back-end messages are translated in `services/i18n_middleware.py` (the `detail`, `message`, `reason`… fields of JSON responses and SSE events; phrases with data work as templates). The tests fail if a new HTML phrase, a `t('…')`, an achievement or a back-end message is left untranslated.
- Colours live as tokens in `static/css/base.css`; `themes.css` defines the themes (Amethyst, Overworld, Nether and End) by changing those tokens and each one's page background (`--bg-pattern`, pixel-art SVG textures, and `--bg-extra`, a gradient on top), and `scene.css` the pixel-art scene in the Server header and the sign-in screen, the segmented bars and the celebrations. Scrollbars also come from the tokens (at the end of `base.css`), and `search.css` styles the two Modrinth/CurseForge searches: cards with the icon in an inventory slot, a halo in the icon's colour and an enchantment glint on the chosen modpack. `static/js/appearance.js` stores the theme in the browser, `sounds.js` the sounds (off by default), `achievements.js` the achievements and `pixel_art.js` draws logos, fallback heads and empty states. A new achievement is an entry in `ACHIEVEMENTS` (in `achievements.js`) (with `secret: true` if it should show as "???" until unlocked), its 10x10 pixel-art icon in `achievement_icons.js` (a test checks none is missing), its name and hint in `en.json`, and an `unlockAchievement('id')` call where it happens. Sounds are in `SOUNDS`, and what plays when you click something depends on what it does (`soundForControl`): switching section, starting, deleting, closing, turning on or off, picking a theme... A button can choose its own with `data-sound`.
- When `/` is served, every `/static/...` gets `?v=` with that file's modification time, and those responses are marked immutable: the browser keeps them indefinitely and only downloads the ones that change.
- Player heads are fetched from mc-heads.net through `/api/players/head/{name}` and cached for a few days in `.global/heads/`. A modpack's logo is its `server-icon.png` or, if it was installed from Modrinth or CurseForge, the store's (`.mcdeployer/icon.*` inside its folder). Without internet, the panel draws a face or a block in the name's colours.
