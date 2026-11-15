from __future__ import annotations

from utils.net import PortStatus, domain_points_to


def test_port_status_requires_both_protocols_to_be_free():
    assert PortStatus(443).available
    assert not PortStatus(443, tcp_owner="haproxy").available
    assert not PortStatus(443, udp_owner="dns").available


def test_domain_match_uses_resolved_addresses(monkeypatch):
    monkeypatch.setattr("utils.net.domain_addresses", lambda _domain: ["203.0.113.10"])
    assert domain_points_to("vpn.example.com", "203.0.113.10") == (True, ["203.0.113.10"])
