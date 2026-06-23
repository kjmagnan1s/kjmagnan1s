# Profile stats automation

`update_stats.py` regenerates the `AI coding, by the numbers` block in the top-level
`README.md`. It reads three local sources and rewrites only the text between the
`<!-- STATS:START -->` and `<!-- STATS:END -->` markers.

| Source | Where | Powers |
| :-- | :-- | :-- |
| Claude Code telemetry | `~/.claude/projects/**/*.jsonl` (token counts only) | token totals, cache reuse, model mix |
| GitHub | `gh` CLI | commits, PRs, repo counts |
| Local git | repos under `~/Documents/GitHub` | lines added this year |

Nothing here uploads log content. Only aggregate numbers land in the README.

## Refresh by hand (the reliable path)

```sh
cd ~/Documents/GitHub/kjmagnan1s
zsh scripts/refresh.sh          # recompute + commit + push
# or, no push:
python3 scripts/update_stats.py
```

## Schedule it weekly (optional)

A GitHub Action can't do this: the token data lives in `~/.claude` on this Mac, which
a cloud runner never sees. So scheduling has to be local. The `launchd` plist runs the
refresh every Monday at 9:00.

```sh
cp scripts/com.kjmagnan1s.profile-stats.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kjmagnan1s.profile-stats.plist
launchctl kickstart -k gui/$(id -u)/com.kjmagnan1s.profile-stats   # test once now
```

Two macOS gotchas if the scheduled run does nothing:
1. **Full Disk Access** — grant it to `/bin/zsh` (System Settings > Privacy & Security)
   so the job can read `~/Documents`. Without it, lines-of-code falls back to last-known
   and the rest still updates.
2. **git push auth** — the job pushes over SSH. If your key needs an agent, the auto-push
   may fail while a manual run from Terminal succeeds. Logs land in
   `~/.claude/profile-stats-refresh.log`.

Unschedule:

```sh
launchctl unload ~/Library/LaunchAgents/com.kjmagnan1s.profile-stats.plist
```
