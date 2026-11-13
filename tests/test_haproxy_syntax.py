from __future__ import annotations

import shutil
import subprocess

import pytest

from core.config import ClientSpec, InstallConfig
from core.render import render_haproxy_block
from utils.haproxy import merge_managed_block

BASE = """global
    log /dev/log local0
    maxconn 4096
    daemon
    user haproxy
    group haproxy

defaults
    mode tcp
    log global
    option dontlognull
    timeout connect 5s
    timeout client 1h
    timeout server 1h
"""


def _config(**kwargs):
    base = dict(
        server_ip="203.0.113.10",
        endpoint_mode="ip",
        endpoint_host="203.0.113.10",
        users=[ClientSpec("MHH06-01", "mhh0601", "Correct-Horse-Battery-9")],
    )
    base.update(kwargs)
    return InstallConfig(**base)


@pytest.mark.skipif(not shutil.which("haproxy"), reason="haproxy not installed")
@pytest.mark.parametrize("vless", [False, True])
def test_haproxy_accepts_merged_config(tmp_path, vless):
    config = _config(
        enable_vless=vless,
        domain1="a.example.com",
        domain2="b.example.com",
        reality_domain="www.cloudflare.com",
    )
    merged, _ = merge_managed_block(BASE, render_haproxy_block(config))
    path = tmp_path / "haproxy.cfg"
    path.write_text(merged)
    proc = subprocess.run(["haproxy", "-c", "-f", str(path)],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr or proc.stdout
