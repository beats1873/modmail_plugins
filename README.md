# modmail-menu

A [Modmail](https://github.com/modmail-dev/Modmail) plugin that posts a persistent embed with a dropdown menu in a public server channel, allowing users to open a Modmail thread by selecting a topic — without needing to DM the bot first.

---

## Features

- Persistent embed panel posted in any channel you choose
- Dropdown menu with up to 25 customisable options
- Each option can route to a different Modmail category
- Each option posts a topic note in the mod-side thread channel
- Custom embed title, description, color, and placeholder text
- Modal-based setup and editing — no long back-and-forth wizard
- All bot responses use embeds
- Persistent across bot restarts

---

## Installation

In your Discord server, run:

```
?plugins add beats1873/modmail_plugins/modmail_menu
```

For local testing:

```
?plugins load @local/modmail_menu
```

> **Note:** The folder and file must use underscores, not hyphens: `modmail_menu/modmail_menu.py`

---

## Setup

### 1. Configure the panel

```
.mmenu setup
```

Opens a modal to set:
- **Title** — the embed title
- **Description** — the embed description
- **Color** — hex color code (e.g. `#5865F2`), leave blank for bot default
- **Placeholder** — the greyed-out text shown in the dropdown before a user selects

After submitting the panel settings, you will be asked how many options you want. A modal will open for each option with fields for:
- **Label** — shown in the dropdown (max 100 chars)
- **Description** — short subtitle shown under the label (max 100 chars)
- **Emoji** — optional emoji shown next to the label
- **Opening Message** — note posted in the mod channel when this option is chosen
- **Category ID** — routes the thread to a specific Modmail category (leave blank for default)

### 2. Post the panel

```
.mmenu post <channelID>
```

Posts the configured embed with the dropdown into the specified channel.

### 3. Done

Users can now click the dropdown to open a thread. They receive an ephemeral confirmation, and the mod-side channel gets a note showing which topic was selected.

---

## Commands

All commands require the `Administrator` permission level.

| Command | Description |
|---|---|
| `.mmenu setup` | Run the full setup flow via modals |
| `.mmenu edit` | Edit panel title, description, color, and placeholder via a modal |
| `.mmenu post <channelID>` | Post the panel embed into a channel |
| `.mmenu clear` | Delete the panel message and wipe the config |

---

## Updating the Plugin

After pushing changes to GitHub:

```
?plugins update beats1873/modmail_plugins/modmail_menu
```

Or remove and re-add:

```
?plugins remove beats1873/modmail_plugins/modmail_menu
?plugins add beats1873/modmail_plugins/modmail_menu
```

---

## Notes

- Discord modals have a 5-field limit, so panel settings and each option use separate modals
- If a user already has an open thread, their selection will post the topic note to the existing thread rather than creating a duplicate
- The panel embed and dropdown persist across bot restarts via discord.py's persistent view system
- Requires Modmail v4 (discord.py v2)
