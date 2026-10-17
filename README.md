# BotPilot Render MVP (PHP + Python)

Private single-admin dashboard for uploading ZIPs containing a PHP or Python bot, then starting/stopping/restarting it and viewing logs.

## Deploy to Render

1. Create a **private GitHub repository** and upload all files from this folder.
2. In Render, choose **New + → Blueprint** and connect the repository. Render reads `render.yaml`.
3. Set `ADMIN_PASSWORD` to a strong unique password in the service environment. Keep `ADMIN_USER=admin` or change it.
4. Deploy. Open the service URL; the browser will show a username/password prompt. Use your configured credentials.
5. Upload a ZIP with `bot.php`, `main.php`, `bot.py`, or `main.py` at the ZIP root. A different `.php` or `.py` file can also be selected automatically.

## Important limitations

- This is an MVP, not a secure multi-tenant hosting platform.
- Uploaded code runs inside the same container as the dashboard. Only upload code you trust. A malicious or compromised bot could access environment variables and affect the panel. Do not upload third-party code you have not reviewed.
- This version supports one entry file per bot. PHP dependencies via Composer and Python dependencies from arbitrary `requirements.txt` are not installed automatically.
- The process monitor attempts crash recovery up to five times, but state is in-process and a redeploy/restart can interrupt bots. A production design should use a separate isolated runner per bot, a durable queue, and a separate database.
- Render Persistent Disk is paid and attached to this service. Keep `DATA_DIR=/var/data` and do not scale this single-disk service to multiple instances.
- Use webhook or polling bots according to the bot's own code. This panel does not automatically configure Telegram webhooks or tokens.
- Do not commit `.env`, Telegram tokens, or secrets to GitHub.
