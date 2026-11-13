from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from core.config import ClientSpec, InstallConfig
from core.exceptions import HAProxyConflictError
from utils.haproxy import HAProxyManager

EXISTING = """global
    daemon

defaults
    mode http

frontend web
    bind *:80
    default_backend app

backend app
    server app1 127.0.0.1:8080
"""


@pytest.fixture
def fake_bin(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    haproxy = bin_dir / "haproxy"
    haproxy.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  -v) exit 0 ;;\n"
        "  -c) exit 0 ;;\n"
        "esac\n"
        "exit 0\n"
    )
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  is-active) echo active; exit 0 ;;\n"
        "  reload-or-restart|reload|restart) echo ok; exit 0 ;;\n"
        "esac\n"
        "exit 0\n"
    )
    ss = bin_dir / "ss"
    ss.write_text("#!/bin/sh\nexit 0\n")
    for path in (haproxy, systemctl, ss):
        os.chmod(path, 0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    return bin_dir


def _config(tmp_path, **kwargs):
    cfg = tmp_path / "haproxy.cfg"
    cfg.write_text(EXISTING)
    base = dict(
        server_ip="203.0.113.10",
        endpoint_mode="ip",
        endpoint_host="203.0.113.10",
        users=[ClientSpec("MHH06-01", "mhh0601", "Correct-Horse-Battery-9")],
        haproxy_cfg=str(cfg),
        backup_dir=str(tmp_path / "backups"),
    )
    base.update(kwargs)
    return InstallConfig(**base)


def test_apply_appends_and_backs_up(tmp_path, fake_bin):
    config = _config(tmp_path)
    result = HAProxyManager(config).apply()
    assert result.changed
    text = Path(config.haproxy_cfg).read_text()
    assert text.startswith(EXISTING.rstrip())
    assert "ovpn_wizard_frontend_443" in text
    assert result.backup and Path(result.backup).exists()
    assert stat.S_IMODE(Path(result.backup).stat().st_mode) == 0o600


def test_apply_twice_is_idempotent(tmp_path, fake_bin):
    config = _config(tmp_path)
    manager = HAProxyManager(config)
    first = manager.apply()
    assert first.changed
    before = Path(config.haproxy_cfg).read_text()
    second = manager.apply()
    assert not second.changed
    assert Path(config.haproxy_cfg).read_text() == before


def test_conflict_leaves_file_untouched(tmp_path, fake_bin):
    config = _config(tmp_path)
    conflicting = EXISTING.replace("bind *:80", "bind *:443 ssl crt /tmp/x.pem")
    Path(config.haproxy_cfg).write_text(conflicting)
    with pytest.raises(HAProxyConflictError):
        HAProxyManager(config).apply()
    assert Path(config.haproxy_cfg).read_text() == conflicting


def test_remove_restores_exact_original(tmp_path, fake_bin):
    config = _config(tmp_path)
    manager = HAProxyManager(config)
    manager.apply()
    assert manager.remove()
    assert Path(config.haproxy_cfg).read_text().strip() == EXISTING.strip()


def test_udp_does_not_touch_haproxy(tmp_path, fake_bin):
    config = _config(tmp_path, vpn_proto="udp")
    result = HAProxyManager(config).apply()
    assert not result.changed
    assert Path(config.haproxy_cfg).read_text() == EXISTING


LIVE = (Path(__file__).parent / "fixtures" / "haproxy_live.cfg").read_text()


def test_reuses_live_multi_frontend_config_without_changes(tmp_path, fake_bin):
    """The real VPS config already routes 443 to 127.0.0.1:11944."""
    cfg = tmp_path / "haproxy.cfg"
    config = _config(tmp_path, haproxy_cfg=str(cfg), internal_port=11944)
    cfg.write_text(LIVE)
    before = cfg.read_text()
    result = HAProxyManager(config).apply()
    assert result.reused_existing
    assert not result.changed
    assert cfg.read_text() == before


def test_inserts_route_into_existing_tcp_frontend(tmp_path, fake_bin):
    base = """global
    daemon

defaults
    mode tcp
    timeout connect 5s
    timeout client 1h
    timeout server 1h

frontend web_tls
    bind *:443
    tcp-request inspect-delay 5s
    tcp-request content accept if { req_ssl_hello_type 1 }
    use_backend app_tls if { req.ssl_sni -i app.example.com }
    default_backend app_tls

backend app_tls
    mode tcp
    server app 127.0.0.1:8443
"""
    cfg = tmp_path / "haproxy.cfg"
    config = _config(tmp_path, haproxy_cfg=str(cfg), internal_port=11944)
    cfg.write_text(base)
    result = HAProxyManager(config).apply()
    assert result.changed and result.inserted_route
    text = cfg.read_text()
    assert "use_backend app_tls if { req.ssl_sni -i app.example.com }" in text
    assert "default_backend app_tls" in text
    assert "use_backend ovpn_wizard_openvpn if !{ req_ssl_hello_type 1 }" in text
    assert "server openvpn 127.0.0.1:11944" in text
    assert text.index("openvpn-wizard route") < text.index("default_backend app_tls")


def test_remove_after_route_insertion_restores_original(tmp_path, fake_bin):
    base = """global
    daemon

defaults
    mode tcp
    timeout connect 5s
    timeout client 1h
    timeout server 1h

frontend web_tls
    bind *:443
    default_backend app_tls

backend app_tls
    mode tcp
    server app 127.0.0.1:8443
"""
    cfg = tmp_path / "haproxy.cfg"
    config = _config(tmp_path, haproxy_cfg=str(cfg), internal_port=11944)
    cfg.write_text(base)
    manager = HAProxyManager(config)
    manager.apply()
    assert manager.remove()
    assert cfg.read_text().strip() == base.strip()


def test_http_frontend_on_port_is_refused(tmp_path, fake_bin):
    base = """defaults
    mode http
    timeout connect 5s

frontend web
    bind *:443
    default_backend app

backend app
    mode http
    server app 127.0.0.1:8080
"""
    cfg = tmp_path / "haproxy.cfg"
    config = _config(tmp_path, haproxy_cfg=str(cfg))
    cfg.write_text(base)
    with pytest.raises(HAProxyConflictError):
        HAProxyManager(config).apply()
    assert cfg.read_text() == base
