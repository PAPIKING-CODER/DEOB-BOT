import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import threading
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask, render_template, jsonify

try:
    from dotenv import load_dotenv
    load_dotenv()  # no hace nada si no existe .env (ej. en Render)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
COMMAND_PREFIX = os.environ.get("COMMAND_PREFIX", "!")
OWNER_ID = os.environ.get("OWNER_ID")  # tu ID de Discord, string
DISCORD_INVITE = "https://discord.gg/85aX5f5WHz"
SUCCESS_MESSAGE = f"DEOB SUCCESSFULLY GANG\nBY KING DEOBFUSCATOR — {DISCORD_INVITE}"

if not DISCORD_TOKEN:
    raise RuntimeError(
        "Falta la variable de entorno DISCORD_TOKEN. "
        "Configúrala en Render (Environment > Add Environment Variable)."
    )

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # necesario para resolver usuarios en whitelist/blacklist

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(BASE_DIR, "modules")
DATA_PATH = os.path.join(BASE_DIR, "bot_data.json")

REQUIRED_MODULE_FILES = [
    "clean_gens.py",
    "consts.py",
    "debugging.py",
    "reverse_pipes.py",
    "tokenizers.py",
    "vmify.py",
]

LUA_URL_RE = re.compile(r"https?://\S+\.lua(?:\?\S*)?", re.IGNORECASE)
CODE_BLOCK_RE = re.compile(r"```(?:lua)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
PROMETHEUS_HINTS = ("PHASE_BOUNDARY", "getfenv", "loadstring", "MoonSec", "Prometheus")

# ---------------------------------------------------------------------------
# Emojis personalizados de tu server (decoración)
# Formato: <:nombre:id> — solo se ven bien si el bot está en ese mismo server.
# ---------------------------------------------------------------------------
EMOJI_IDS = {
    "success": "1525379448768303207",
    "failed": "1526857565156147250",
    "clown": "1526858087510835252",
    "warning": "1526855124134137856",
    "crown": "1526742765311098980",
    "gold_key": "1525381310200414310",
    "loader": "1526741970226253834",
    "search": "1526851410283728898",
    "owner": "1526850915418509362",
    "settings": "1526853210231410810",
}


def emoji(name: str) -> str:
    eid = EMOJI_IDS.get(name)
    return f"<:{name}:{eid}>" if eid else ""


# ---------------------------------------------------------------------------
# Persistencia simple en JSON (whitelist, blacklist, canal de auto-deob)
# NOTA: en Render (plan free) el disco persiste entre reinicios pero se
# borra en cada nuevo deploy. Si necesitas que esto sea 100% permanente,
# lo ideal es moverlo a una base de datos (te puedo ayudar con eso después).
# ---------------------------------------------------------------------------
def load_data() -> dict:
    if os.path.exists(DATA_PATH):
        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"whitelist": [], "blacklist": [], "setup_channel_id": None}


def save_data():
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(DATA, f)


DATA = load_data()


def is_owner_user(user: discord.abc.User) -> bool:
    if OWNER_ID and str(user.id) == OWNER_ID:
        return True
    return False


def is_blacklisted(user_id: int) -> bool:
    return str(user_id) in DATA["blacklist"]


def is_allowed(user: discord.abc.User) -> bool:
    """owner siempre puede. Si hay blacklist, bloquea. Si hay whitelist activa, solo esos pueden."""
    if is_owner_user(user):
        return True
    if is_blacklisted(user.id):
        return False
    if DATA["whitelist"]:
        return str(user.id) in DATA["whitelist"]
    return True


def check_repo_health() -> str | None:
    problems = []
    if not os.path.exists(os.path.join(BASE_DIR, "pol.py")):
        problems.append("- Falta `pol.py` en la raíz del repo.")
    if not os.path.isdir(MODULES_DIR):
        problems.append("- No existe la carpeta `modules/` en la raíz del repo.")
    else:
        existing = set(os.listdir(MODULES_DIR))
        for fname in REQUIRED_MODULE_FILES:
            if fname not in existing:
                problems.append(f"- Falta `modules/{fname}` (revisa mayúsculas/minúsculas exactas).")
    if problems:
        return "Problemas encontrados en el repo:\n" + "\n".join(problems)
    return None


# ---------------------------------------------------------------------------
# Stats en memoria (para el dashboard)
# ---------------------------------------------------------------------------
STATS_LOCK = threading.Lock()
STATS = {"start_time": time.time(), "commands_run": 0, "visits": 0}


def bump(key: str):
    with STATS_LOCK:
        STATS[key] += 1


# ---------------------------------------------------------------------------
# Keep-alive web server
# ---------------------------------------------------------------------------
app = Flask(__name__)


@app.route("/")
def home():
    bump("visits")
    return render_template("index.html")


@app.route("/api/stats")
def api_stats():
    with STATS_LOCK:
        commands_run = STATS["commands_run"]
        visits = STATS["visits"]
        uptime_seconds = int(time.time() - STATS["start_time"])
    guild_count = len(bot.guilds) if bot.is_ready() else 0
    return jsonify({
        "uptime_seconds": uptime_seconds,
        "guild_count": guild_count,
        "commands_run": commands_run,
        "visits": visits,
    })


@app.route("/health")
def health():
    return {"status": "ok", "bot_ready": bot.is_ready()}, 200


def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    threading.Thread(target=run_web, daemon=True).start()


# ---------------------------------------------------------------------------
# Deobfuscador
# ---------------------------------------------------------------------------
def run_deobfuscator(input_path: str, timeout: int = 120):
    repo_problem = check_repo_health()
    if repo_problem:
        return None, repo_problem

    output_path = input_path.replace(".lua", "_deobf.lua")
    try:
        result = subprocess.run(
            [sys.executable, "pol.py", input_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=BASE_DIR,
        )
    except subprocess.TimeoutExpired:
        return None, "El script tardó demasiado y se canceló."

    if not os.path.exists(output_path):
        stderr = result.stderr or "Error desconocido."
        if "ModuleNotFoundError" in stderr:
            return None, (
                "Falta un archivo en `modules/` de tu repo (o el nombre no coincide "
                "exactamente).\n```\n" + stderr[-800:] + "\n```"
            )
        return None, stderr[-1500:]

    return output_path, None


async def download_to_temp(url: str, tmp_dir: str) -> str | None:
    filename = url.split("/")[-1].split("?")[0]
    if not filename.endswith(".lua"):
        filename += ".lua"
    dest_path = os.path.join(tmp_dir, filename)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                return None
            data = await resp.read()
    with open(dest_path, "wb") as f:
        f.write(data)
    return dest_path


def save_text_to_temp(code: str, tmp_dir: str, filename: str = "pasted_script.lua") -> str:
    dest_path = os.path.join(tmp_dir, filename)
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(code)
    return dest_path


def looks_like_obfuscated_lua(text: str) -> bool:
    if not text:
        return False
    return any(hint.lower() in text.lower() for hint in PROMETHEUS_HINTS)


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------
@bot.event
async def on_ready():
    print(f"Conectado como {bot.user} (id: {bot.user.id})")
    problem = check_repo_health()
    if problem:
        print("=" * 60)
        print("ADVERTENCIA — el repo tiene archivos faltantes:")
        print(problem)
        print("=" * 60)
    else:
        print("Repo OK: pol.py y todos los módulos están presentes.")
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Error sincronizando slash commands: {e}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if is_blacklisted(message.author.id):
        await bot.process_commands(message)  # deja que commands.py maneje el bloqueo si aplica
        return

    await bot.process_commands(message)

    setup_channel_id = DATA.get("setup_channel_id")
    content = message.content or ""

    # si hay un canal configurado con /setupdeob, el auto-deob SOLO corre ahí
    if setup_channel_id is not None:
        if message.channel.id != setup_channel_id:
            return
        handled = await try_auto_deob(message, content)
        if not handled:
            await message.reply(f"{emoji('failed')} That's not a valid script.")
        return

    # sin canal configurado: auto-deob funciona en cualquier canal (comportamiento anterior)
    await try_auto_deob(message, content)


async def try_auto_deob(message: discord.Message, content: str) -> bool:
    """Intenta detectar y procesar un .lua adjunto, un link, o texto pegado. Devuelve True si procesó algo."""
    for attachment in message.attachments:
        if attachment.filename.endswith(".lua"):
            await auto_deobfuscate(message, source="attachment", value=attachment.url, filename=attachment.filename)
            return True

    match = LUA_URL_RE.search(content)
    if match:
        url = match.group(0)
        await auto_deobfuscate(message, source="url", value=url, filename=url.split("/")[-1].split("?")[0])
        return True

    code_match = CODE_BLOCK_RE.search(content)
    if code_match:
        code = code_match.group(1).strip()
        is_lua_tagged = content.strip().lower().startswith("```lua")
        if code and (is_lua_tagged or looks_like_obfuscated_lua(code)):
            await auto_deobfuscate(message, source="text", value=code, filename="pasted_script.lua")
            return True

    return False


async def auto_deobfuscate(message: discord.Message, source: str, value: str, filename: str):
    if not is_allowed(message.author):
        await message.reply(f"{emoji('warning')} No tienes permiso para usar este bot.")
        return

    bump("commands_run")
    async with message.channel.typing():
        with tempfile.TemporaryDirectory() as tmp_dir:
            if source == "text":
                input_path = save_text_to_temp(value, tmp_dir, filename)
            else:
                input_path = await download_to_temp(value, tmp_dir)
                if input_path is None:
                    await message.reply(f"{emoji('failed')} No pude descargar ese archivo/link.")
                    return

            output_path, error = run_deobfuscator(input_path)
            if output_path is None:
                await message.reply(f"{emoji('failed')} No se pudo deobfuscar.\n{error}")
                return

            await message.reply(
                f"{emoji('success')} {SUCCESS_MESSAGE}",
                file=discord.File(output_path),
            )


# ---------------------------------------------------------------------------
# Comando con prefijo (!deobf)
# ---------------------------------------------------------------------------
@bot.command(name="deobf")
async def deobf_prefix(ctx: commands.Context, *, codigo: str = None):
    if not is_allowed(ctx.author):
        await ctx.reply(f"{emoji('warning')} No tienes permiso para usar este bot.")
        return

    if ctx.message.attachments:
        attachment = ctx.message.attachments[0]
        if not attachment.filename.endswith(".lua"):
            await ctx.reply("Solo acepto archivos `.lua`.")
            return
        await auto_deobfuscate(ctx.message, source="attachment", value=attachment.url, filename=attachment.filename)
        return

    if codigo:
        code_match = CODE_BLOCK_RE.search(codigo)
        code = code_match.group(1).strip() if code_match else codigo.strip()
        if code:
            await auto_deobfuscate(ctx.message, source="text", value=code, filename="pasted_script.lua")
            return

    await ctx.reply(
        "Adjunta un archivo `.lua`, o pega el código así:\n"
        "`!deobf` seguido de un bloque ```lua ... ```"
    )


# ---------------------------------------------------------------------------
# Slash commands — deobfuscador
# ---------------------------------------------------------------------------
@bot.tree.command(name="deobf", description="Deobfusca un script .lua ofuscado con Prometheus (archivo)")
@app_commands.describe(archivo="El archivo .lua que quieres deobfuscar")
async def deobf_slash(interaction: discord.Interaction, archivo: discord.Attachment):
    if not is_allowed(interaction.user):
        await interaction.response.send_message(f"{emoji('warning')} No tienes permiso para usar este bot.", ephemeral=True)
        return
    if not archivo.filename.endswith(".lua"):
        await interaction.response.send_message("Solo acepto archivos `.lua`.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    bump("commands_run")

    with tempfile.TemporaryDirectory() as tmp_dir:
        input_path = os.path.join(tmp_dir, archivo.filename)
        await archivo.save(input_path)
        output_path, error = run_deobfuscator(input_path)
        if output_path is None:
            await interaction.followup.send(f"{emoji('failed')} No se pudo deobfuscar.\n{error}")
            return
        await interaction.followup.send(f"{emoji('success')} {SUCCESS_MESSAGE}", file=discord.File(output_path))


@bot.tree.command(name="deobftext", description="Deobfusca código Lua pegado directamente como texto")
@app_commands.describe(codigo="Pega aquí el script Lua ofuscado")
async def deobftext_slash(interaction: discord.Interaction, codigo: str):
    if not is_allowed(interaction.user):
        await interaction.response.send_message(f"{emoji('warning')} No tienes permiso para usar este bot.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    bump("commands_run")

    with tempfile.TemporaryDirectory() as tmp_dir:
        code_match = CODE_BLOCK_RE.search(codigo)
        code = code_match.group(1).strip() if code_match else codigo.strip()
        input_path = save_text_to_temp(code, tmp_dir)
        output_path, error = run_deobfuscator(input_path)
        if output_path is None:
            await interaction.followup.send(f"{emoji('failed')} No se pudo deobfuscar.\n{error}")
            return
        await interaction.followup.send(f"{emoji('success')} {SUCCESS_MESSAGE}", file=discord.File(output_path))


@bot.tree.command(name="stats", description="Muestra las estadísticas en vivo del bot")
async def stats_slash(interaction: discord.Interaction):
    with STATS_LOCK:
        commands_run = STATS["commands_run"]
        visits = STATS["visits"]
        uptime_seconds = int(time.time() - STATS["start_time"])
    guild_count = len(bot.guilds)
    h, rem = divmod(uptime_seconds, 3600)
    m, s = divmod(rem, 60)

    embed = discord.Embed(title=f"{emoji('crown')} King Deobfuscator — Stats", color=discord.Color.purple())
    embed.add_field(name="Uptime", value=f"{h}h {m}m {s}s", inline=True)
    embed.add_field(name="Servidores", value=str(guild_count), inline=True)
    embed.add_field(name="Deobfuscaciones", value=str(commands_run), inline=True)
    embed.add_field(name="Visitas web", value=str(visits), inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ping", description="Revisa la latencia del bot")
async def ping_slash(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! {round(bot.latency * 1000)}ms")


@bot.tree.command(name="help", description="Muestra cómo usar King Deobfuscator")
async def help_slash(interaction: discord.Interaction):
    text = textwrap.dedent(f"""
        {emoji('crown')} **King Deobfuscator — Comandos**

        `/deobf archivo:` — sube un archivo `.lua` y lo deobfusca.
        `/deobftext codigo:` — pega el script Lua directo como texto.
        `!deobf` — igual, adjuntando el archivo o pegando ```lua ... ```.
        **Auto-deob** — manda un `.lua`, un link, o pega ```lua ... ``` y lo detecto solo.
        `/stats` — estadísticas en vivo.
        `/ping` — latencia del bot.

        **Solo owner:**
        `/whitelist add|remove usuario:` `/blacklist add|remove usuario:` `/setupdeob canal:`

        By King Deobfuscator — {DISCORD_INVITE}
    """).strip()
    await interaction.response.send_message(text)


# ---------------------------------------------------------------------------
# Slash commands — administración (solo owner)
# ---------------------------------------------------------------------------
def owner_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if is_owner_user(interaction.user):
            return True
        await interaction.response.send_message(
            f"{emoji('warning')} Solo el owner del bot puede usar esto.", ephemeral=True
        )
        return False
    return app_commands.check(predicate)


whitelist_group = app_commands.Group(name="whitelist", description="Administra la whitelist (solo owner)")
blacklist_group = app_commands.Group(name="blacklist", description="Administra la blacklist (solo owner)")


@whitelist_group.command(name="add", description="Agrega un usuario a la whitelist")
@owner_only()
async def whitelist_add(interaction: discord.Interaction, usuario: discord.User):
    uid = str(usuario.id)
    if uid not in DATA["whitelist"]:
        DATA["whitelist"].append(uid)
        save_data()
    await interaction.response.send_message(f"{emoji('success')} {usuario.mention} agregado a la whitelist.")


@whitelist_group.command(name="remove", description="Quita un usuario de la whitelist")
@owner_only()
async def whitelist_remove(interaction: discord.Interaction, usuario: discord.User):
    uid = str(usuario.id)
    if uid in DATA["whitelist"]:
        DATA["whitelist"].remove(uid)
        save_data()
    await interaction.response.send_message(f"{emoji('success')} {usuario.mention} quitado de la whitelist.")


@blacklist_group.command(name="add", description="Agrega un usuario a la blacklist (no podrá usar el bot)")
@owner_only()
async def blacklist_add(interaction: discord.Interaction, usuario: discord.User):
    uid = str(usuario.id)
    if uid not in DATA["blacklist"]:
        DATA["blacklist"].append(uid)
        save_data()
    await interaction.response.send_message(f"{emoji('failed')} {usuario.mention} agregado a la blacklist.")


@blacklist_group.command(name="remove", description="Quita un usuario de la blacklist")
@owner_only()
async def blacklist_remove(interaction: discord.Interaction, usuario: discord.User):
    uid = str(usuario.id)
    if uid in DATA["blacklist"]:
        DATA["blacklist"].remove(uid)
        save_data()
    await interaction.response.send_message(f"{emoji('success')} {usuario.mention} quitado de la blacklist.")


bot.tree.add_command(whitelist_group)
bot.tree.add_command(blacklist_group)


@bot.tree.command(name="setupdeob", description="Configura el canal donde el auto-deob detecta links/archivos (solo owner)")
@app_commands.describe(canal="Canal donde el bot va a auto-detectar scripts")
@owner_only()
async def setupdeob_slash(interaction: discord.Interaction, canal: discord.TextChannel):
    DATA["setup_channel_id"] = canal.id
    save_data()
    await interaction.response.send_message(
        f"{emoji('settings')} Canal de auto-deob configurado en {canal.mention}. "
        f"Fuera de ese canal el auto-deob ya no va a reaccionar solo (los comandos `/deobf` siguen funcionando en todos lados)."
    )


if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
