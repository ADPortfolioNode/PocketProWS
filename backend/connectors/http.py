"""Shared HTTP helper for job-board connectors.

Why this exists: in this VM, httpx's default env-proxy handling breaks —
it mis-parses the proxy environment (bracketed IPv6 entries in NO_PROXY)
and every outbound call fails with `InvalidURL: Invalid port: ':1]'`,
while direct egress is blocked (SSL wrong-version). Passing the egress
proxy EXPLICITLY works (verified live 2026-11-07: Remotive 200, 12 jobs)
— but trust_env must stay True, because the egress proxy MITMs TLS with
a cert in the system CA bundle (/run/hatch/egress-tls/ca-bundle.pem),
which httpx only picks up via the environment. On a normal host / Asura
there is no proxy env var, so this degrades to a plain direct call —
same code, both places.
"""
import os

import httpx


def _proxy():
    return os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None


def get(url, **kwargs):
    proxy = _proxy()
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.get(url, **kwargs)


def post(url, **kwargs):
    proxy = _proxy()
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.post(url, **kwargs)
