import os
import re
import subprocess
import sys
import tempfile
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

# URL que apunta directo a un archivo .lua (raw de github/pastebin/etc)
LUA_URL_RE = re.compile(r"https?://\S+\.lua(?:\?\S*)?", re.IGNORECASE)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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
# UptimeRobot tenga algo que pinguear cada 5 min sin 404)
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
    Corre pol.py sobre input_path. Devuelve (output_path, stderr) o (None, stderr) si falla.
    """
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
        error_msg = result.stderr[-1500:] if result.stderr else "Error desconocido."
        return None, error_msg

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


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------
@bot.event
async def on_ready():
    print(f"Conectado como {bot.user} (id: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Error sincronizando slash commands: {e}")


@bot.event
async def on_message(message: discord.Message):
    # no reaccionar a otros bots (evita loops)
    if message.author.bot:
        return

    # sigue procesando comandos normales tipo !deobf
    await bot.process_commands(message)

    # --- auto-deob: archivo .lua adjunto ---
    for attachment in message.attachments:
        if attachment.filename.endswith(".lua"):
            await auto_deobfuscate(message, attachment_url=attachment.url, filename=attachment.filename)
            return  # solo procesa el primero para no saturar

    # --- auto-deob: link a un .lua en el texto ---
    match = LUA_URL_RE.search(message.content or "")
    if match:
        url = match.group(0)
        await auto_deobfuscate(message, attachment_url=url, filename=url.split("/")[-1].split("?")[0])


async def auto_deobfuscate(message: discord.Message, attachment_url: str, filename: str):
    bump("commands_run")
    async with message.channel.typing():
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = await download_to_temp(attachment_url, tmp_dir)
            if input_path is None:
                await message.reply("No pude descargar ese archivo/link.")
                return

            output_path, error = run_deobfuscator(input_path)
            if output_path is None:
                await message.reply(f"No se pudo deobfuscar.\n```\n{error}\n```")
                return

            await message.reply(
                SUCCESS_MESSAGE,
                file=discord.File(output_path),
            )


# ---------------------------------------------------------------------------
# Comando con prefijo (!deobf) — se mantiene por compatibilidad
# ---------------------------------------------------------------------------
@bot.command(name="deobf")
async def deobf_prefix(ctx: commands.Context):
    if not ctx.message.attachments:
        await ctx.reply("Adjunta un archivo `.lua` junto con el comando `!deobf`.")
        return

    attachment = ctx.message.attachments[0]
    if not attachment.filename.endswith(".lua"):
        await ctx.reply("Solo acepto archivos `.lua`.")
        return

    await auto_deobfuscate(ctx.message, attachment_url=attachment.url, filename=attachment.filename)


# ---------------------------------------------------------------------------
# Slash command (/deobf)
# ---------------------------------------------------------------------------
@bot.tree.command(name="deobf", description="Deobfusca un script .lua ofuscado con Prometheus")
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
            await interaction.followup.send(f"No se pudo deobfuscar.\n```\n{error}\n```")
            return

        await interaction.followup.send(
            SUCCESS_MESSAGE,
            file=discord.File(output_path),
        )


if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
