# King Deobfuscator Bot 🔓

Bot de Discord que deobfusca scripts `.lua` protegidos con **Prometheus Obfuscator / MoonsecV2 / MoonsecV3**, corriendo 24/7 en Render.

Basado en [Prometheus-Deobfuscator](https://github.com/0x251/Prometheus-Deobfuscator).

## Cómo usarlo

**Slash command:**
/deobf archivo:<tu_script.lua>
**Prefijo:**
!deobf
(adjuntando un `.lua` al mensaje)

**Auto-deob:**
Solo manda un `.lua` adjunto o pega un link que termine en `.lua` en cualquier canal donde esté el bot, y lo procesa solo.

## Features del deobfuscador

- Reversión de polimorfismo multi-capa
- Análisis y devirtualización de estructuras VM
- Reconstrucción de control flow graph
- Desencriptación de literales híbridos (Base64/Hex/Decimal)
- Reversión de encriptación de strings
- Detección de anti-debugging / anti-tamper

## Setup / Deploy

1. Clona este repo.
2. Crea una app en el [Discord Developer Portal](https://discord.com/developers/applications), activa el intent `MESSAGE CONTENT`, e invita el bot con los scopes `bot` + `applications.commands`.
3. Sube el repo a Render como **Web Service**.
4. Configura la variable de entorno `DISCORD_TOKEN` en Render.
5. Deploy. Render expone un endpoint `/` para health checks (usalo con UptimeRobot para mantenerlo despierto).

## Variables de entorno

| Variable | Descripción |
|---|---|
| `DISCORD_TOKEN` | Token del bot de Discord (requerido) |
| `COMMAND_PREFIX` | Prefijo de comandos de texto (default: `!`) |
| `PORT` | Puerto del keep-alive (lo setea Render automático) |

## Créditos

By **King Deobfuscator** — [discord.gg/85aX5f5WHz](https://discord.gg/85aX5f5WHz)

Deobfuscador original: [0x251/Prometheus-Deobfuscator](https://github.com/0x251/Prometheus-Deobfuscator) (MIT License)

---
**Disclaimer:** herramienta con fines educativos. Úsala solo en código sobre el que tengas derechos legales.
