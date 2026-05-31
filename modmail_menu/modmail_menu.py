# modmail_menu/modmail_menu.py

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


def parse_color(value: str) -> discord.Color:
    value = value.strip().lstrip("#")
    try:
        return discord.Color(int(value, 16))
    except ValueError:
        return None


def ok(description: str, bot=None) -> discord.Embed:
    """Green success embed."""
    return discord.Embed(
        description=f"✅ {description}",
        color=bot.main_color if bot else discord.Color.blurple(),
    )


def err(description: str) -> discord.Embed:
    """Red error embed."""
    return discord.Embed(
        description=f"❌ {description}",
        color=discord.Color.red(),
    )


def info(description: str, title: str = None, bot=None) -> discord.Embed:
    """Neutral info embed for wizard steps."""
    return discord.Embed(
        title=title,
        description=description,
        color=bot.main_color if bot else discord.Color.blurple(),
    )


# ── Modal ─────────────────────────────────────────────────────────────────────

class PanelEditModal(discord.ui.Modal, title="Edit Panel"):
    panel_title = discord.ui.TextInput(
        label="Title",
        placeholder="e.g. Contact Support",
        max_length=256,
        required=True,
    )
    description = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=True,
    )
    embed_color = discord.ui.TextInput(
        label="Embed Color (hex)",
        placeholder="e.g. #5865F2  —  leave blank for bot default",
        max_length=7,
        required=False,
    )
    placeholder_text = discord.ui.TextInput(
        label="Dropdown Placeholder Text",
        placeholder="e.g. Select a topic...",
        max_length=150,
        required=False,
    )

    def __init__(self, current: dict):
        super().__init__()
        self.panel_title.default = current.get("title", "")
        self.description.default = current.get("description", "")
        self.embed_color.default = current.get("embed_color", "")
        self.placeholder_text.default = current.get("placeholder_text", "Select a topic...")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self._values = {
            "title": self.panel_title.value,
            "description": self.description.value,
            "embed_color": self.embed_color.value.strip() or None,
            "placeholder_text": self.placeholder_text.value.strip() or "Select a topic...",
        }
        if self._values["embed_color"] and parse_color(self._values["embed_color"]) is None:
            await interaction.followup.send(
                embed=err("Invalid hex color — changes not saved. Use format `#rrggbb`."),
                ephemeral=True,
            )
            self._values = None
            return
        await interaction.followup.send(
            embed=ok("Panel settings updated."),
            ephemeral=True,
        )


# ── Dropdown ──────────────────────────────────────────────────────────────────

class ContactSelect(discord.ui.Select):
    def __init__(self, options_config: list, placeholder: str = "Select a topic..."):
        options = [
            discord.SelectOption(
                label=opt["label"],
                description=opt.get("description") or "",
                emoji=opt.get("emoji") or None,
                value=str(i),
            )
            for i, opt in enumerate(options_config)
        ]
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="modmail_menu:select",
        )
        self.options_config = options_config

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        chosen = self.options_config[int(self.values[0])]
        bot = interaction.client
        user = interaction.user

        guild = bot.guild
        member = guild.get_member(user.id)
        if member is None:
            try:
                member = await guild.fetch_member(user.id)
            except discord.NotFound:
                return await interaction.followup.send(
                    embed=err("Could not find you as a member of this server."),
                    ephemeral=True,
                )

        category = None
        category_id = chosen.get("category_id")
        if category_id:
            category = discord.utils.get(
                bot.modmail_guild.categories, id=int(category_id)
            )

        thread = await bot.threads.find(recipient=member)
        if thread is None:
            thread = await bot.threads.create(
                member,
                creator=member,
                category=category,
            )

        await thread.wait_until_ready()

        if thread.channel:
            label = chosen["label"]
            note = chosen.get("opening_message") or f"User selected topic: **{label}**"
            await thread.channel.send(
                embed=discord.Embed(
                    description=f"📋 {note}",
                    color=bot.main_color,
                ).set_footer(text=f"Selected via panel: {label}")
            )

        await interaction.followup.send(
            embed=discord.Embed(
                description=(
                    f"Your thread has been opened under **{chosen['label']}**.\n"
                    f"Please check your DMs from this bot."
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )


class ContactView(discord.ui.View):
    def __init__(self, options_config: list, placeholder: str = "Select a topic..."):
        super().__init__(timeout=None)
        self.add_item(ContactSelect(options_config, placeholder))


# ── Cog ───────────────────────────────────────────────────────────────────────

class ModmailMenu(commands.Cog):
    """Post a channel panel with a dropdown to open Modmail threads."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        self._views_added = False

    @commands.Cog.listener()
    async def on_plugins_ready(self):
        if not self._views_added:
            config = await self.db.find_one({"_id": "config"})
            if config and config.get("options"):
                placeholder = config.get("placeholder_text", "Select a topic...")
                self.bot.add_view(ContactView(config["options"], placeholder))
            self._views_added = True

    # ── Helper ────────────────────────────────────────────────────────────────

    async def _get_config(self, ctx) -> dict | None:
        """Fetch config and send an error embed if missing."""
        config = await self.db.find_one({"_id": "config"})
        if not config:
            await ctx.send(embed=err("No config found. Run `.mmenu setup` first."))
            return None
        return config

    # ── Commands ──────────────────────────────────────────────────────────────

    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    @commands.group(name="mmenu", invoke_without_command=True)
    async def mmenu(self, ctx):
        """Manage the Modmail contact panel."""
        await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    @mmenu.command(name="setup")
    async def mmenu_setup(self, ctx):
        """Interactive wizard to configure the dropdown panel."""

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        def step(n: int, total: int, prompt: str) -> discord.Embed:
            return info(prompt, title=f"Panel Setup — Step {n}/{total}", bot=self.bot)

        total = 5
        try:
            await ctx.send(embed=step(1, total, "What should the embed **title** be?"))
            title = (await self.bot.wait_for("message", check=check, timeout=120)).content

            await ctx.send(embed=step(2, total, "What should the embed **description** be?"))
            description = (await self.bot.wait_for("message", check=check, timeout=120)).content

            await ctx.send(embed=step(
                3, total,
                "Embed color as a hex code (e.g. `#5865F2`), or `skip` for bot default:"
            ))
            color_raw = (await self.bot.wait_for("message", check=check, timeout=120)).content
            embed_color = None if color_raw.lower() == "skip" else color_raw.strip()
            if embed_color and parse_color(embed_color) is None:
                return await ctx.send(embed=err("Invalid hex color. Run `.mmenu setup` again."))

            await ctx.send(embed=step(
                4, total,
                "Dropdown placeholder text (shown before a user selects), or `skip` for default:"
            ))
            ph_raw = (await self.bot.wait_for("message", check=check, timeout=120)).content
            placeholder_text = "Select a topic..." if ph_raw.lower() == "skip" else ph_raw

            await ctx.send(embed=step(5, total, "How many dropdown options do you want? (1–25)"))
            count_msg = await self.bot.wait_for(
                "message",
                check=lambda m: check(m) and m.content.isdigit() and 1 <= int(m.content) <= 25,
                timeout=60,
            )
            count = int(count_msg.content)

            options = []
            for i in range(count):
                await ctx.send(embed=info(
                    f"**Label** (shown in dropdown — max 100 chars):",
                    title=f"Option {i+1}/{count}",
                    bot=self.bot,
                ))
                label = (await self.bot.wait_for("message", check=check, timeout=120)).content[:100]

                await ctx.send(embed=info("Short **description** (or `skip`):", bot=self.bot))
                desc_raw = (await self.bot.wait_for("message", check=check, timeout=120)).content
                desc = None if desc_raw.lower() == "skip" else desc_raw[:100]

                await ctx.send(embed=info("**Emoji** (or `skip`):", bot=self.bot))
                emoji_raw = (await self.bot.wait_for("message", check=check, timeout=120)).content
                emoji = None if emoji_raw.lower() == "skip" else emoji_raw

                await ctx.send(embed=info(
                    "**Note** to post in the mod channel when this option is chosen (or `skip` for default):",
                    bot=self.bot,
                ))
                msg_raw = (await self.bot.wait_for("message", check=check, timeout=120)).content
                opening_message = None if msg_raw.lower() == "skip" else msg_raw

                await ctx.send(embed=info(
                    "**Category ID** to route this option to (or `skip` for default category):",
                    bot=self.bot,
                ))
                cat_raw = (await self.bot.wait_for("message", check=check, timeout=120)).content
                category_id = None if cat_raw.lower() == "skip" else cat_raw.strip()

                options.append({
                    "label": label,
                    "description": desc,
                    "emoji": emoji,
                    "opening_message": opening_message,
                    "category_id": category_id,
                })

            await self.db.find_one_and_update(
                {"_id": "config"},
                {"$set": {
                    "title": title,
                    "description": description,
                    "embed_color": embed_color,
                    "placeholder_text": placeholder_text,
                    "options": options,
                }},
                upsert=True,
            )
            await ctx.send(embed=ok(
                "Config saved! Run `.mmenu post #channel` to post the panel.",
                bot=self.bot,
            ))

        except TimeoutError:
            await ctx.send(embed=err("Setup timed out. Run `.mmenu setup` to try again."))

    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    @mmenu.command(name="edit")
    async def mmenu_edit(self, ctx):
        """Edit the panel title, description, color, and placeholder via a modal."""
        config = await self._get_config(ctx)
        if config is None:
            return

        class LaunchModal(discord.ui.View):
            def __init__(self_inner):
                super().__init__(timeout=60)

            @discord.ui.button(label="Open Editor", style=discord.ButtonStyle.primary)
            async def open_modal(self_inner, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user != ctx.author:
                    return await interaction.response.send_message(
                        embed=err("Only the person who ran this command can use this."),
                        ephemeral=True,
                    )
                modal = PanelEditModal(current=config)
                await interaction.response.send_modal(modal)
                await modal.wait()

                if not hasattr(modal, "_values") or modal._values is None:
                    return

                await self.db.find_one_and_update(
                    {"_id": "config"},
                    {"$set": modal._values},
                    upsert=True,
                )
                self_inner.stop()

        await ctx.send(
            embed=info(
                "Click below to edit the panel title, description, color, and placeholder text.\n"
                "To edit individual options, run `.mmenu setup` to reconfigure from scratch.",
                bot=self.bot,
            ),
            view=LaunchModal(),
        )

    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    @mmenu.command(name="post")
    async def mmenu_post(self, ctx, channel: discord.TextChannel):
        """Post the contact panel into the specified channel."""
        config = await self._get_config(ctx)
        if config is None:
            return

        raw_color = config.get("embed_color")
        color = parse_color(raw_color) if raw_color else None
        if color is None:
            color = self.bot.main_color

        placeholder = config.get("placeholder_text", "Select a topic...")

        embed = discord.Embed(
            title=config["title"],
            description=config["description"],
            color=color,
        )
        view = ContactView(config["options"], placeholder)
        msg = await channel.send(embed=embed, view=view)

        await self.db.find_one_and_update(
            {"_id": "config"},
            {"$set": {"panel_message_id": msg.id, "panel_channel_id": channel.id}},
            upsert=True,
        )
        self.bot.add_view(view, message_id=msg.id)
        await ctx.send(embed=ok(f"Panel posted in {channel.mention}.", bot=self.bot))

    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    @mmenu.command(name="clear")
    async def mmenu_clear(self, ctx):
        """Delete the panel message and clear the config."""
        config = await self.db.find_one({"_id": "config"})
        if config:
            ch = self.bot.get_channel(config.get("panel_channel_id", 0))
            if ch:
                try:
                    msg = await ch.fetch_message(config.get("panel_message_id", 0))
                    await msg.delete()
                except discord.NotFound:
                    pass
            await self.db.find_one_and_delete({"_id": "config"})
        await ctx.send(embed=ok("Panel cleared.", bot=self.bot))


async def setup(bot):
    await bot.add_cog(ModmailMenu(bot))
