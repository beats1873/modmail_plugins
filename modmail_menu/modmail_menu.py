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
    """Neutral info embed."""
    return discord.Embed(
        title=title,
        description=description,
        color=bot.main_color if bot else discord.Color.blurple(),
    )


# ── Block check helper ────────────────────────────────────────────────────────

async def is_blocked(bot, user_id: int) -> bool:
    """
    Returns True if the user is blocked in Modmail's config.
    Handles both async and non-async bot.config.get gracefully.
    """
    try:
        blocked = bot.config.get("blocked")
        if hasattr(blocked, "__await__"):
            blocked = await blocked
    except Exception:
        return False
    return bool(blocked and str(user_id) in blocked)


# ── Modals ────────────────────────────────────────────────────────────────────

class PanelSettingsModal(discord.ui.Modal, title="Panel Settings"):
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

    def __init__(self, current: dict = None):
        super().__init__()
        if current:
            self.panel_title.default = current.get("title", "")
            self.description.default = current.get("description", "")
            self.embed_color.default = current.get("embed_color", "")
            self.placeholder_text.default = current.get("placeholder_text", "Select a topic...")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        color_raw = self.embed_color.value.strip() or None
        if color_raw and parse_color(color_raw) is None:
            await interaction.followup.send(
                embed=err("Invalid hex color — use format `#rrggbb`."),
                ephemeral=True,
            )
            self._values = None
            return
        self._values = {
            "title": self.panel_title.value,
            "description": self.description.value,
            "embed_color": color_raw,
            "placeholder_text": self.placeholder_text.value.strip() or "Select a topic...",
        }


class OptionModal(discord.ui.Modal, title="Add Option"):
    label_input = discord.ui.TextInput(
        label="Label",
        placeholder="e.g. Bug Report",
        max_length=100,
        required=True,
    )
    description_input = discord.ui.TextInput(
        label="Description",
        placeholder="Short subtitle shown under the label (optional)",
        max_length=100,
        required=False,
    )
    emoji_input = discord.ui.TextInput(
        label="Emoji",
        placeholder="e.g. 🐛  —  leave blank for none",
        max_length=64,
        required=False,
    )
    opening_message_input = discord.ui.TextInput(
        label="Opening Message (mod channel note)",
        placeholder="e.g. User is reporting a bug. Leave blank for default.",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False,
    )
    category_id_input = discord.ui.TextInput(
        label="Category ID",
        placeholder="Route to a specific category ID, or leave blank for default",
        max_length=20,
        required=False,
    )

    def __init__(self, index: int, current: dict = None):
        super().__init__(title=f"Option {index + 1}")
        self._index = index
        if current:
            self.label_input.default = current.get("label", "")
            self.description_input.default = current.get("description", "") or ""
            self.emoji_input.default = current.get("emoji", "") or ""
            self.opening_message_input.default = current.get("opening_message", "") or ""
            self.category_id_input.default = current.get("category_id", "") or ""

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self._values = {
            "label": self.label_input.value,
            "description": self.description_input.value.strip() or None,
            "emoji": self.emoji_input.value.strip() or None,
            "opening_message": self.opening_message_input.value.strip() or None,
            "category_id": self.category_id_input.value.strip() or None,
        }


# ── Option count prompt view ──────────────────────────────────────────────────

class OptionCountView(discord.ui.View):
    """Presents buttons 1–10 to pick the number of options."""

    def __init__(self):
        super().__init__(timeout=60)
        self._count = None
        for n in range(1, 11):
            btn = discord.ui.Button(
                label=str(n),
                style=discord.ButtonStyle.secondary,
                custom_id=f"count_{n}",
            )
            btn.callback = self._make_callback(n)
            self.add_item(btn)

    def _make_callback(self, n: int):
        async def callback(interaction: discord.Interaction):
            self._count = n
            await interaction.response.defer()
            self.stop()
        return callback


# ── Dropdown + Submit button ──────────────────────────────────────────────────

async def open_thread(interaction: discord.Interaction, chosen: dict):
    """Shared logic for opening a thread, called from the submit button."""
    bot = interaction.client
    user = interaction.user

    # ── Block check ──────────────────────────────────────────────────────────
    if await is_blocked(bot, user.id):
        return await interaction.followup.send(
            embed=err("You are unable to open a ticket at this time."),
            ephemeral=True,
        )

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
        # Block check on selection so blocked users get instant feedback
        # and can never reach the submit button successfully.
        if await is_blocked(interaction.client, interaction.user.id):
            return await interaction.response.send_message(
                embed=err("You are unable to open a ticket at this time."),
                ephemeral=True,
            )

        # Store selected index on the view for the submit button to read.
        self.view._selected_index = int(self.values[0])
        await interaction.response.defer()


class SubmitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Open Ticket",
            style=discord.ButtonStyle.green,
            custom_id="modmail_menu:submit",
            emoji="🛟",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Block check again on submit as a second line of defense.
        if await is_blocked(interaction.client, interaction.user.id):
            return await interaction.followup.send(
                embed=err("You are unable to open a ticket at this time."),
                ephemeral=True,
            )

        selected_index = getattr(self.view, "_selected_index", None)
        if selected_index is None:
            return await interaction.followup.send(
                embed=err("Please select a topic from the dropdown first."),
                ephemeral=True,
            )

        chosen = self.view.options_config[selected_index]
        await open_thread(interaction, chosen)


class ContactView(discord.ui.View):
    def __init__(self, options_config: list, placeholder: str = "Select a topic..."):
        super().__init__(timeout=None)
        self.options_config = options_config
        self._selected_index = None
        self.add_item(ContactSelect(options_config, placeholder))
        self.add_item(SubmitButton())


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

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_config(self, ctx) -> dict | None:
        config = await self.db.find_one({"_id": "config"})
        if not config:
            await ctx.send(embed=err("No config found. Run `.mmenu setup` first."))
            return None
        return config

    async def _launch_modal(self, ctx, modal: discord.ui.Modal) -> bool:
        """
        Send a button that opens the given modal when clicked.
        Returns True if the modal was submitted, False if it timed out.
        """
        class ModalLauncher(discord.ui.View):
            def __init__(self_inner):
                super().__init__(timeout=120)
                self_inner.submitted = False

            @discord.ui.button(label="Open", style=discord.ButtonStyle.primary)
            async def open_btn(self_inner, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user != ctx.author:
                    return await interaction.response.send_message(
                        embed=err("Only the person who ran this command can use this."),
                        ephemeral=True,
                    )
                await interaction.response.send_modal(modal)
                await modal.wait()
                self_inner.submitted = True
                self_inner.stop()

        launcher = ModalLauncher()
        msg = await ctx.send(view=launcher)
        await launcher.wait()
        await msg.delete()
        return launcher.submitted

    # ── Commands ──────────────────────────────────────────────────────────────

    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    @commands.group(name="mmenu", invoke_without_command=True)
    async def mmenu(self, ctx):
        """Manage the Modmail contact panel."""
        await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    @mmenu.command(name="setup")
    async def mmenu_setup(self, ctx):
        """Configure the panel and options via modals."""

        # ── Step 1: panel settings modal ──────────────────────────────────────
        settings_modal = PanelSettingsModal()
        await ctx.send(embed=info(
            "Click **Open** to set the panel title, description, color, and dropdown placeholder.",
            title="Panel Setup — Step 1 of 2: Panel Settings",
            bot=self.bot,
        ))
        submitted = await self._launch_modal(ctx, settings_modal)

        if not submitted or not hasattr(settings_modal, "_values") or settings_modal._values is None:
            return await ctx.send(embed=err("Setup cancelled or timed out."))

        panel_settings = settings_modal._values

        # ── Step 2: how many options? ─────────────────────────────────────────
        await ctx.send(embed=info(
            "How many dropdown options do you want? Select below (1–10).\n"
            "If you need more than 10, run `.mmenu setup` again after — options are additive.",
            title="Panel Setup — Step 2 of 2: Options",
            bot=self.bot,
        ))
        count_view = OptionCountView()
        count_msg = await ctx.send(view=count_view)
        await count_view.wait()
        await count_msg.delete()

        count = count_view._count
        if count is None:
            return await ctx.send(embed=err("Setup timed out. Run `.mmenu setup` again."))

        # ── Step 3: one modal per option ──────────────────────────────────────
        options = []
        for i in range(count):
            option_modal = OptionModal(index=i)
            await ctx.send(embed=info(
                f"Click **Open** to configure option {i + 1} of {count}.",
                title=f"Option {i + 1}/{count}",
                bot=self.bot,
            ))
            submitted = await self._launch_modal(ctx, option_modal)

            if not submitted or not hasattr(option_modal, "_values"):
                return await ctx.send(embed=err(f"Setup cancelled at option {i + 1}."))

            options.append(option_modal._values)

        # ── Save ──────────────────────────────────────────────────────────────
        await self.db.find_one_and_update(
            {"_id": "config"},
            {"$set": {**panel_settings, "options": options}},
            upsert=True,
        )
        await ctx.send(embed=ok(
            f"Setup complete with {count} option(s)! Run `.mmenu post #channel` to post the panel.",
            bot=self.bot,
        ))

    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    @mmenu.command(name="edit")
    async def mmenu_edit(self, ctx):
        """Edit the panel title, description, color, and placeholder via a modal."""
        config = await self._get_config(ctx)
        if config is None:
            return

        settings_modal = PanelSettingsModal(current=config)
        await ctx.send(embed=info(
            "Click **Open** to edit the panel settings.\n"
            "To edit individual options use `.mmenu setup` to reconfigure from scratch.",
            bot=self.bot,
        ))
        submitted = await self._launch_modal(ctx, settings_modal)

        if not submitted or not hasattr(settings_modal, "_values") or settings_modal._values is None:
            return await ctx.send(embed=err("Edit cancelled or timed out."))

        await self.db.find_one_and_update(
            {"_id": "config"},
            {"$set": settings_modal._values},
            upsert=True,
        )
        await ctx.send(embed=ok(
            "Panel settings updated. Run `.mmenu post #channel` to repost with the new settings.",
            bot=self.bot,
        ))

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

    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    @mmenu.command(name="debug")
    async def mmenu_debug(self, ctx):
        """Debug block list."""
        blocked = self.bot.config.get("blocked")
        await ctx.send(f"Type: `{type(blocked)}`\nValue: `{blocked}`")


async def setup(bot):
    await bot.add_cog(ModmailMenu(bot))
