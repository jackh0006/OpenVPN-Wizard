from __future__ import annotations

import os

import pytest

from core.config import ClientSpec, InstallConfig
from utils import firewall


@pytest.fixture
def fake_firewall(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "rules.txt"
    state.write_text("")

    iptables = bin_dir / "iptables"
    iptables.write_text(f"""#!/usr/bin/env python3
import sys
from pathlib import Path
state = Path({str(state)!r})
args = sys.argv[1:]
table = "filter"
if "-t" in args:
    i = args.index("-t")
    table = args[i + 1]
    del args[i:i + 2]
action = next((a for a in args if a in ("-C", "-I", "-A", "-D")), None)
if action is None:
    sys.exit(0)
i = args.index(action)
chain = args[i + 1]
rest = args[i + 2:]
if action == "-I" and rest and rest[0].isdigit():
    rest = rest[1:]
key = " ".join([table, chain, *rest])
lines = [line for line in state.read_text().splitlines() if line]
if action == "-C":
    sys.exit(0 if key in lines else 1)
if action in ("-I", "-A"):
    if key not in lines:
        lines.append(key)
        state.write_text("\\n".join(lines) + "\\n")
    sys.exit(0)
if action == "-D":
    state.write_text("\\n".join(line for line in lines if line != key) + ("\\n" if lines else ""))
    sys.exit(0)
""")
    ufw = bin_dir / "ufw"
    ufw.write_text("#!/bin/sh\n[ \"$1\" = status ] && { echo 'Status: inactive'; exit 0; }\nexit 0\n")
    sysctl = bin_dir / "sysctl"
    sysctl.write_text("#!/bin/sh\nexit 0\n")
    modprobe = bin_dir / "modprobe"
    modprobe.write_text("#!/bin/sh\nexit 1\n")
    systemctl = bin_dir / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 1\n")
    ip = bin_dir / "ip"
    ip.write_text("#!/bin/sh\necho 'default via 192.0.2.1 dev eth0'\n")

    for path in (iptables, ufw, sysctl, modprobe, systemctl, ip):
        os.chmod(path, 0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr(firewall, "SYSCTL_PATH", tmp_path / "99-openvpn-wizard.conf")
    return state


def _config(tmp_path, **kwargs):
    base = dict(
        server_ip="203.0.113.10",
        endpoint_mode="ip",
        endpoint_host="203.0.113.10",
        users=[ClientSpec("A", "a", "Correct-Horse-Battery-9")],
        wan_interface="eth0",
    )
    base.update(kwargs)
    return InstallConfig(**base)


def test_free_mode_adds_nat_once(tmp_path, fake_firewall, monkeypatch):
    monkeypatch.setattr(firewall.FirewallManager, "_persist", lambda self, actions: None)
    config = _config(tmp_path, access_mode="free")
    manager = firewall.FirewallManager(config)
    manager.apply()
    first = fake_firewall.read_text()
    manager.apply()
    second = fake_firewall.read_text()
    assert first == second
    assert "nat POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE" in first
    assert "filter FORWARD -i tun0 -o eth0 -j ACCEPT" in first
    assert "filter INPUT -p tcp --dport 443 -j ACCEPT" in first


def test_locked_mode_has_no_nat(tmp_path, fake_firewall, monkeypatch):
    monkeypatch.setattr(firewall.FirewallManager, "_persist", lambda self, actions: None)
    config = _config(tmp_path, access_mode="locked")
    firewall.FirewallManager(config).apply()
    rules = fake_firewall.read_text()
    assert "MASQUERADE" not in rules
    assert "FORWARD" not in rules
    assert "filter INPUT -p tcp --dport 443 -j ACCEPT" in rules


def test_udp_opens_udp(tmp_path, fake_firewall, monkeypatch):
    monkeypatch.setattr(firewall.FirewallManager, "_persist", lambda self, actions: None)
    config = _config(tmp_path, vpn_proto="udp", public_port=1194)
    firewall.FirewallManager(config).apply()
    rules = fake_firewall.read_text()
    assert "filter INPUT -p udp --dport 1194 -j ACCEPT" in rules


def test_sysctl_uses_only_our_file(tmp_path, fake_firewall, monkeypatch):
    monkeypatch.setattr(firewall.FirewallManager, "_persist", lambda self, actions: None)
    config = _config(tmp_path)
    actions = firewall.FirewallManager(config).apply()
    content = firewall.SYSCTL_PATH.read_text()
    assert "net.ipv4.ip_forward = 1" in content
    assert "disable_ipv6" not in content
    assert str(firewall.SYSCTL_PATH) in actions["sysctl"]
