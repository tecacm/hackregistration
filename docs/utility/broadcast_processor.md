# Background email broadcasts: processor setup

This app uses an outbox queue (Broadcast + BroadcastRecipient) and a background processor to send segmented emails reliably without tying up web requests.

Below are options to run the processor continuously in production.

## One-off manual run

Run from the project root (adjust flags as needed):

```bash
/opt/hackassistant/env/bin/python3 /opt/hackassistant/manage.py process_broadcasts \
  --batch-size 100 \
  --delay-ms 500 \
  --max-retries 2 \
  --max-broadcasts 5
```

## Recommended: systemd service + timer

This starts the processor on a schedule and prevents overlapping runs (systemd won’t start the service again while it’s still active).

Create the service unit at `/etc/systemd/system/hackregistration-broadcasts.service`:

```
[Unit]
Description=Hackregistration email broadcast processor
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/opt/hackassistant
User=www-data
Group=www-data
# Adjust flags to your ESP/rate limits
ExecStart=/opt/hackassistant/env/bin/python3 /opt/hackassistant/manage.py process_broadcasts \
  --batch-size 100 --delay-ms 500 --max-retries 2 --max-broadcasts 5
# Optional: limit runaway jobs
RuntimeMaxSec=600

[Install]
WantedBy=multi-user.target
```

Create the timer at `/etc/systemd/system/hackregistration-broadcasts.timer`:

```
[Unit]
Description=Run hackregistration broadcast processor periodically

[Timer]
# Run 30s after the last completion (prevents overlap)
OnUnitActiveSec=30s
# Ensure missed runs execute after downtime
Persistent=true
Unit=hackregistration-broadcasts.service

[Install]
WantedBy=timers.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hackregistration-broadcasts.timer
# Optional: run immediately
sudo systemctl start hackregistration-broadcasts.service
```

Status and logs:

```bash
systemctl status hackregistration-broadcasts.timer
systemctl status hackregistration-broadcasts.service
journalctl -u hackregistration-broadcasts.service -n 200 -f
```

Notes:
- Overlap: `Type=oneshot` keeps the unit active until it finishes; the timer won’t start another instance while it’s active.
- Tuning: increase `--batch-size` or reduce `--delay-ms` based on ESP limits and worker capacity.
- Security: set `User`/`Group` to the account that owns the app files and can send email (e.g., `www-data` or a dedicated user).

## Alternative: cron + flock

If you prefer cron, run every minute with a file lock to avoid overlap. Add to root’s crontab (`sudo crontab -e`):

```
* * * * * flock -n /var/lock/hackregistration-broadcasts.lock \
  /opt/hackassistant/env/bin/python3 /opt/hackassistant/manage.py process_broadcasts \
  --batch-size 100 --delay-ms 500 --max-retries 2 --max-broadcasts 5 \
  >> /var/log/hackregistration-broadcasts.log 2>&1
```

Tip: use `logrotate` or rely on journald when using systemd.

## Where to monitor

- Admin → Broadcasts: see queued/running/completed status, totals, and accepted counts.
- Admin → Broadcast recipients: per-recipient status and attempts.
- Application logs: each successful send creates an `ApplicationLog` entry on the recipient’s application.
