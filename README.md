# PATRA Server Monitor

Small monitor service for the PATRA 5-pod deployment.

It continuously checks:

- `patra`
- `patra-dev`
- `patrabackend`
- `patradb`
- `patradbeaver`

and sends Telegram alerts to all subscribed admins when a service goes down, returns an abnormal response, times out, or later recovers.

## Features

- multi-admin Telegram subscription
- optional email notifications per subscriber
- persistent subscriber storage in SQLite
- HTTP, TCP, and TLS health checks
- dynamic target management via Telegram bot commands
- change-based alerting with recovery notices
- manual check endpoint
- deployable as a Tapis Pod Docker image

## Telegram Commands

- `/start`
  - automatically enables notifications for the current chat
  - replies with the available command list
- `/status`
  - actively runs one fresh health-check pass across all five PATRA pods
  - returns the current full report
- `/services`
  - shows the monitored pod list and the latest known status for each one
- `/events`
  - shows the most recent abnormal monitor events
- `/targets`
  - shows the current monitored target list
- `/target_http name https://service`
  - adds or updates a normal HTTP target
- `/target_http_insecure name https://service`
  - adds or updates an HTTP target without TLS verification
- `/target_http_auth name https://service`
  - adds or updates an auth-protected HTTP target that may return `302`, `401`, or `403`
- `/target_tcp name host port`
  - adds or updates a raw TCP target
- `/target_tls name host port`
  - adds or updates a TLS handshake target
- `/target_remove name`
  - removes a target from the monitored list
- `/notification_on`
  - enables notifications for the current chat
- `/notification_off`
  - disables notifications for the current chat
- `/email your.name@example.org`
  - saves an email and enables email alerts for this chat
- `/email_on`
  - re-enables email alerts for the saved email
- `/email_off`
  - disables email alerts
- `/email_status`
  - shows the current email alert setting
- `/subscribers`
  - shows how many admins are currently subscribed
- `/help`
  - prints the command list

## Required Environment Variables

- `TELEGRAM_BOT_TOKEN`

## Recommended Environment Variables

- `MONITOR_DB_PATH=/data/patra-monitor.db`
- `MONITOR_INTERVAL_SECONDS=30`
- `MONITOR_REQUEST_TIMEOUT_SECONDS=10`
- `MONITOR_FAILURE_THRESHOLD=2`
- `MONITOR_RECOVERY_THRESHOLD=1`
- `MONITOR_REMINDER_INTERVAL_MINUTES=30`
- `MONITOR_TARGETS_JSON=...`
- `SMTP_HOST=smtp.example.org`
- `SMTP_PORT=587`
- `SMTP_USERNAME=your-smtp-user`
- `SMTP_PASSWORD=your-smtp-password`
- `SMTP_FROM_EMAIL=patra-monitor@example.org`
- `SMTP_STARTTLS=true`
- `SMTP_SSL=false`

## Local Run

```powershell
pip install -r requirements.txt
$env:TELEGRAM_BOT_TOKEN="your-bot-token"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

## Docker

```powershell
docker build -t plalelab/patra-server-monitor:latest .
docker run -p 8080:8080 `
  -e TELEGRAM_BOT_TOKEN=your-bot-token `
  -e MONITOR_DB_PATH=/data/patra-monitor.db `
  plalelab/patra-server-monitor:latest
```

## Pod Deploy

Use [`pod_config.json`](./pod_config.json) as the starting Tapis Pod payload.

This monitor is intended to be the sixth PATRA pod alongside:

- `patra`
- `patra-dev`
- `patrabackend`
- `patradb`
- `patradbeaver`
