from __future__ import annotations

from core.config import ClientSpec, InstallConfig
from core.render import render_haproxy_block
from utils.haproxy import (
    find_port_conflicts,
    is_v1_managed,
    merge_managed_block,
    strip_managed_block,
)

BASE = """global
    log /dev/log local0
    maxconn 4096
    daemon

defaults
    mode http
    timeout connect 5s

frontend web
    bind *:80
    default_backend app

backend app
    server app1 127.0.0.1:8080
"""


def _config(**kwargs):
    base = dict(
        server_ip="203.0.113.10",
        endpoint_host="vpn.example.com",
        endpoint_mode="domain",
        domain="vpn.example.com",
        users=[ClientSpec("MHH06-01", "mhh0601", "Correct-Horse-Battery-9")],
    )
    base.update(kwargs)
    return InstallConfig(**base)


def test_append_preserves_existing_config():
    block = render_haproxy_block(_config())
    merged, created = merge_managed_block(BASE, block)
    assert created
    assert merged.startswith(BASE.rstrip())
    assert "ovpn_wizard_frontend_443" in merged


def test_merge_is_idempotent():
    block = render_haproxy_block(_config())
    first, _ = merge_managed_block(BASE, block)
    second, created = merge_managed_block(first, block)
    assert not created
    assert second == first


def test_remove_restores_original_exactly():
    block = render_haproxy_block(_config())
    merged, _ = merge_managed_block(BASE, block)
    cleaned, found = strip_managed_block(merged)
    assert found
    assert cleaned.strip() == BASE.strip()


def test_conflict_detection_ignores_our_block():
    block = render_haproxy_block(_config())
    merged, _ = merge_managed_block(BASE, block)
    assert find_port_conflicts(merged, 443) == []


def test_conflict_detection_finds_other_frontend():
    existing = BASE.replace("bind *:80", "bind *:443 ssl crt /tmp/x.pem")
    conflicts = find_port_conflicts(existing, 443)
    assert len(conflicts) == 1
    assert conflicts[0][0] == 11


def test_ipv6_and_star_binds_detected():
    assert find_port_conflicts("frontend a\n    bind [::]:443\n", 443)
    assert find_port_conflicts("frontend a\n    bind 0.0.0.0:443\n", 443)
    assert find_port_conflicts("frontend a\n    bind :443\n", 443)
    assert find_port_conflicts("frontend a\n    bind *:8443\n", 8443)


def test_v1_detection():
    v1 = """global
    daemon
frontend https_in
    bind *:443 ssl crt /etc/haproxy/certs/x.pem
frontend ovpn_tcp
    bind *:443
backend openvpn_tcp
    server x 127.0.0.1:1194
"""
    assert is_v1_managed(v1)
    assert not is_v1_managed(BASE)


def test_vless_block_contains_sni_routes():
    config = _config(
        enable_vless=True, domain1="a.example.com", domain2="b.example.com",
        reality_domain="www.cloudflare.com",
    )
    block = render_haproxy_block(config)
    assert "a.example.com" in block
    assert "b.example.com" in block
    assert "www.cloudflare.com" in block
    assert "ovpn_wizard_vless_1" in block
