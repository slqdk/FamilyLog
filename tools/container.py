#!/usr/bin/env python3
"""Update FamilyLog in its container, with a backup and a way back.

Ported from SLQ Companion's tools/slq_container.py (2.66.0 - 2.67.1); the
flow is unchanged.

Run on the Docker host, from the clone (normally through ./update.sh):

    bash update.sh                  pull, build, back up, restart, check
    bash update.sh --yes            the same without the question (cron)
    bash update.sh status           version, health, newest backup
    bash update.sh backups          list the backups
    bash update.sh rollback         back to the newest backup (code + data)
    bash update.sh compose ps       docker compose with the right files

What `update` does, in an order that keeps the running app safe as long
as possible:

  1. Checks the clone is clean and on a branch the remote has, and that
     docker compose works. Fetches; nothing new -> nothing happens.
  2. Shows the new commits and version, and asks.
  3. Tags the running image `familylog:rollback`, pulls (fast-forward
     only) and BUILDS the new image while the old one keeps serving. A
     failed build puts the code back - the app was never touched.
  4. Stops the app and backs up the whole /data volume to
     <backups>/<time>_<version>.tar.gz (+ .json: commit, version, image).
     The app is stopped so SQLite is not copied mid-write.
  5. Starts the new image and waits until it answers
     /api/auth/status from inside the container.
  6. Healthy -> old backups beyond --keep are deleted. Not healthy within
     --timeout -> its log is shown and everything is put back: the old
     code, the old image, and /data from the backup in step 4 (the new
     version may already have migrated the database).

Backups go to $APP_BACKUP_DIR, default <clone>/../familylog-backups (so
/opt/familylog-backups for a clone in /opt/familylog). Your own compose changes (URLs,
a host folder instead of the named volume, the port) belong in
deploy/container/docker-compose.override.yml - git ignores it, so the
clone stays clean and updates are fast-forwards.

Standard library only; Python 3.9+ (Debian 12 has 3.11).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Out:
    """Colour when a terminal is attached, plain when piped."""

    def __init__(self) -> None:
        self.tty = sys.stdout.isatty()

    def _c(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.tty else text

    def say(self, text: str = "") -> None:
        print(text)

    def head(self, text: str) -> None:
        print(self._c(text, "36;1"))

    def ok(self, text: str) -> None:
        print(self._c("  [OK]   ", "32") + text)

    def warn(self, text: str) -> None:
        print(self._c("  [WARN] ", "33") + text)

    def bad(self, text: str) -> None:
        print(self._c("  [FAIL] ", "31") + text)

    def info(self, text: str) -> None:
        print("         " + text)


class Stop(Exception):
    """A refusal with a reason the user can act on."""


def backups_to_delete(names: list[str], keep: int) -> list[str]:
    """The ones to delete, oldest first. Names are timestamps, so lexical
    order is chronological."""
    return sorted(sorted(names, reverse=True)[keep:])


def stamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")


out = Out()

# The names of this install. The app's display name lives in
# backend/app/meta.py; these are the technical ones (compose service, image).
APP_TITLE = "FamilyLog"
SERVICE = "app"
IMAGE = "familylog"
COMPOSE = ROOT / "deploy" / "container" / "docker-compose.yml"
OVERRIDE = ROOT / "deploy" / "container" / "docker-compose.override.yml"
HEALTH_URL = "http://127.0.0.1:8080/api/auth/status"
KEEP = 3
TIMEOUT = 300
POLL = float(os.environ.get("APP_UPDATE_POLL", "3"))


# ---------------------------------------------------------------- running

def run(cmd: list[str], capture: bool = True, check: bool = False) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=capture, errors="replace")
    if check and r.returncode != 0:
        raise Stop(f"{' '.join(cmd[:4])} … failed:\n         "
                   + ((r.stderr or r.stdout or "").strip()[-800:] if capture else "see above"))
    return r


def git(*args: str) -> subprocess.CompletedProcess:
    return run(["git", *args])


def compose_files() -> list[str]:
    files = ["-f", str(COMPOSE)]
    if OVERRIDE.is_file():
        files += ["-f", str(OVERRIDE)]
    return files


def compose(*args: str, capture: bool = True, check: bool = False) -> subprocess.CompletedProcess:
    return run(["docker", "compose", *compose_files(), *args], capture=capture, check=check)


def backup_dir() -> Path:
    return Path(os.environ.get("APP_BACKUP_DIR") or (ROOT.parent / f"{IMAGE}-backups")).resolve()


def read_version_at(ref: str = "HEAD") -> str:
    r = git("show", f"{ref}:VERSION")
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "unknown"


# ---------------------------------------------------------------- decisions

def failed_file() -> Path:
    return backup_dir() / "last-failed.json"


def last_failed() -> dict:
    try:
        return json.loads(failed_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def backup_name(version: str, now: datetime | None = None) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ".-" else "_" for ch in version)
    return f"{stamp(now)}_{safe}"


def list_backups(where: Path) -> list[dict]:
    """Newest first. A backup is a .tar.gz with its .json beside it."""
    items = []
    for meta in sorted(where.glob("*.json"), reverse=True):
        tar = where / (meta.stem + ".tar.gz")
        if not tar.is_file():
            continue
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        info.update(name=meta.stem, size=tar.stat().st_size)
        items.append(info)
    return items


def health_verdict(state: str, answered: bool, restarts_seen: int) -> str:
    """'ok', 'wait' or 'failed' from one poll: the container's state, whether
    the app answered inside it, and how many polls in a row it was
    restarting (a crash loop under restart: unless-stopped)."""
    if answered and state == "running":
        return "ok"
    if state in ("exited", "dead"):
        return "failed"
    if restarts_seen >= 3:
        return "failed"
    return "wait"


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


# ---------------------------------------------------------------- steps

def preflight(need_clean: bool = True) -> str:
    for tool in ("git", "docker"):
        if shutil.which(tool) is None:
            raise Stop(f"{tool} is not installed, or not on PATH.")
    if run(["docker", "compose", "version"]).returncode != 0:
        raise Stop("docker compose is not available (apt install docker-compose-plugin), "
                   "or this user may not use Docker (add it to the docker group, or use sudo).")
    if not (ROOT / ".git").is_dir():
        raise Stop(f"{ROOT} is not a git clone. Clone it:\n"
                   f"           git clone <repo url> /opt/{IMAGE}")
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if need_clean:
        dirty = [l for l in git("status", "--porcelain", "--untracked-files=no").stdout.splitlines() if l.strip()]
        if dirty:
            out.warn("Files in the clone have been changed by hand:")
            for l in dirty:
                out.info(l)
            raise Stop("put your own settings in deploy/container/docker-compose.override.yml "
                       "and undo the edits (git checkout -- <file>), then update again.")
    return branch


def image_id(tag: str) -> str | None:
    r = run(["docker", "image", "inspect", f"{IMAGE}:{tag}", "--format", "{{.Id}}"])
    return r.stdout.strip() or None if r.returncode == 0 else None


def container_id() -> str | None:
    r = compose("ps", "-a", "-q", SERVICE)
    return r.stdout.strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else None


def container_state() -> str:
    cid = container_id()
    if not cid:
        return "missing"
    r = run(["docker", "inspect", "--format", "{{.State.Status}}", cid])
    return r.stdout.strip() or "missing" if r.returncode == 0 else "missing"


def answers() -> bool:
    return compose("exec", "-T", SERVICE, "curl", "-fsS", "-o", "/dev/null", HEALTH_URL).returncode == 0


def wait_healthy(timeout: float) -> bool:
    start, restarting = time.monotonic(), 0
    out.info(f"Waiting for the app to answer (up to {int(timeout)} s)…")
    while time.monotonic() - start < timeout:
        state = container_state()
        restarting = restarting + 1 if state == "restarting" else 0
        verdict = health_verdict(state, state == "running" and answers(), restarting)
        if verdict == "ok":
            out.ok(f"The app answers ({int(time.monotonic() - start)} s)")
            return True
        if verdict == "failed":
            out.bad(f"The container is {state}.")
            return False
        time.sleep(POLL)
    out.bad(f"No answer within {int(timeout)} s.")
    return False


def show_log(lines: int = 40) -> None:
    r = compose("logs", "--no-color", "--tail", str(lines), SERVICE)
    text = (r.stdout or "") + (r.stderr or "")
    if text.strip():
        out.say("  ---- container log (last lines) ----")
        for l in text.rstrip().splitlines()[-lines:]:
            out.say("  | " + l)
        out.say("  ------------------------------------")


def tar_in_container(script: str, where: Path) -> subprocess.CompletedProcess:
    """Run a shell snippet as root in a throwaway container of the service,
    with /data mounted as configured and the backup folder at /backup."""
    return compose("run", "--rm", "--no-deps", "-T", "--user", "0:0", "--entrypoint", "sh",
                   "-v", f"{where}:/backup", SERVICE, "-c", script)


def make_backup(name: str, info: dict) -> Path:
    where = backup_dir()
    where.mkdir(parents=True, exist_ok=True)
    r = tar_in_container(f"tar --numeric-owner -czf /backup/{name}.tar.gz -C /data .", where)
    tar = where / f"{name}.tar.gz"
    if r.returncode != 0 or not tar.is_file():
        raise Stop("the backup of /data failed:\n         "
                   + (r.stderr or r.stdout or "").strip()[-600:])
    (where / f"{name}.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    return tar


def restore_data(name: str) -> None:
    where = backup_dir()
    if not (where / f"{name}.tar.gz").is_file():
        raise Stop(f"no backup {name}.tar.gz in {where}")
    r = tar_in_container(
        f"find /data -mindepth 1 -maxdepth 1 -exec rm -rf {{}} + && "
        f"tar --numeric-owner -xzf /backup/{name}.tar.gz -C /data", where)
    if r.returncode != 0:
        raise Stop("restoring /data failed:\n         " + (r.stderr or r.stdout or "").strip()[-600:])


def prune_backups(keep: int) -> list[str]:
    where = backup_dir()
    names = [b["name"] for b in list_backups(where)]
    gone = backups_to_delete(names, keep)
    for n in gone:
        for ext in (".tar.gz", ".json"):
            (where / f"{n}{ext}").unlink(missing_ok=True)
    return gone


def put_back(commit: str, image: str | None, backup: str | None, timeout: float) -> bool:
    """Old code, old image, and (when given) the data from `backup`."""
    out.head("Putting the previous version back…")
    compose("stop", SERVICE)
    git("reset", "--hard", commit)
    out.ok(f"Code   : back at {commit[:10]} ({read_version_at()})")
    rollback_id = image_id("rollback")
    if image and rollback_id == image:
        run(["docker", "tag", f"{IMAGE}:rollback", f"{IMAGE}:latest"], check=True)
        out.ok("Image  : the previous image")
    else:
        out.info("The previous image is gone - building it from the old code…")
        if compose("build", capture=False).returncode != 0:
            raise Stop("rebuilding the previous version failed. Data is in the backup; "
                       "see docs/CONTAINER.md, Updates.")
        out.ok("Image  : rebuilt")
    if backup:
        restore_data(backup)
        out.ok(f"Data   : restored from {backup}")
    compose("up", "-d", capture=False, check=True)
    return wait_healthy(timeout)


# ---------------------------------------------------------------- commands

def cmd_update(args) -> int:
    out.head(f"=== {APP_TITLE} - container update ===")
    branch = preflight()
    old = git("rev-parse", "HEAD").stdout.strip()
    old_version = read_version_at()
    out.info(f"Clone  : {ROOT}  ({branch} at {old[:10]}, version {old_version})")
    out.info(f"Backups: {backup_dir()}")

    if git("fetch", "--tags", "origin").returncode != 0:
        raise Stop("could not fetch from GitHub. Network, or the clone's credentials "
                   "(a private repo needs a deploy key or token on this host).")
    if git("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}").returncode != 0:
        raise Stop(f"the clone is on '{branch}', which the remote does not have.")
    incoming = [l for l in git("log", "--oneline", f"HEAD..origin/{branch}").stdout.splitlines() if l.strip()]
    if not incoming and not args.force:
        out.ok(f"Already up to date ({old_version}). Nothing to do.")
        return 0
    new_version = read_version_at(f"origin/{branch}")
    target = git("rev-parse", f"origin/{branch}").stdout.strip()
    failed = last_failed()
    if failed.get("commit") == target and not args.force:
        raise Stop(f"{new_version} ({target[:10]}) did not start when it was tried at "
                   f"{failed.get('at')}, and nothing newer has been pushed. Push a fix, or "
                   "try it again with --force.")
    if incoming:
        out.head(f"New: {old_version} -> {new_version}")
        for l in incoming[:30]:
            out.info(l)
        if len(incoming) > 30:
            out.info(f"… and {len(incoming) - 30} more")
    else:
        out.warn("No new commits - rebuilding and restarting anyway (--force).")

    if not args.yes:
        if not sys.stdin.isatty():
            raise Stop("not asking without a terminal - add --yes to update unattended.")
        if input("\n  Update now? The app is stopped for the backup. [y/N] ").strip().lower() not in ("y", "yes", "j", "ja"):
            out.info("Nothing changed.")
            return 0

    # 3. Build the new image next to the running one.
    old_image = image_id("latest")
    if old_image:
        run(["docker", "tag", f"{IMAGE}:latest", f"{IMAGE}:rollback"], check=True)
    if incoming and run(["git", "merge", "--ff-only", f"origin/{branch}"], capture=False).returncode != 0:
        raise Stop("the update is not a fast-forward - the clone has commits of its own.")
    out.head("Building the new image (the app keeps running)…")
    if compose("build", capture=False).returncode != 0:
        git("reset", "--hard", old)
        if old_image:
            run(["docker", "tag", f"{IMAGE}:rollback", f"{IMAGE}:latest"])
        raise Stop("the build failed (see above). The code is back where it was and the "
                   "app was never stopped.")
    out.ok("Built")

    # 4. Back up /data with the app stopped.
    name = None
    first = container_id() is None
    if args.no_backup:
        out.warn("Backup : skipped (--no-backup)")
    elif first:
        out.info("Backup : skipped - first start, there is no data yet")
    else:
        out.head("Backing up /data…")
        compose("stop", SERVICE, check=True)
        name = backup_name(old_version)
        try:
            tar = make_backup(name, {"commit": old, "version": old_version, "image": old_image,
                                     "created": datetime.now().isoformat(timespec="seconds"),
                                     "reason": "before update to " + new_version})
        except Stop:
            out.bad("Starting the old version again.")
            git("reset", "--hard", old)
            if old_image:
                run(["docker", "tag", f"{IMAGE}:rollback", f"{IMAGE}:latest"])
            compose("up", "-d")
            raise
        out.ok(f"Backup : {tar.name} ({human(tar.stat().st_size)})")

    # 5. Start the new one and check it.
    out.head("Starting the new version…")
    compose("up", "-d", capture=False, check=True)
    if wait_healthy(args.timeout):
        gone = prune_backups(args.keep)
        if gone:
            out.info(f"Deleted {len(gone)} old backup(s), keeping {args.keep}.")
        run(["docker", "image", "prune", "-f"])
        failed_file().unlink(missing_ok=True)
        out.head("=== Update complete ===")
        out.info(f"Version: {old_version} -> {read_version_at()}")
        return 0

    # 6. Not healthy: everything back.
    show_log()
    if not old_image:
        raise Stop("the new version does not start, and there is no earlier image to go back to.")
    backup_dir().mkdir(parents=True, exist_ok=True)
    failed_file().write_text(json.dumps({"commit": target, "version": new_version,
                                         "at": datetime.now().isoformat(timespec="seconds")}),
                             encoding="utf-8")
    if put_back(old, old_image, name, args.timeout):
        out.head("=== Update undone ===")
        out.warn(f"{new_version} did not start; {old_version} is running again with the data "
                 f"from before. update.sh skips {new_version} until something newer is pushed "
                 "(or --force).")
        return 1
    show_log()
    raise Stop("the previous version did not come back either. The backup is "
               f"{name or '(none)'} in {backup_dir()}; see docs/CONTAINER.md, Updates.")


def cmd_rollback(args) -> int:
    out.head(f"=== {APP_TITLE} - roll back ===")
    preflight()
    backups = list_backups(backup_dir())
    if not backups:
        raise Stop(f"there are no backups in {backup_dir()}.")
    pick = next((b for b in backups if b["name"] == args.backup), None) if args.backup else backups[0]
    if pick is None:
        raise Stop(f"no backup called {args.backup}. `update.sh backups` lists them.")
    commit = pick.get("commit")
    if not commit or git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        raise Stop(f"the backup does not name a commit this clone has ({commit}).")
    out.info(f"Back to : {pick['name']} - version {pick.get('version')}, made {pick.get('created')}")
    out.warn(f"Everything changed in {APP_TITLE} since then (Økonomi, FamilyMap, settings) is replaced by the "
             "backup. A backup of the current state is made first.")
    if not args.yes:
        if not sys.stdin.isatty():
            raise Stop("not asking without a terminal - add --yes.")
        if input("  Roll back? [y/N] ").strip().lower() not in ("y", "yes", "j", "ja"):
            out.info("Nothing changed.")
            return 0
    compose("stop", SERVICE)
    now_version = read_version_at()
    safety = backup_name(now_version) + "-before-rollback"
    make_backup(safety, {"commit": git("rev-parse", "HEAD").stdout.strip(), "version": now_version,
                         "image": image_id("latest"),
                         "created": datetime.now().isoformat(timespec="seconds"),
                         "reason": "before rolling back to " + pick["name"]})
    out.ok(f"Current state saved as {safety}")
    if put_back(commit, pick.get("image"), pick["name"], args.timeout):
        out.head("=== Rolled back ===")
        out.info(f"Version: {read_version_at()}. `update.sh` brings the newest version back.")
        return 0
    show_log()
    raise Stop(f"the restored version does not answer. {safety} holds the state from before.")


def cmd_status(args) -> int:
    out.head(f"=== {APP_TITLE} - status ===")
    preflight(need_clean=False)
    head = git("rev-parse", "--short", "HEAD").stdout.strip()
    out.info(f"Clone  : {ROOT} at {head}, version {read_version_at()}")
    state = container_state()
    (out.ok if state == "running" else out.warn)(f"Container: {state}")
    if state == "running":
        (out.ok if answers() else out.bad)("App answers" if answers() else "App does not answer")
    out.info(f"Image  : latest {(image_id('latest') or 'none')[:19]}, "
             f"rollback {(image_id('rollback') or 'none')[:19]}")
    b = list_backups(backup_dir())
    out.info(f"Backups: {len(b)} in {backup_dir()}" + (f", newest {b[0]['name']}" if b else ""))
    return 0


def cmd_backups(args) -> int:
    b = list_backups(backup_dir())
    if not b:
        out.info(f"No backups in {backup_dir()}.")
        return 0
    for x in b:
        out.say(f"  {x['name']:<38} {human(x['size']):>9}  version {x.get('version', '?'):<9} "
                f"{x.get('reason', '')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "compose":          # passthrough, flags and all
        return run(["docker", "compose", *compose_files(), *argv[1:]], capture=False).returncode
    if not argv or argv[0].startswith("-"):
        argv = ["update", *argv]
    p = argparse.ArgumentParser(prog="update.sh", description=f"{APP_TITLE} container updates")
    sub = p.add_subparsers(dest="command", required=True)
    u = sub.add_parser("update", help="pull, build, back up, restart, check (the default)")
    u.add_argument("--yes", "-y", action="store_true", help="do not ask")
    u.add_argument("--force", action="store_true", help="rebuild and restart even with nothing new")
    u.add_argument("--no-backup", action="store_true", help="skip the /data backup")
    u.add_argument("--keep", type=int, default=KEEP, help=f"backups to keep (default {KEEP})")
    u.add_argument("--timeout", type=float, default=TIMEOUT, help="seconds to wait for the app")
    r = sub.add_parser("rollback", help="back to a backup: its code, image and data")
    r.add_argument("backup", nargs="?", help="backup name (default: the newest)")
    r.add_argument("--yes", "-y", action="store_true")
    r.add_argument("--timeout", type=float, default=TIMEOUT)
    sub.add_parser("status", help="version, container, health, backups")
    sub.add_parser("backups", help="list the backups")
    sub.add_parser("compose", help="docker compose with this install's files")
    args = p.parse_args(argv)
    try:
        return {"update": cmd_update, "rollback": cmd_rollback, "status": cmd_status,
                "backups": cmd_backups}[args.command](args)
    except Stop as stop:
        out.say()
        out.bad(f"STOPPED: {stop}")
        out.say()
        return 1
    except KeyboardInterrupt:
        out.say()
        out.warn("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
