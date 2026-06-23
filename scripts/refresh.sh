#!/bin/zsh
# Weekly refresh wrapper. Recomputes the stats block and pushes if it changed.
# Run by hand any time:  zsh scripts/refresh.sh
# Or schedule it via scripts/com.kjmagnan1s.profile-stats.plist (see README in this folder).
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
cd "$(dirname "$0")/.." || exit 1
LOG="$HOME/.claude/profile-stats-refresh.log"
{
  echo "=== $(date) ==="
  python3 scripts/update_stats.py --push
  echo
} >> "$LOG" 2>&1
