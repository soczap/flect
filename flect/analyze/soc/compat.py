"""Minimal shims for the soc_engine helpers that scanner.py / auth_testing.py import."""
import hashlib
import json
from urllib.request import HTTPRedirectHandler


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirects are not permitted")
