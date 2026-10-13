"""Configuration: built-in defaults, then flect.toml, then FLECT_* environment overrides."""
from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path

MODES = ("off", "observe", "enforce")
CAPABILITIES = ("prguard", "dos", "crash", "cicd", "vapt", "keys")

DEFAULTS: dict = {
    "general": {"data_dir": "~/flect/data", "dry_run": False},
    # Every capability starts in observe mode: detect and report, never act.
    "modes": {"prguard": "observe", "dos": "observe", "crash": "observe",
              "cicd": "observe", "vapt": "observe", "keys": "observe"},
    "llm": {
        "base_url": "http://127.0.0.1:1111/v1",
        "max_in_flight": 2,
        "timeouts_s": {"crash": 900, "prguard": 1200, "vapt": 1800, "narrative": 300},
        "max_output_tokens": {"crash": 4096, "prguard": 1500, "vapt": 2000, "narrative": 600},
        "max_prompt_chars": {"crash": 96000, "prguard": 72000, "vapt": 48000, "narrative": 18000},
    },
    "github": {
        "repo": "soczap/Computer_Vision",
        "poll_interval_s": 30,
        "identity_name": "soczap",
        "identity_email": "67731207+soczap@users.noreply.github.com",
        "feature_base": "uat",
        "prod_branch": "main",
        # GitHub logins allowed to override a needs-human verdict with a "/flect approve" PR comment.
        "approvers": ["soczap"],
    },
    "target": {
        "name": "vigil",
        "prod_dir": "~/VIGIL",
        "prod_unit": "vigil.service",
        "prod_url": "https://127.0.0.1:8090",
        "uat_dir": "~/VIGIL-uat",
        "uat_data_dir": "~/VIGIL-uat-data",
        "uat_unit": "vigil-uat.service",
        "uat_url": "https://127.0.0.1:8190",
        "venv": "~/VIGIL/.venv",
        "logs": ["~/VIGIL/data/logs/vigil.log", "~/VIGIL/data/logs/service.out"],
        "health_path": "/api/health",
        "protected_ports": [8090, 8190],
        "tls_certs": ["~/VIGIL/certs/server.crt"],
    },
    "dos": {
        "allowlist": ["127.0.0.0/8", "::1/128", "192.168.7.0/24", "100.87.127.50/32", "fd7a:115c:a1e0::/48"],
        "per_ip_rps": 20.0,
        "per_ip_sustain_s": 10,
        "failed_logins_per_min": 50,
        "failed_paths_per_min": 60,
        "global_flood_factor": 5.0,
        "global_min_rps": 50.0,
        "ttl_ladder": ["15m", "1h", "24h"],
    },
    "crash": {
        "health_interval_s": 5,
        "health_fail_probes": 3,
        "restart_loop_count": 2,
        "restart_loop_window_s": 120,
        "error_burst_count": 5,
        "error_burst_window_s": 600,
        "lkg_healthy_minutes": 10,
        "hotfix_max_lines": 200,
        "hotfix_max_files": 5,
        "hotfix_forbidden_paths": ["deploy/", ".github/", "Makefile", "vigil/security.py", "vigil/api/auth.py"],
        "fix_attempts": 3,
        "post_deploy_watch_minutes": 10,
    },
    "keys": {"interval_s": 3600, "warn_days": [7, 3, 1], "cert_warn_days": 30, "extra": []},
    "dashboard": {"host": "127.0.0.1", "port": 1113},
    "sandbox": {
        "bwrap": "/usr/local/lib/flect/bwrap",
        "memory_max": "2G",
        "cpu_quota": "200%",
        "tasks_max": 256,
        "runtime_max_s": 600,
    },
    "nft": {"helper": "/usr/local/sbin/flect-nft"},
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _expand(value):
    if isinstance(value, str) and value.startswith("~"):
        return str(Path(value).expanduser())
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


class Config:
    def __init__(self, data: dict, path: Path | None = None):
        self.data = data
        self.path = path
        for cap, mode in data["modes"].items():
            if mode not in MODES:
                raise ValueError(f"modes.{cap} must be one of {MODES}, got {mode!r}")

    def __getitem__(self, key):
        return self.data[key]

    @property
    def data_dir(self) -> Path:
        return Path(self.data["general"]["data_dir"])

    def mode(self, capability: str) -> str:
        if self.data["general"].get("dry_run"):
            return "observe" if self.data["modes"].get(capability) != "off" else "off"
        return self.data["modes"].get(capability, "off")


def load(path: str | os.PathLike | None = None, env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    path = Path(path or env.get("FLECT_CONFIG") or Path("~/flect/flect.toml").expanduser())
    data = copy.deepcopy(DEFAULTS)
    if path.is_file():
        data = _merge(data, tomllib.loads(path.read_text()))
    if env.get("FLECT_DATA_DIR"):
        data["general"]["data_dir"] = env["FLECT_DATA_DIR"]
    if env.get("FLECT_DRY_RUN"):
        data["general"]["dry_run"] = env["FLECT_DRY_RUN"].lower() in {"1", "true", "yes"}
    for cap in CAPABILITIES:
        value = env.get(f"FLECT_MODE_{cap.upper()}")
        if value:
            data["modes"][cap] = value
    return Config(_expand(data), path if path.is_file() else None)
