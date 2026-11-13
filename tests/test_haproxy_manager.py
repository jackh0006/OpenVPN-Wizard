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
