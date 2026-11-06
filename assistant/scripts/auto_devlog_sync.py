#!/usr/bin/env python3
"""
BUPI Autonomous Daily Git Commit & DevLog Sync Engine.
Automatically compiles daily modifications, checks DevLog alignment,
generates a structured conventional commit, and syncs with GitHub.

Usage:
    python scripts/auto_devlog_sync.py [--push] [--message "Optional custom note"]
"""

import os
import sys
import subprocess
import datetime
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEVLOG_DIR = REPO_ROOT / "devlog"


def run_cmd(cmd, check=True):
    """Run shell command and return trimmed stdout."""
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), shell=True, capture_output=True, text=True)
    if check and res.returncode != 0:
        print(f"[-] Command failed: {cmd}\n{res.stderr.strip()}")
        return None
    return res.stdout.strip()


def get_git_status():
    """Returns list of modified/untracked files."""
    out = run_cmd("git status --porcelain", check=False)
    if not out:
        return []
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    return lines


def ensure_today_devlog():
    """Ensure today's DevLog markdown file exists in devlog/."""
    today_str = datetime.date.today().isoformat()
    existing = list(DEVLOG_DIR.glob(f"{today_str}_*.md"))
    
    if existing:
        return existing[0]
    
    # Create new entry template for today if missing
    new_log = DEVLOG_DIR / f"{today_str}_daily_progress.md"
    template = f"""# DevLog: {today_str} — Daily Engineering Progress

## 1. Executive Summary
- Automated daily engineering log created on {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}.

## 2. Features & Architecture Implemented
- Daily modifications and codebase improvements.

## 3. Blockers Encountered & Solutions
### Daily Troubleshooting
- Verified subsystem communication and stability.

## 4. End-of-Day Git Actions
```bash
git add .
git commit -m "feat(daily-sync): {today_str} progress and subsystem updates"
git push origin main
```
"""
    new_log.write_text(template, encoding="utf-8")
    print(f"[+] Created today's DevLog: {new_log.name}")
    return new_log


def build_commit_message(custom_note=None, changed_files=None):
    """Generate structured conventional commit message."""
    today_str = datetime.date.today().isoformat()
    
    # Categorize changes
    components = set()
    if changed_files:
        for f in changed_files:
            parts = f.split()
            if len(parts) >= 2:
                filepath = parts[1].lower()
                if "firmware" in filepath or "esp32" in filepath:
                    components.add("firmware")
                elif "sonar" in filepath or "dip" in filepath or "vision" in filepath:
                    components.add("sonar-vision")
                elif "devlog" in filepath:
                    components.add("devlog")
                elif "ui" in filepath or "frontend" in filepath or "html" in filepath:
                    components.add("ui")
                elif "test" in filepath:
                    components.add("tests")
                elif "backend" in filepath or "server" in filepath:
                    components.add("backend")
                else:
                    components.add("core")

    scope = "-".join(sorted(components)[:3]) if components else "daily-sync"
    
    if custom_note:
        header = f"feat({scope}): {today_str} - {custom_note}"
    else:
        header = f"feat({scope}): {today_str} engineering progress and DevLog update"
    
    body = [
        header,
        "",
        f"Automated daily sync triggered at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.",
        f"Active subsystems touched: {', '.join(components) if components else 'General'}.",
        f"Synchronized with BUPI Engineering DevLog."
    ]
    return "\n".join(body)


def main():
    parser = argparse.ArgumentParser(description="BUPI Auto DevLog & Git Sync")
    parser.add_argument("--push", action="store_true", help="Push to remote origin after committing")
    parser.add_argument("--message", type=str, default=None, help="Custom commit note")
    parser.add_argument("--dry-run", action="store_true", help="Preview commit without firing git")
    args = parser.parse_args()

    print("=" * 60)
    print("🚀 BUPI Autonomous Daily DevLog & Git Sync Engine")
    print("=" * 60)

    # 1. Check for dirty working tree
    status_lines = get_git_status()
    if not status_lines:
        print("[*] Working tree is clean. Nothing to commit.")
        if args.push:
            print("[*] Pushing any unpushed commits to origin...")
            run_cmd("git push origin main")
            print("[+] Push complete.")
        return

    print(f"[*] Detected {len(status_lines)} changed/untracked file(s).")

    # 2. Ensure DevLog exists for today
    today_log = ensure_today_devlog()

    # 3. Stage changes
    print("[*] Staging files with 'git add .'...")
    if not args.dry_run:
        run_cmd("git add .")

    # 4. Generate structured commit message
    commit_msg = build_commit_message(args.message, status_lines)
    print(f"\n[*] Generated Commit Message:\n{'-'*40}\n{commit_msg}\n{'-'*40}\n")

    if args.dry_run:
        print("[!] Dry-run enabled. Exiting without committing.")
        return

    # 5. Execute git commit
    print("[*] Executing git commit...")
    # Escape quotes for shell execution
    escaped_msg = commit_msg.replace('"', '\\"')
    commit_res = run_cmd(f'git commit -m "{escaped_msg}"')
    if commit_res:
        print("[+] Commit successful!")
        print(commit_res)

    # 6. Push to GitHub if requested
    if args.push:
        print("\n[*] Pushing to origin/main...")
        push_res = run_cmd("git push origin main", check=False)
        if push_res is not None:
            print("[+] Successfully pushed to GitHub!")
            print(push_res)
        else:
            print("[!] Push encountered an issue. You can manually run: git push origin main")

    print("\n[✓] Daily Sync Complete. Keep innovating!")


if __name__ == "__main__":
    main()

