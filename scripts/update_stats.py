#!/usr/bin/env python3
"""Regenerate the AI-coding stats block in the profile README.

Reads three local sources, none of which leave this machine:
  1. Claude Code telemetry  -> ~/.claude/projects/**/*.jsonl  (token counts only)
  2. GitHub metrics         -> `gh` CLI (commits, PRs, repo counts)
  3. Lines of code          -> git numstat across repos under ~/Documents/GitHub

It rewrites only the text between the <!-- STATS:START --> and <!-- STATS:END -->
markers in ../README.md. Everything else in the README is left untouched.

Usage:
    python3 update_stats.py            # rewrite README.md on disk
    python3 update_stats.py --push     # rewrite, then git commit + push

If a GitHub/LOC source fails (offline, auth, macOS file-access prompt), that one
metric falls back to the value already rendered in the README, so the block never
regresses to blanks.
"""

import os
import re
import sys
import json
import glob
import subprocess
from datetime import date, datetime

HOME = os.path.expanduser("~")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(REPO_ROOT, "README.md")
LOGS = os.path.join(HOME, ".claude", "projects")
GH_REPOS_DIR = os.path.join(HOME, "Documents", "GitHub")
USER = "kjmagnan1s"
APPS_IN_FLIGHT = 7  # production apps shipped or actively building; bump by hand

START = "<!-- STATS:START"
END = "<!-- STATS:END -->"


# ----- formatting helpers -------------------------------------------------

def human(n):
    n = float(n)
    if n >= 1e9:
        b = n / 1e9
        return (f"{b:.0f}B" if b >= 100 else f"{b:.2f}".rstrip("0").rstrip(".") + "B")
    if n >= 1e6:
        m = n / 1e6
        return f"{m:.0f}M" if m >= 100 else f"{m:.1f}M"
    if n >= 1e3:
        k = n / 1e3
        return f"{k:.1f}K" if k < 10 else f"{k:.0f}K"
    return f"{int(n)}"


def pct(part, whole):
    return 0.0 if not whole else round(100.0 * part / whole, 1)


def gh_json(args):
    out = subprocess.check_output(["gh"] + args, text=True, stderr=subprocess.DEVNULL)
    return json.loads(out) if out.strip() else None


# ----- data sources -------------------------------------------------------

def read_tokens():
    """Sum token usage across all local Claude Code session logs."""
    fields = ("input_tokens", "output_tokens",
              "cache_creation_input_tokens", "cache_read_input_tokens")
    tot = {f: 0 for f in fields}
    by_model = {}
    msgs = 0
    dmin = dmax = None
    for path in glob.glob(os.path.join(LOGS, "**", "*.jsonl"), recursive=True):
        try:
            with open(path, errors="ignore") as fh:
                for line in fh:
                    if '"usage"' not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    m = obj.get("message", {})
                    u = m.get("usage")
                    if not u:
                        continue
                    model = m.get("model", "unknown")
                    ts = (obj.get("timestamp") or "")[:10]
                    if ts:
                        dmin = ts if dmin is None or ts < dmin else dmin
                        dmax = ts if dmax is None or ts > dmax else dmax
                    bucket = by_model.setdefault(model, 0)
                    line_total = 0
                    for f in fields:
                        v = u.get(f, 0) or 0
                        tot[f] += v
                        line_total += v
                    by_model[model] = bucket + line_total
                    msgs += 1
        except OSError:
            continue
    grand = sum(tot.values())
    opus = sum(v for k, v in by_model.items() if "opus" in k.lower())
    return {
        "input": tot["input_tokens"],
        "output": tot["output_tokens"],
        "cache_write": tot["cache_creation_input_tokens"],
        "cache_read": tot["cache_read_input_tokens"],
        "total": grand,
        "io": tot["input_tokens"] + tot["output_tokens"],
        "msgs": msgs,
        "opus_share": pct(opus, grand),
        "reuse": pct(tot["cache_read_input_tokens"], grand),
        "out_per_turn": (tot["output_tokens"] / msgs) if msgs else 0,
        "dmin": dmin,
        "dmax": dmax,
    }


def read_github(start, end):
    """All metrics scoped to the telemetry window [start, end]."""
    out = {}
    try:
        c = gh_json(["api", "-H", "Accept: application/vnd.github.cloak-preview+json",
                     f"/search/commits?q=author:{USER}+author-date:{start}..{end}&per_page=1"])
        out["commits"] = c.get("total_count")
    except Exception:
        out["commits"] = None
    try:
        p = gh_json(["api", f"/search/issues?q=author:{USER}+type:pr+created:{start}..{end}&per_page=1"])
        out["prs_opened"] = p.get("total_count")
    except Exception:
        out["prs_opened"] = None
    try:
        m = gh_json(["api", f"/search/issues?q=author:{USER}+type:pr+is:merged+merged:{start}..{end}&per_page=1"])
        out["prs_merged"] = m.get("total_count")
    except Exception:
        out["prs_merged"] = None
    try:
        repos = gh_json(["repo", "list", USER, "--limit", "200", "--json", "pushedAt"])
        out["repos_active"] = sum(1 for r in repos if (r.get("pushedAt") or "")[:10] >= start)
    except Exception:
        out["repos_active"] = None
    return out


def read_loc(start, end):
    """Lines added by Kevin across locally cloned repos in the window."""
    if not os.path.isdir(GH_REPOS_DIR):
        return None
    author = r"Kevin\|kjmagnan\|kevinmagnan"
    total = 0
    found = False
    for name in os.listdir(GH_REPOS_DIR):
        repo = os.path.join(GH_REPOS_DIR, name)
        if not os.path.isdir(os.path.join(repo, ".git")):
            continue
        try:
            out = subprocess.check_output(
                ["git", "-C", repo, "log", f"--since={start}", f"--until={end}",
                 f"--author={author}", "--pretty=tformat:", "--numstat"],
                text=True, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            continue
        for ln in out.splitlines():
            parts = ln.split("\t")
            if len(parts) == 3 and parts[0].isdigit():
                total += int(parts[0])
                found = True
    return total if found else None


# ----- fallback: keep last-known numbers if a source fails ----------------

def previous(label, text):
    m = re.search(r"\|\s*" + re.escape(label) + r".*?\|\s*\*\*(.+?)\*\*\s*\|", text)
    return m.group(1) if m else None


# ----- render -------------------------------------------------------------

def month_day(iso):
    d = datetime.strptime(iso, "%Y-%m-%d")
    return d.strftime("%b ") + str(d.day)


def render(tk, gh, loc, old):
    weeks = 6
    if tk["dmin"] and tk["dmax"]:
        weeks = max(1, round((datetime.strptime(tk["dmax"], "%Y-%m-%d") -
                              datetime.strptime(tk["dmin"], "%Y-%m-%d")).days / 7))
    year = tk["dmax"][:4] if tk["dmax"] else str(date.today().year)
    win = (f"{month_day(tk['dmin'])} – {month_day(tk['dmax'])}, {year}"
           if tk["dmin"] else "recent")

    def commits():
        return f"{gh['commits']:,}" if gh.get("commits") is not None else (previous("Commits", old) or "—")

    def prs():
        o, m = gh.get("prs_opened"), gh.get("prs_merged")
        return f"{o} / {m}" if o is not None and m is not None else (previous("Pull requests", old) or "—")

    def loc_s():
        return f"+{human(loc)}" if loc else (previous("Lines added", old) or "—")

    def repos():
        return f"{gh['repos_active']}" if gh.get("repos_active") is not None else (previous("Repos active", old) or "—")

    return f"""<!-- STATS:START — auto-generated by scripts/update_stats.py; edit the script, not this block -->

The last ~{weeks} weeks of AI engineering, pulled straight from local Claude Code logs and GitHub. A running total from here.

| Last {weeks} weeks &nbsp;·&nbsp; {win} | |
| :-- | --: |
| Tokens processed | **{human(tk['total'])}** |
| Commits | **{commits()}** |
| Pull requests (opened / merged) | **{prs()}** |
| Lines added | **{loc_s()}** |
| Repos active | **{repos()}** |
| Production apps shipped or in flight | **{APPS_IN_FLIGHT}+** |

{tk['reuse']}% context cache reuse &nbsp;·&nbsp; {tk['opus_share']:.0f}% on frontier Opus models &nbsp;·&nbsp; {tk['msgs']:,} agent turns.

<!-- STATS:END -->"""


def main():
    with open(README) as fh:
        text = fh.read()
    if START not in text or END not in text:
        sys.exit("markers not found in README.md")
    old_block = text[text.index(START):text.index(END) + len(END)]

    tk = read_tokens()
    start = tk["dmin"] or f"{date.today().year}-01-01"
    end = tk["dmax"] or date.today().isoformat()
    gh = read_github(start, end)
    loc = read_loc(start, end)
    block = render(tk, gh, loc, old_block)

    new_text = text.replace(old_block, block)
    if new_text == text:
        print("stats unchanged")
        return
    with open(README, "w") as fh:
        fh.write(new_text)
    print(f"updated: {human(tk['total'])} tokens, {tk['msgs']:,} turns, "
          f"window {tk['dmin']}..{tk['dmax']}")

    if "--push" in sys.argv:
        subprocess.run(["git", "-C", REPO_ROOT, "add", "README.md"], check=True)
        msg = f"chore: refresh AI-coding stats ({date.today().isoformat()})"
        r = subprocess.run(["git", "-C", REPO_ROOT, "commit", "-m", msg])
        if r.returncode == 0:
            subprocess.run(["git", "-C", REPO_ROOT, "push"], check=True)
            print("pushed")


if __name__ == "__main__":
    main()
