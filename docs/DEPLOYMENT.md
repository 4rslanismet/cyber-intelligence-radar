# Deployment

The radar is a scheduled batch job, not a long-running server (the only
always-on optional piece is the Telegram feedback listener, and it's
optional). Pick whichever scheduling mechanism fits your environment.

## systemd (recommended on Linux)

Templates are provided in `systemd/*.service.example`/`*.timer.example`.
They use a placeholder install path (`/opt/cyber-intelligence-radar`)
and a placeholder service user (`cyber-radar`) — edit both before use:

```bash
sudo useradd --system --home /opt/cyber-intelligence-radar --shell /usr/sbin/nologin cyber-radar
sudo cp -r . /opt/cyber-intelligence-radar
sudo chown -R cyber-radar:cyber-radar /opt/cyber-intelligence-radar

sed 's#/opt/cyber-intelligence-radar#/opt/cyber-intelligence-radar#; s/cyber-radar/cyber-radar/' \
  systemd/cyber-radar.service.example | sudo tee /etc/systemd/system/cyber-radar.service
sudo cp systemd/cyber-radar.timer.example /etc/systemd/system/cyber-radar.timer

sudo systemctl daemon-reload
sudo systemctl enable --now cyber-radar.timer
```

The units are hardened (`NoNewPrivileges`, `PrivateTmp`, `PrivateDevices`,
`ProtectKernelTunables`/`Modules`, `ProtectControlGroups`,
`RestrictSUIDSGID`, `LockPersonality`) — the same baseline used in the
private deployment this project was derived from. `ProtectSystem`/
`ProtectHome`/`ReadWritePaths` are deliberately **not** set — auditing
every write path your specific deployment needs before adding those is
your responsibility (see [SECURITY.md](SECURITY.md)).

If you enable Google Drive with `GDRIVE_SYNC_MODE=queued`, also install
`cyber-radar-drive-sync.service.example`/`.timer.example`.

## cron (simpler, less isolation)

```cron
30 7,19 * * * cd /opt/cyber-intelligence-radar && .venv/bin/cyber-radar run >> /var/log/cyber-radar.log 2>&1
```

## Docker

**Not provided in this release.** A proper container setup needs to
correctly handle: a separate PostgreSQL+pgvector container or an
external DB, volume-mounted `data/` and `.env`, and secret injection
that doesn't end up baked into an image layer. Getting all three right
and actually testing the result was judged out of scope for this
release rather than shipping an unverified Dockerfile that looks
official but wasn't validated end-to-end. If you containerize this
successfully, a contribution is welcome (see `CONTRIBUTING.md`).

## Manual / no scheduler

`cyber-radar run` is always safe to invoke by hand — there's no
required daemon or lock file beyond the rate-limiter's own lock files
under `data/state/`, which are per-external-host and self-cleaning.
