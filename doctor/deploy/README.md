# doctor/deploy — the off-host dead-man checker (auto-review-02w)

The doctor records its own `ops.job_runs` row each run, so "latest
`auto-review-doctor` row age" is a heartbeat. `doctor/deadman-check` is the
**independent** watcher that alarms when that heartbeat goes stale — run it on a
host **other** than the doctor's so it still fires when the doctor's host is fully
down (the case the doctor's in-band self-liveness structurally can't report).

Mechanism lives here; instance values (the DSN, the host) live on the operator's
box only — this repo is public.

## Deploy (workstation / any off-doctor host)

```bash
# 1. the checker
install -m 0755 doctor/deadman-check ~/.local/bin/deadman-check

# 2. instance config — the DSN is NOT in the repo. A password-less URI keeps the
#    credential in ~/.pgpass, not the env file. Needs SELECT on ops.job_runs.
mkdir -p ~/.config/auto-review
cat > ~/.config/auto-review/deadman.env <<'ENV'
DEADMAN_PG_DSN=postgresql://<reader>@<pg-host>:5432/<db>
DEADMAN_MAX_AGE_HOURS=30
ENV
chmod 600 ~/.config/auto-review/deadman.env

# 3. the systemd --user timer
install -m 0644 doctor/deploy/auto-review-deadman.service ~/.config/systemd/user/
install -m 0644 doctor/deploy/auto-review-deadman.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now auto-review-deadman.timer

# 4. verify
systemctl --user start auto-review-deadman.service   # run once now
systemctl --user status auto-review-deadman.service  # should be a clean oneshot exit 0
```

An alarm surfaces three ways: the unit goes **failed** (`systemctl --user
--failed`), the journal records the message (`journalctl --user -u
auto-review-deadman.service`), and `notify-send` fires a desktop notification.

## Residual

The checker is itself unmonitored — a one-line SQL check on a box that is not the
doctor's host is a much smaller thing to trust than the whole doctor (accepted per
`auto-review-02w`). A future hardening (`auto-review-01m`-adjacent) could narrow
its DSN from a shared reader to a dedicated `SELECT ops.job_runs`-only role.
