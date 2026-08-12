#!/bin/bash
# AlphaBrief 30-day observation daily checkpoint (reference copy).
#
# Runtime observation strategy (scheduler holds the DuckDB write lock):
#   - scheduler health: DB file mtime updates every reconcile tick (60s)
#   - freezes/alerts: scan scheduler.err.log for ALERT/ERROR lines
#   - AI state: read the per-day ai_cycle_*.json exports the scheduler
#     writes to ALPHABRIEF_OBSERVATION_DIR (no DB lock conflict)
#
# Deployed copy lives at ~/.alphabrief/daily_check.sh. Schedule it once
# per day (launchd/cron) and keep the report in the observation dir.
set -uo pipefail

HOME_DIR="${HOME:-/Users/jeremyliu}"
AB="${ALPHABRIEF_CLI:-$HOME_DIR/Desktop/Projects/AlphaBrief/.venv/bin/alphabrief}"
OBS_DIR="${ALPHABRIEF_OBSERVATION_DIR:-$HOME_DIR/.alphabrief/reports/paper_observation}"
DATA_DIR="${ALPHABRIEF_SCHEDULER_DATA_DIR:-$HOME_DIR/.alphabrief/data}"
DATE=$(date '+%Y-%m-%d')
mkdir -p "$OBS_DIR"

# DB heartbeat proxy: WAL file mtime within last 180s = scheduler alive and
# reconciling (DuckDB writes go to the .wal first; the main file only changes
# on checkpoint)
DB="$DATA_DIR/alphabrief.db"
WAL="$DB.wal"
if [ -f "$WAL" ]; then
  DB_MTIME=$(stat -f %m "$WAL" 2>/dev/null || echo 0)
else
  DB_MTIME=$(stat -f %m "$DB" 2>/dev/null || echo 0)
fi
NOW=$(date +%s)
DB_AGE=$(( NOW - DB_MTIME ))
ERRLOG="$HOME_DIR/.alphabrief/scheduler.err.log"

# Scan log since last check (persist marker next to the report)
LAST_MARK="$OBS_DIR/.daily_check_last_line"
MARK_LINE=$(cat "$LAST_MARK" 2>/dev/null || echo 0)
TOTAL_LINES=$(wc -l < "$ERRLOG" 2>/dev/null || echo 0)
NEW_ALERTS=""
if [ "$TOTAL_LINES" -gt "$MARK_LINE" ] 2>/dev/null; then
  NEW_ALERTS=$(sed -n "$((MARK_LINE+1)),\$p" "$ERRLOG" 2>/dev/null | grep -E 'ALERT|ERROR' | tail -5)
  echo "$TOTAL_LINES" > "$LAST_MARK"
fi

# AI state: scheduler exports a per-day JSON after each cycle
AI_FILE="$OBS_DIR/ai_cycle_$DATE.json"
if [ -f "$AI_FILE" ]; then
  ai=$(cat "$AI_FILE")
else
  ai='{"exported": false, "note": "no AI cycle exported yet today"}'
fi
ai_hist='{"cycles":[]}'

# Archive raw AI snapshot for the runbook evidence folder
echo "=== $DATE $(date '+%H:%M:%S %Z') ===" >> "$OBS_DIR/daily.log"
echo "$ai" >> "$OBS_DIR/daily.log"

python3 - "$DATE" "$DB_AGE" "$NEW_ALERTS" "$ai" "$ai_hist" "$OBS_DIR" <<'PYEOF'
import json, os, sys
date, db_age, new_alerts, ai, ai_hist, obs_dir = sys.argv[1:7]

def jget(s, *keys, default=None):
    try:
        d = json.loads(s)
        for k in keys:
            d = d.get(k) if isinstance(d, dict) else None
            if d is None:
                return default
        return d
    except Exception:
        return default

cycles = jget(ai_hist, "cycles", default=[])
today_cycles = [c for c in cycles if str(c.get("trading_day", "")) == date] if isinstance(cycles, list) else []
outcomes = {}
for c in today_cycles:
    o = c.get("outcome", "?")
    outcomes[o] = outcomes.get(o, 0) + 1
last_cycle = today_cycles[0] if today_cycles else None

summary = {
    "date": date,
    "scheduler": {
        "db_age_seconds": int(db_age),
        "healthy": int(db_age) <= 180,
        "note": "DB file mtime is the heartbeat proxy (reconcile tick = 60s); CLI queries are locked by design while scheduler runs",
    },
    "new_alert_lines": (new_alerts.strip().split("\n") if new_alerts.strip() else []),
    "ai": {
        "exported": os.path.isfile(os.path.join(obs_dir, "ai_cycle_" + date + ".json")),
        "cycle_id": jget(ai, "cycle_id", default=None),
        "outcome": jget(ai, "outcome", default=None),
        "trading_day": jget(ai, "trading_day", default=None),
        "created_at": jget(ai, "created_at", default=None),
        "plan_count": jget(ai, "plan_count", default=0),
        "executed_count": jget(ai, "executed_count", default=0),
        "attempt_count": jget(ai, "attempt_count", default=0),
        "blocked_count": jget(ai, "blocked_count", default=0),
        "error": jget(ai, "error", default=None),
    },
}
print(json.dumps(summary, ensure_ascii=False))
PYEOF
