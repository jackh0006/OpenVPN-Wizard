from __future__ import annotations

import pytest

from cli import _config_from_options


def test_cli_config_builder_makes_unique_keys():
    config = _config_from_options(
        server_ip="203.0.113.10", profiles=3, prefix="Test",
    )
    assert len(config.users) == 3
    names = {u.name for u in config.users}
    users = {u.username for u in config.users}
    assert len(names) == 3
    assert len(users) == 3
    assert config.users[0].password != config.users[1].password


def test_cli_config_builder_rejects_bad_port():
    with pytest.raises(Exception):
        _config_from_options(server_ip="203.0.113.10", port=70000)


def test_cli_config_builder_users_list():
    config = _config_from_options(
        server_ip="203.0.113.10", users_raw="MHH06-01,Phone,Tablet",
        domain="vpn.example.com",
    )
    assert [u.name for u in config.users] == ["MHH06-01", "Phone", "Tablet"]
    assert config.endpoint_mode == "domain"
    assert config.endpoint_host == "vpn.example.com"
