from __future__ import annotations

import os
import stat


from core.config import ClientSpec, InstallConfig
from core.plan import build_plan


def _config(**kwargs):
    base = dict(
        server_ip="203.0.113.10",
        endpoint_mode="domain",
        endpoint_host="vpn.example.com",
        domain="vpn.example.com",
        vpn_proto="tcp",
        public_port=443,
        auth_mode="userpass",
        access_mode="free",
        users=[
            ClientSpec("MHH06-01", "mhh0601", "Correct-Horse-Battery-9"),
            ClientSpec("MHH06-02", "mhh0602", "Another-Strong-Pass-42"),
        ],
    )
    base.update(kwargs)
    return InstallConfig(**base)


def test_plan_renders_valid_tcp_profiles(tmp_path):
    result = build_plan(_config(), tmp_path / "plan")
    assert result["problems"] == []
    server = open(result["server_conf"]).read()
    assert "proto tcp-server" in server
    assert "local 127.0.0.1" in server
    assert "port 1194" in server
    assert "tls-crypt" in server
    assert "data-ciphers AES-256-GCM" in server
    assert "tls-version-min 1.2" in server
    assert "comp-lzo" not in server
    assert "\ncompress " not in server
    assert "dh none" in server

    for path in result["profiles"]:
        content = open(path).read()
        assert "proto tcp-client" in content
        assert "remote vpn.example.com 443" in content
        assert "verify-x509-name server name" in content
        assert "auth-user-pass" in content
        assert content.count("<tls-crypt>") == 1
        assert "-----BEGIN CERTIFICATE-----" in content
        assert "-----BEGIN PRIVATE KEY-----" in content
        assert "key-direction" not in content
        assert "comp-lzo" not in content
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_plan_locked_cert_only(tmp_path):
    config = _config(auth_mode="cert", access_mode="locked",
                     users=[ClientSpec("Locked", "locked", "")])
    result = build_plan(config, tmp_path / "plan")
    assert result["problems"] == []
    server = open(result["server_conf"]).read()
    assert 'push "redirect-gateway' not in server
    assert "openvpn-plugin-auth-pam.so" not in server
    client = open(result["profiles"][0]).read()
    assert "auth-user-pass" not in client
    assert "route-nopull" in client
    assert 'pull-filter ignore "redirect-gateway"' in client
    assert "route 10.8.0.0 255.255.255.0" in client


def test_plan_udp_binds_public(tmp_path):
    result = build_plan(_config(vpn_proto="udp", public_port=443), tmp_path / "plan")
    assert result["problems"] == []
    server = open(result["server_conf"]).read()
    assert "proto udp4" in server
    assert "port 443" in server
    assert "local 0.0.0.0" in server
    client = open(result["profiles"][0]).read()
    assert "proto udp" in client
    assert "explicit-exit-notify 2" in client
    assert result["haproxy_block"] == ""


def test_plan_no_haproxy_tcp(tmp_path):
    result = build_plan(_config(manage_haproxy=False), tmp_path / "plan")
    server = open(result["server_conf"]).read()
    assert "port 443" in server
    assert "local 0.0.0.0" in server
    assert result["haproxy_block"] == ""


def test_plan_haproxy_block(tmp_path):
    result = build_plan(_config(), tmp_path / "plan")
    block = open(result["haproxy_block"]).read()
    assert "frontend ovpn_wizard_frontend_443" in block
    assert "backend ovpn_wizard_openvpn" in block
    assert "127.0.0.1:1194" in block
    assert "openvpn-wizard managed block" in block


def test_plan_no_plaintext_password_in_profiles(tmp_path):
    config = _config()
    build_plan(config, tmp_path / "plan")
    for path in (tmp_path / "plan" / "clients").glob("*.ovpn"):
        content = path.read_text()
        assert "Correct-Horse-Battery-9" not in content
        assert "Another-Strong-Pass-42" not in content
