# Render Deployment Notes

**Required Environment Variables**
- `BOT_TOKEN` — your Telegram bot token.
- `WEBHOOK_URL` — your public base URL (e.g., https://your-service.onrender.com).
- Optional: 
  - `ADMIN_ID` — Telegram user id for admin (default 1262317603).
  - `DATABASE_URL` — Postgres URL if you want SQL storage.

**Service Type**
- Create a **Web Service** (NOT Background Worker).

**Start Command**
- Provided by `Procfile`:
```
web: gunicorn bot:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120
```

**How it works**
- On first boot, app binds to `$PORT` and exposes `/` for health, and `/{BOT_TOKEN}` as the Telegram webhook path.
- The app calls `bot.remove_webhook()` then `bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")` at startup.
- Telegram must be able to reach **`{WEBHOOK_URL}/{BOT_TOKEN}`** over HTTPS with a valid certificate.

**Common gotchas**
- Missing `BOT_TOKEN` or `WEBHOOK_URL` -> the process starts but can't receive updates.
- Wrong service type (Background Worker) -> Render kills it because it doesn't bind to `$PORT`.
- 404 on webhook path -> path must be exactly `/{BOT_TOKEN}`.
- If you don't need Postgres, **do not** set `DATABASE_URL`, or ensure it's a valid URL if set.
