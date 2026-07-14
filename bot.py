"""
bot.py — Main entry point for the Codeforces Discord Bot

On Render (free tier), this file also spins up a lightweight HTTP server
on port 8080. That makes Render treat it as a Web Service (which is free),
and UptimeRobot can ping the /health endpoint every 5 minutes to prevent
the service from sleeping.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from threading import Thread

from aiohttp import web
import discord
from discord.ext import commands

import config
from cf_api.client import CodeforcesClient
from db.database import get_db, init_db

os.makedirs("data", exist_ok=True)

# On Render, RENDER env var is auto-set — log only to stdout there.
# Locally, also write to a file for easier debugging.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_handlers: list = [logging.StreamHandler(sys.stdout)]
if not os.getenv("RENDER"):
    _handlers.append(logging.FileHandler("data/bot.log", encoding="utf-8"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=_handlers,
)
log = logging.getLogger("bot")

COGS = [
    "cogs.setup",
    "cogs.gimme",
    "cogs.gimme_unique",
    "cogs.list_unsolved",
    "cogs.gitgud",
    "cogs.gitgud_contest",
    "cogs.duel",
    "cogs.graphs",
    "cogs.contests",
    "cogs.profile",
]


# ── Keep-alive HTTP server (required for Render free tier) ─────────────────

async def health_check(request: web.Request) -> web.Response:
    """Simple endpoint so Render and UptimeRobot can confirm the bot is alive."""
    return web.Response(text="Bot is alive!")


def run_health_server():
    """Run a tiny aiohttp web server in the background on port 8080."""
    async def _start():
        app = web.Application()
        app.router.add_get("/", health_check)
        app.router.add_get("/health", health_check)
        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.getenv("PORT", 8080))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        log.info("Health-check server running on port %d", port)
        # Run forever alongside the bot
        await asyncio.Event().wait()

    asyncio.run(_start())


class CFBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix="!cf_",  # users interact only through slash commands
            intents=intents,
            help_command=None,
        )

        self.cf: CodeforcesClient = CodeforcesClient(
            api_key=config.CF_API_KEY,
            api_secret=config.CF_API_SECRET,
            cache_ttl=config.PROBLEM_CACHE_TTL,
        )
        self.db = None  # assigned in setup_hook

    async def setup_hook(self) -> None:
        """Runs once before the bot connects to Discord's gateway."""
        await self.cf.start()
        log.info("Codeforces API client started")

        os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
        self.db = await get_db(config.DB_PATH)
        await init_db(self.db)
        log.info("Database ready at %s", config.DB_PATH)

        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info("Loaded cog: %s", cog)
            except Exception as exc:
                log.error("Failed to load cog %s: %s", cog, exc, exc_info=True)

        # Guild-scoped sync is instant; global sync takes up to 1 hour.
        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d slash commands to guild %d", len(synced), config.GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d slash commands globally (may take up to 1 hour)", len(synced))

    async def on_ready(self):
        log.info("[OK] Logged in as %s (ID: %s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Codeforces problems | /setup",
            )
        )

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ):
        """Global error handler — catches unhandled slash command errors."""
        msg = str(error)
        if isinstance(error, discord.app_commands.CommandOnCooldown):
            msg = f"Command on cooldown. Try again in {error.retry_after:.1f}s."
        elif isinstance(error, discord.app_commands.MissingPermissions):
            msg = "You don't have permission to use this command."
        elif isinstance(error, discord.app_commands.BotMissingPermissions):
            msg = f"I'm missing permissions: {', '.join(error.missing_permissions)}"

        embed = discord.Embed(title="❌ Error", description=msg, color=config.COLOUR_ERROR)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            pass

        log.error("App command error in /%s: %s", interaction.command and interaction.command.name, error)

    async def close(self):
        await self.cf.close()
        if self.db:
            await self.db.close()
        await super().close()
        log.info("Bot shut down cleanly")


async def main():
    if not config.BOT_TOKEN:
        log.critical("BOT_TOKEN is not set. Copy .env.example -> .env and fill in your token.")
        sys.exit(1)

    bot = CFBot()
    async with bot:
        await bot.start(config.BOT_TOKEN)


if __name__ == "__main__":
    # Start the health-check HTTP server in a background thread so it doesn't
    # block the bot's asyncio event loop.
    health_thread = Thread(target=run_health_server, daemon=True)
    health_thread.start()

    asyncio.run(main())
