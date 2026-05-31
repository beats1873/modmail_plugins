# modmail_menu/modmail_menu.py

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


class ContactSelect(discord.ui.Select):
    def __init__(self, options_config: list):
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
            placeholder="Select a topic...",
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

        # Check if user already has an open thread
        thread = bot.threads.find(recipient=user)
        if thread is not None:
            return await interaction.followup.send(
                "You already have an open thread. Please continue there.",
                ephemeral=True,
            )

        # Resolve category if one is configured for this option
        category = None
        category_id = chosen.get("category_id")
        if category_id:
            category = discord.utils.get(
                bot.modmail_guild.categories, id=int(category_id)
            )

        # Create the thread — mirrors how ?contact works internally
        guild = bot.guild  # the main (non-modmail) guild
        member = guild.get_member(user.id)
        if member is None:
            try:
                member = await guild.fetch_member(user.id)
            except discord.NotFound:
                return await interaction.followup.send(
                    "Could not find you as a member of this server.",
                    ephemeral=True,
                )

        # build a minimal fake message so thread.setup() has something to log
        # (same pattern used by the internal contact command)
        thread = await bot.threads.find_or_create(member)
        await thread.wait_until_ready()

        # Post the topic note into the mod-side channel
        if thread.channel:
            label = chosen["label"]
            note = chosen.get("opening_message") or f"User selected topic: **{label}**"
            embed = discord.Embed(
                description=f"📋 {note}",
                color=bot.main_color,
            )
            embed.set_footer(text=f"Selected via panel: {label}")
            await thread.channel.send(embed=embed)

        await interaction.followup.send(
            f"✅ Your thread has been created under **{chosen['label']}**. "
            f"Please check your DMs from this bot.",
            ephemeral=True,
        )


class ContactView(discord.ui.View):
    def __init__(self, options_config: list):
        super().__init__(timeout=None)
        self.add_item(ContactSelect(options_config))


class ModmailMenu(commands.Cog):
    """Post a channel panel with a dropdown to open Modmail threads."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        self._views_added = False

    @commands.Cog.listener()
    async def on_plugins_ready(self):
        """Re-register persistent views after bot restart."""
        if not self._views_added:
            config = await self.db.find_one({"_id": "config"})
            if config and config.get("options"):
                self.bot.add_view(ContactView(config["options"]))
            self._views_added = True

    # ── Commands ──────────────────────────────────────────────────────────────

    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    @commands.group(name="mmenu", invoke_without_command=True)
    async def mmenu(self, ctx):
        """Manage the Modmail contact panel. Subcommands: setup, post, clear."""
        await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    @mmenu.command(name="setup")
    async def mmenu_setup(self, ctx):
        """Interactive wizard to configure the dropdown panel."""

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            await ctx.send("**Panel Setup — Step 1**\nWhat should the embed **title** be?")
            title = (await self.bot.wait_for("message", check=check, timeout=120)).content

            await ctx.send("**Step 2**\nWhat should the embed **description** be?")
            description = (await self.bot.wait_for("message", check=check, timeout=120)).content

            await ctx.send("**Step 3**\nHow many dropdown options do you want? (1–25)")
            count_msg = await self.bot.wait_for(
                "message",
                check=lambda m: check(m) and m.content.isdigit() and 1 <= int(m.content) <= 25,
                timeout=60,
            )
            count = int(count_msg.content)

            options = []
            for i in range(count):
                await ctx.send(
                    f"**Option {i+1}/{count}**\n"
                    f"Label (shown in dropdown — max 100 chars):"
                )
                label = (await self.bot.wait_for("message", check=check, timeout=120)).content[:100]

                await ctx.send(f"Short description for option {i+1} (or `skip`):")
                desc_raw = (await self.bot.wait_for("message", check=check, timeout=120)).content
                desc = None if desc_raw.lower() == "skip" else desc_raw[:100]

                await ctx.send(f"Emoji for option {i+1} (or `skip`):")
                emoji_raw = (await self.bot.wait_for("message", check=check, timeout=120)).content
                emoji = None if emoji_raw.lower() == "skip" else emoji_raw

                await ctx.send(
                    f"Note to post in the mod channel when this option is chosen (or `skip` for default):"
                )
                msg_raw = (await self.bot.wait_for("message", check=check, timeout=120)).content
                opening_message = None if msg_raw.lower() == "skip" else msg_raw

                await ctx.send(
                    f"Category ID to route this option to (or `skip` to use the default category):"
                )
                cat_raw = (await self.bot.wait_for("message", check=check, timeout=120)).content
                category_id = None if cat_raw.lower() == "skip" else cat_raw.strip()

                options.append({
                    "label": label,
                    "description": desc,
                    "emoji": emoji,
                    "opening_message": opening_message,
                    "category_id": category_id,
                })

            config = {"title": title, "description": description, "options": options}
            await self.db.find_one_and_update(
                {"_id": "config"}, {"$set": config}, upsert=True
            )
            await ctx.send(
                "✅ Config saved! Run `.mmenu post #channel` to post the panel."
            )

        except TimeoutError:
            await ctx.send("⏰ Setup timed out. Run `.mmenu setup` to try again.")

    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    @mmenu.command(name="post")
    async def mmenu_post(self, ctx, channel: discord.TextChannel):
        """Post the contact panel into the specified channel."""
        config = await self.db.find_one({"_id": "config"})
        if not config or not config.get("options"):
            return await ctx.send("❌ No config found. Run `.mmenu setup` first.")

        embed = discord.Embed(
            title=config["title"],
            description=config["description"],
            color=self.bot.main_color,
        )
        view = ContactView(config["options"])
        msg = await channel.send(embed=embed, view=view)

        # Persist message/channel IDs for view re-registration on restart
        await self.db.find_one_and_update(
            {"_id": "config"},
            {"$set": {"panel_message_id": msg.id, "panel_channel_id": channel.id}},
            upsert=True,
        )
        self.bot.add_view(view, message_id=msg.id)

        await ctx.send(f"✅ Panel posted in {channel.mention}.")

    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    @mmenu.command(name="clear")
    async def mmenu_clear(self, ctx):
        """Delete the panel message and clear the config."""
        config = await self.db.find_one({"_id": "config"})
        if config:
            channel_id = config.get("panel_channel_id")
            message_id = config.get("panel_message_id")
            if channel_id and message_id:
                ch = self.bot.get_channel(channel_id)
                if ch:
                    try:
                        msg = await ch.fetch_message(message_id)
                        await msg.delete()
                    except discord.NotFound:
                        pass
            await self.db.find_one_and_delete({"_id": "config"})
        await ctx.send("✅ Panel cleared.")


async def setup(bot):
    await bot.add_cog(ModmailMenu(bot))
