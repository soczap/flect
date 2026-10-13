"""`flect` command line. Control commands talk to the running daemon over its 0600 unix socket."""
from __future__ import annotations

import argparse
import json
import socket
import sys

from flect import config as config_mod


def _send(cfg, payload: dict) -> dict:
    path = str(cfg.data_dir / "flect.sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(30)
        try:
            s.connect(path)
        except (FileNotFoundError, ConnectionRefusedError):
            sys.exit(f"flect daemon is not running (no socket at {path}). Start it: systemctl --user start flect")
        s.sendall((json.dumps(payload) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf or b"{}")


def cmd_status(cfg, args):
    r = _send(cfg, {"cmd": "status"})
    if args.json:
        print(json.dumps(r, indent=2, default=str))
        return
    h = r.get("health") or {}
    caps = r.get("capabilities") or {}
    print(f"Flect up {r.get('uptime_s')}s   GitHub writes paused: {r.get('writes_paused') or 'no'}")
    print(f"Prod health: {'OK' if h.get('http_ok') else 'FAILING'} (unit {h.get('active_state')}, restarts {h.get('n_restarts')})")
    print("Modes: " + ", ".join(f"{k}={v}" for k, v in (r.get("modes") or {}).items()))
    for key in ("sandbox", "nft", "uat", "llm", "github_poll"):
        print(f"  {key:12s} {caps.get(key)}")


def cmd_unblock(cfg, args):
    print(json.dumps(_send(cfg, {"cmd": "unblock", "ip": args.ip})))


def cmd_mode(cfg, args):
    print(json.dumps(_send(cfg, {"cmd": "mode", "capability": args.capability, "mode": args.mode})))


def cmd_pause(cfg, args):
    print(json.dumps(_send(cfg, {"cmd": "pause", "reason": " ".join(args.reason) or None})))


def cmd_resume(cfg, args):
    print(json.dumps(_send(cfg, {"cmd": "resume"})))


def cmd_keys(cfg, args):
    """One-shot expiry/liveness check without the daemon (prints names and dates only, never values)."""
    from flect.policy.rules import key_alert_level
    from flect.sources.keys import run_all
    for st in run_all(cfg):
        days = st.days_left()
        level = key_alert_level(st.kind, days, st.probe_ok, cfg["keys"]["warn_days"], cfg["keys"]["cert_warn_days"])
        exp = st.expires.strftime("%Y-%m-%d %H:%M UTC") if st.expires else "-"
        print(f"{level:8s} {st.name:34s} expires {exp:22s} days {str(days):8s} probe {st.probe_ok}  {st.details}")


def cmd_run(cfg, args):
    from flect.daemon import main
    main(args.config)


def main(argv=None):
    p = argparse.ArgumentParser(prog="flect", description="Agentic CI/CD that protects production.")
    p.add_argument("--config", help="path to flect.toml (default ~/flect/flect.toml)")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run the daemon in the foreground").set_defaults(fn=cmd_run)
    s = sub.add_parser("status", help="show daemon status")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)
    s = sub.add_parser("unblock", help="remove an IP block")
    s.add_argument("ip")
    s.set_defaults(fn=cmd_unblock)
    s = sub.add_parser("mode", help="set a capability mode: off | observe | enforce")
    s.add_argument("capability", choices=config_mod.CAPABILITIES)
    s.add_argument("mode", choices=config_mod.MODES)
    s.set_defaults(fn=cmd_mode)
    s = sub.add_parser("pause", help="pause all GitHub write actions")
    s.add_argument("reason", nargs="*")
    s.set_defaults(fn=cmd_pause)
    sub.add_parser("resume", help="resume GitHub write actions").set_defaults(fn=cmd_resume)
    sub.add_parser("keys", help="check key/token/cert expiry now (no daemon needed)").set_defaults(fn=cmd_keys)
    args = p.parse_args(argv)
    cfg = config_mod.load(args.config)
    args.fn(cfg, args)


if __name__ == "__main__":
    main()
