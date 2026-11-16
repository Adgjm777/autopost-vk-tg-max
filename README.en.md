# Media autoposting: VK + Telegram + MAX

The script takes a random file from the `media` folder, publishes it to a VK community,
a Telegram channel and MAX, and deletes the file after a successful post. If the folder is
empty, the script just waits for new files and publishes nothing.

It is meant for regular scheduled posting of photos and short videos.

---

## Features

- Publishes photos and videos to a VK community, as the community itself.
- Publishes to a Telegram channel and to MAX.
- Scheduled VK posts: create a post for later without publishing it now.
- Pauses between posts so it does not look like spam.
- Writes logs to `autopost.log`.

---

## Requirements

- Python 3.9 or newer.
- The `requests` library, one command to install.
- No ffmpeg needed, VK processes video on its side.

---

## Install

1. Download the folder with the script, or `git clone` it.
2. Install the dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in the values, see below.
4. Create a `media` folder and put photos or videos in it (`.jpg`, `.png`, `.mp4` and so on).
5. Run:

```bash
python autopost.py
```

---

## Getting the tokens

### 1) VK community token (`VK_TOKEN`)

1. Open your community, then Management, then API usage.
2. Click create key.
3. Tick the scopes: **manage, wall, photos, video, messages**.
4. Confirm with the code sent to your phone.
5. Copy the key into `.env` on the `VK_TOKEN=` line.

Use the community key: it uploads photos and posts to the wall.

### 2) User token (`VK_USER_TOKEN`), video only

VK does not let a community upload video with a community key, so video needs a token of
an administrator user with the `video` scope.

If you post photos only, leave the field empty.

### 3) Telegram

1. Message @BotFather, send `/newbot`, get a token like `123456789:AA...`.
2. Add the bot as an administrator of the channel with the right to post messages.
3. In `.env`: `TELEGRAM_BOT_TOKEN=...` and `TELEGRAM_CHANNEL=@channel_name`.

### 4) MAX

Token and channel id come from the MAX dashboard. If you do not need MAX, leave the fields
empty and posting to MAX switches itself off.

---

## Settings (.env)

| Variable | Meaning |
|---|---|
| `VK_GROUP_ID` | numeric community id, without the minus sign |
| `VK_TOKEN` | community key |
| `VK_USER_TOKEN` | user token for video, optional |
| `TELEGRAM_BOT_TOKEN` | bot token |
| `TELEGRAM_CHANNEL` | `@channel_name` |
| `MAX_TOKEN` | MAX token, optional |
| `MAX_CHANNEL_ID` | MAX channel id, optional |

If a token is empty, that platform is skipped.

---

## Running

```bash
python autopost.py                            # publish one random file
python autopost.py --count 3                  # publish three files with pauses
python autopost.py --scheduled --delay 180    # scheduled VK post in about three hours
```

---

## Scheduled runs

**Windows:** Task Scheduler, create a task, trigger "every hour", action "start a program":
`python` with arguments `C:\path\autopost.py`.

**Linux:** `crontab -e`, for example every hour:

```
0 * * * * cd /path/to/autopost && /usr/bin/python3 autopost.py >> cron.log 2>&1
```

---

## Common VK errors

| Code | Meaning | What to do |
|---|---|---|
| 5 | token is wrong or expired | reissue the token |
| 27 | method is not available for a community key | video needs `VK_USER_TOKEN` |
| 1051 | not enough token scopes | add scopes when creating the key |
| 6, 10 | temporary VK error | the script retries by itself |

---

## Security

- Never publish `.env` or `tokens.txt`, they are already in `.gitignore`.
- If a token leaks, reissue it immediately, delete the key in the settings.
- The script can be handed to any AI assistant: with this README it will install and configure everything itself.