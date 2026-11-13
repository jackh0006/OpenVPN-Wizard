from __future__ import annotations

from pathlib import Path

from core.config import ClientSpec, InstallConfig
from core.detect import apply_existing_setup, detect_openvpn_config


def test_detects_reference_vps_settings():
    path = Path(__file__).parent / "fixtures" / "server_live.conf"
    detected = detect_openvpn_config(path)
    assert detected["port"] == 11944
    assert detected["proto"] == "tcp"
    assert detected["auth_digest"] == "SHA384"
    assert detected["tls_min"] == "1.3"
    assert detected["tls_max"] == "1.3"
    assert detected["tun_mtu"] == 1400
    assert detected["mssfix"] == 1360
    assert detected["sndbuf"] == 524288
    assert detected["rcvbuf"] == 524288
    assert detected["verify_client_cert"] == "none"
    assert detected["duplicate_cn"] is True


def test_apply_existing_setup_preserves_port_and_crypto(monkeypatch, tmp_path):
    import core.detect as detect

    path = Path(__file__).parent / "fixtures" / "server_live.conf"
    monkeypatch.setattr(detect, "DEFAULT_OPENVPN_CONF", path)
    config = InstallConfig(
        server_ip="203.0.113.10", endpoint_mode="ip",
        endpoint_host="203.0.113.10",
        users=[ClientSpec("A", "a", "Correct-Horse-Battery-9")],
    )
    apply_existing_setup(config)
    assert config.openvpn_listen_port == 11944
    assert config.auth_digest == "SHA384"
    assert config.tun_mtu == 1400
    assert config.mssfix == 1360
    assert config.sndbuf == 524288
    assert config.rcvbuf == 524288
    assert config.tls_min == "1.3"
    assert config.verify_client_cert == "none"
    assert config.duplicate_cn is True
