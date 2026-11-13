from __future__ import annotations

import shutil
import subprocess

import pytest

from core.config import ClientSpec, InstallConfig
from core.plan import build_plan


def _config(**kwargs):
    base = dict(
        server_ip="203.0.113.10",
        endpoint_mode="ip",
        endpoint_host="203.0.113.10",
        vpn_proto="tcp",
        public_port=443,
        auth_mode="userpass",
        access_mode="free",
        users=[ClientSpec("MHH06-01", "mhh0601", "Correct-Horse-Battery-9")],
    )
    base.update(kwargs)
    return InstallConfig(**base)


@pytest.mark.skipif(not shutil.which("openvpn"), reason="openvpn not installed")
@pytest.mark.parametrize("proto,access,auth", [
    ("tcp", "free", "userpass"),
    ("tcp", "locked", "cert"),
    ("udp", "free", "userpass"),
    ("udp", "locked", "cert"),
])
def test_openvpn_parses_rendered_configs(tmp_path, proto, access, auth):
    result = build_plan(
        _config(vpn_proto=proto, access_mode=access, auth_mode=auth,
                users=[ClientSpec("MHH06-01", "mhh0601",
                                  "Correct-Horse-Battery-9" if auth == "userpass" else "")]),
        tmp_path / "plan",
    )
    assert result["problems"] == []
    for path in [result["server_conf"], *result["profiles"]]:
        proc = subprocess.run(
            ["openvpn", "--config", path, "--show-gateway"],
            capture_output=True, text=True, timeout=20,
        )
        assert proc.returncode == 0, f"{path}: {proc.stderr}"
        assert "Options error" not in proc.stderr, f"{path}: {proc.stderr}"
