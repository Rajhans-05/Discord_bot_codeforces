# Codeforces Discord Bot

A Discord bot that integrates with the Codeforces API to bring problem recommendations, user profiles, contest tracking, and rating graphs directly to your server.

## Features

| Command | What it does |
|---|---|
| `/setup` | Link your Discord account to your Codeforces handle |
| `/profile` | View your rating, rank, and max rating |
| `/gimme` | Get a problem recommendation by rating and tag (random or latest unattempted) |
| `/gimme_unique` | Get a problem from a unique contest (Global Rounds, company rounds, April Fools) |
| `/listunsolved` | See problems you've attempted but never solved |
| `/gitgud` | Get a challenge problem slightly above your current rating |
| `/duel` | Challenge another user to a timed coding duel |
| `/graph rating` | View your rating history as a graph |
| `/contests` | See upcoming Codeforces contests |

---

## Hosting on Render (Free)

> **Free tier workaround:** Render's free plan only supports Web Services. This bot runs a lightweight HTTP health-check server on port 8080 alongside the bot. You then use [UptimeRobot](https://uptimerobot.com) (free) to ping the `/health` endpoint every 5 minutes, keeping it online 24/7.

> ⚠️ **Database Note:** Render's free filesystem resets on every deploy. Your `/setup` handle links will be lost on each re-deploy unless you pay for a Persistent Disk (~$1/month). For a personal server, this is a minor inconvenience — just run `/setup` again after a deploy.

### Step 1 — Push to GitHub

1. Create a new repository on [github.com](https://github.com).
2. Inside the `HOST_THE_BOT` folder on your PC, open a terminal and run:
   ```
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git push -u origin main
   ```

### Step 2 — Create a Render Web Service

1. Go to [render.com](https://render.com) and sign up / log in (GitHub login is easiest).
2. Click **New +** → **Web Service**.
3. Connect your GitHub account and select the repository you just pushed.
4. Render will auto-detect the `render.yaml` file. Review the settings:
   - **Name:** anything you like
   - **Region:** choose closest to you
   - **Branch:** `main`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
   - **Instance Type:** `Free`
5. Click **Create Web Service**.

### Step 3 — Set Environment Variables

In the Render dashboard for your service, go to **Environment** tab and add:

| Key | Value |
|---|---|
| `BOT_TOKEN` | Your Discord bot token (from [Discord Developer Portal]) |
| `GUILD_ID` | Your Discord server ID  |
| `CF_API_KEY` | *(leave blank — not required)* |
| `CF_API_SECRET` | *(leave blank — not required)* |


### Step 4 — Deploy

Click **Deploy** (or it auto-deploys on push). Wait ~2 minutes. Check the logs — you should see:
```
[OK] Logged in as YourBot#1234 (ID: ...)
```

### Step 5 — Keep Alive with UptimeRobot

Render free services sleep after 15 minutes of inactivity. To prevent this:

1. Go to [uptimerobot.com](https://uptimerobot.com) and create a free account.
2. Click **Add New Monitor**.
3. Select **HTTP(s)** type.
4. Set the URL to your Render service URL: `https://your-service-name.onrender.com/health`
5. Set the interval to **every 5 minutes**.
6. Save. UptimeRobot will now ping your bot every 5 minutes, keeping it awake.

---

## Running Locally

1. Clone the repo and install dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in `BOT_TOKEN` and `GUILD_ID`.
3. Run the bot:
   ```
   python bot.py
   ```

---

## Project Structure

```
├── bot.py              # Entry point (also runs health-check server for Render)
├── config.py           # Loads .env values
├── render.yaml         # Render deployment config
├── requirements.txt    # Python dependencies
├── cogs/               # Slash command modules
├── cf_api/             # Codeforces API wrapper (async, with caching)
├── db/                 # SQLite database manager
└── utils/              # Embed builder, paginator, graph generator
```
