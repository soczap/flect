"""Client for the root-owned nftables helper (deploy/root/flect-nft), invoked via a narrow sudoers rule.

The helper itself re-validates every argument and refuses allowlisted ranges, so a bug here
cannot block loopback/LAN-admin addresses or run arbitrary nft commands.
"""
from __future__ import annotations

import ipaddress
import json
import os
import subprocess

VALID_TTLS = {"15m", "1h", "24h"}


class NftUnavailable(RuntimeError):
    pass


class Nft:
    def __init__(self, helper: str = "/usr/local/sbin/flect-nft"):
        self.helper = helper

    def available(self) -> bool:
        if not os.path.exists(self.helper):
            return False
        res = subprocess.run(["sudo", "-n", "-l", self.helper], capture_output=True, text=True, timeout=10, check=False)
        return res.returncode == 0

    def _call(self, *args: str) -> str:
        if not os.path.exists(self.helper):
            raise NftUnavailable("flect-nft helper not installed (run deploy/root/install-root.sh)")
        res = subprocess.run(["sudo", "-n", self.helper, *args], capture_output=True, text=True, timeout=20, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"flect-nft {args[0]} failed: {(res.stderr or res.stdout).strip()[:300]}")
        return res.stdout

    def block(self, ip: str, ttl: str) -> None:
        ipaddress.ip_address(ip)
        if ttl not in VALID_TTLS:
            raise ValueError(f"ttl must be one of {sorted(VALID_TTLS)}")
        self._call("add", ip, ttl)

    def unblock(self, ip: str) -> None:
        ipaddress.ip_address(ip)
        self._call("del", ip)

    def list(self) -> list[dict]:
        try:
            return json.loads(self._call("list") or "[]")
        except (json.JSONDecodeError, NftUnavailable):
            return []

    def flood(self, on: bool, rate: int = 50) -> None:
        self._call("flood-on", str(int(rate))) if on else self._call("flood-off")
