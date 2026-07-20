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
DISCORD_INVITE = "https://discord.gg/85aX5f5WHz"
SUCCESS_MESSAGE = f"DEOB SUCCESSFULLY GANG\nBY KING DEOBFUSCATOR — {DISCORD_INVITE}"

if not DISCORD_TOKEN:
    raise RuntimeError(
        "Falta la variable de entorno DISCORD_TOKEN. "
        "Configúrala en Render (Environment > Add Environment Variable)."
    )

intents = discord.Intents.default()
intents.message_content = True  # necesario para leer attachments/mensajes normales

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(BASE_DIR, "modules")

# módulos exactos que pol.py necesita — nombres EXACTOS, sensibles a mayúsculas
REQUIRED_MODULE_FILES = [
    "clean_gens.py",
    "consts.py",
    "debugging.py",
    "reverse_pipes.py",
    "tokenizers.py",
    "vmify.py",
    "__init__.py",
]

# URL que apunta directo a un archivo .lua (raw de github/pastebin/etc)
LUA_URL_RE = re.compile(r"https?://\S+\.lua(?:\?\S*)?", re.IGNORECASE)

# bloque de código pegado en el mensaje, ej. ```lua ... ``` o con marcadores de Prometheus
CODE_BLOCK_RE = re.compile(r"```(?:lua)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
PROMETHEUS_HINTS = ("PHASE_BOUNDARY", "getfenv", "loadstring", "MoonSec", "Prometheus")


def check_repo_health() -> str | None:
    """
    Revisa que pol.py y todos los módulos existan con el nombre exacto.
    Devuelve None si todo está bien, o un mensaje de diagnóstico si falta algo.
    """
    problems = []

    if not os.path.exists(os.path.join(BASE_DIR, "pol.py")):
        problems.append("- Falta `pol.py` en la raíz del repo.")

    if not os.path.isdir(MODULES_DIR):
        problems.append("- No existe la carpeta `modules/` en la raíz del repo.")
    else:
        existing = set(os.listdir(MODULES_DIR))
        for fname in REQUIRED_MODULE_FILES:
            if fname == "__init__.py":
                continue  # opcional, Python 3 no lo necesita
            if fname not in existing:
                problems.append(f"- Falta `modules/{fname}` (revisa mayúsculas/minúsculas exactas).")

    if problems:
        return "Problemas encontrados en el repo:\n" + "\n".join(problems)
    return None


# ---------------------------------------------------------------------------
# Stats en memoria (para el dashboard)
# ---------------------------------------------------------------------------
STATS_LOCK = threading.Lock()
STATS = {
    "start_time": time.time(),
    "commands_run": 0,
    "visits": 0,
}


def bump(key: str):
    with STATS_LOCK:
        STATS[key] += 1


# ---------------------------------------------------------------------------
# Keep-alive web server (para que Render exponga un puerto HTTP y
# UptimeRobot tenga algo que pinguear sin 404)
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
    t = threading.Thread(target=run_web, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Lógica central: correr pol.py sobre un archivo .lua
# ---------------------------------------------------------------------------
def run_deobfuscator(input_path: str, timeout: int = 120):
    """
    Corre pol.py sobre input_path. Devuelve (output_path, error_msg).
    error_msg es None si todo salió bien.
    """
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
                "Falta un archivo en la carpeta `modules/` de tu repo de GitHub "
                "(o el nombre no coincide exactamente, GitHub/Render es sensible a "
                "mayúsculas y minúsculas).\n```\n" + stderr[-800:] + "\n```"
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

    await bot.process_commands(message)

    # --- auto-deob: archivo .lua adjunto ---
    for attachment in message.attachments:
        if attachment.filename.endswith(".lua"):
            await auto_deobfuscate(message, source="attachment", value=attachment.url, filename=attachment.filename)
            return

    content = message.content or ""

    # --- auto-deob: link a un .lua en el texto ---
    match = LUA_URL_RE.search(content)
    if match:
        url = match.group(0)
        await auto_deobfuscate(message, source="url", value=url, filename=url.split("/")[-1].split("?")[0])
        return

    # --- auto-deob: código pegado en bloque ```lua ... ``` ---
    code_match = CODE_BLOCK_RE.search(content)
    if code_match:
        code = code_match.group(1).strip()
        is_lua_tagged = content.strip().lower().startswith("```lua")
        if code and (is_lua_tagged or looks_like_obfuscated_lua(code)):
            await auto_deobfuscate(message, source="text", value=code, filename="pasted_script.lua")


async def auto_deobfuscate(message: discord.Message, source: str, value: str, filename: str):
    bump("commands_run")
    async with message.channel.typing():
        with tempfile.TemporaryDirectory() as tmp_dir:
            if source == "text":
                input_path = save_text_to_temp(value, tmp_dir, filename)
            else:
                input_path = await download_to_temp(value, tmp_dir)
                if input_path is None:
                    await message.reply("No pude descargar ese archivo/link.")
                    return

            output_path, error = run_deobfuscator(input_path)
            if output_path is None:
                await message.reply(f"No se pudo deobfuscar.\n{error}")
                return

            await message.reply(
                SUCCESS_MESSAGE,
                file=discord.File(output_path),
            )


# ---------------------------------------------------------------------------
# Comando con prefijo (!deobf) — con archivo o con texto pegado
# ---------------------------------------------------------------------------
@bot.command(name="deobf")
async def deobf_prefix(ctx: commands.Context, *, codigo: str = None):
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
# Slash commands
# ---------------------------------------------------------------------------
@bot.tree.command(name="deobf", description="Deobfusca un script .lua ofuscado con Prometheus (archivo)")
@app_commands.describe(archivo="El archivo .lua que quieres deobfuscar")
async def deobf_slash(interaction: discord.Interaction, archivo: discord.Attachment):
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
            await interaction.followup.send(f"No se pudo deobfuscar.\n{error}")
            return

        await interaction.followup.send(
            SUCCESS_MESSAGE,
            file=discord.File(output_path),
        )


@bot.tree.command(name="deobftext", description="Deobfusca código Lua pegado directamente como texto")
@app_commands.describe(codigo="Pega aquí el script Lua ofuscado")
async def deobftext_slash(interaction: discord.Interaction, codigo: str):
    await interaction.response.defer(thinking=True)
    bump("commands_run")

    with tempfile.TemporaryDirectory() as tmp_dir:
        code_match = CODE_BLOCK_RE.search(codigo)
        code = code_match.group(1).strip() if code_match else codigo.strip()
        input_path = save_text_to_temp(code, tmp_dir)

        output_path, error = run_deobfuscator(input_path)
        if output_path is None:
            await interaction.followup.send(f"No se pudo deobfuscar.\n{error}")
            return

        await interaction.followup.send(
            SUCCESS_MESSAGE,
            file=discord.File(output_path),
        )


@bot.tree.command(name="stats", description="Muestra las estadísticas en vivo del bot")
async def stats_slash(interaction: discord.Interaction):
    with STATS_LOCK:
        commands_run = STATS["commands_run"]
        visits = STATS["visits"]
        uptime_seconds = int(time.time() - STATS["start_time"])
    guild_count = len(bot.guilds)

    h, rem = divmod(uptime_seconds, 3600)
    m, s = divmod(rem, 60)

    embed = discord.Embed(title="👑 King Deobfuscator — Stats", color=discord.Color.purple())
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
        **King Deobfuscator — Comandos**

        `/deobf archivo:` — sube un archivo `.lua` y lo deobfusca.
        `/deobftext codigo:` — pega el script Lua directo como texto.
        `!deobf` — igual que `/deobf`, adjuntando el archivo al mensaje o pegando ```lua ... ``` después del comando.
        **Auto-deob** — manda un `.lua`, un link a un `.lua`, o pega un bloque ```lua ... ``` en cualquier canal y lo detecto solo.
        `/stats` — estadísticas en vivo del bot.
        `/ping` — latencia del bot.

        By King Deobfuscator — {DISCORD_INVITE}
    """).strip()
    await interaction.response.send_message(text)


if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
