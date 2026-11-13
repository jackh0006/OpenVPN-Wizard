from __future__ import annotations


from core.config import (
    ClientSpec,
    InstallConfig,
    sanitize_profile_name,
    validate_config,
    validate_hostname,
    validate_ip,
    validate_password,
    validate_profile_name,
    validate_username,
)
from core.secrets import generate_password, hash_password, verify_password


def test_ip_and_hostname_validation():
    assert validate_ip("203.0.113.10")
    assert validate_ip("2001:db8::1")
    assert not validate_ip("999.1.1.1")
    assert validate_hostname("vpn.example.com")
    assert validate_hostname("203.0.113.10")
    assert not validate_hostname("not a host")


def test_password_rules():
    assert validate_password("Correct-Horse-Battery-9")[0]
    assert not validate_password("short")[0]
    assert not validate_password("alllowercase123!")[0]
    assert not validate_password("NoSymbols12345")[0]


def test_generated_password_is_valid():
    for _ in range(50):
        assert validate_password(generate_password())[0]


def test_hash_roundtrip():
    encoded = hash_password("Correct-Horse-Battery-9")
    assert verify_password("Correct-Horse-Battery-9", encoded)
    assert not verify_password("wrong", encoded)


def test_profile_name_sanitization():
    assert sanitize_profile_name("../../etc/passwd") == "etc-passwd"
    assert sanitize_profile_name("My Phone!") == "My-Phone"
    assert sanitize_profile_name("server") == "client-server"
    assert validate_profile_name("MHH06-01")
    assert not validate_profile_name("")
    assert not validate_profile_name(".hidden")


def test_username_validation():
    assert validate_username("mhh06-01")
    assert not validate_username("MHH06")
    assert not validate_username("bad name")


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


def test_valid_config():
    assert validate_config(_config()) == []


def test_duplicate_users_rejected():
    config = _config(users=[
        ClientSpec("A", "a", "Correct-Horse-Battery-9"),
        ClientSpec("a", "b", "Correct-Horse-Battery-9"),
    ])
    assert any("Duplicate profile" in p for p in validate_config(config))


def test_domain_mode_requires_valid_domain():
    config = _config(endpoint_mode="domain", endpoint_host="not a host", domain="")
    problems = validate_config(config)
    assert any("valid domain" in p for p in problems)


def test_udp_never_uses_haproxy():
    assert _config(vpn_proto="udp").use_haproxy is False
    assert _config(vpn_proto="tcp").use_haproxy is True
    assert _config(vpn_proto="tcp", manage_haproxy=False).use_haproxy is False


def test_locked_and_cert_only_are_valid():
    config = _config(auth_mode="cert", access_mode="locked",
                     users=[ClientSpec("A", "a", "")])
    assert validate_config(config) == []
