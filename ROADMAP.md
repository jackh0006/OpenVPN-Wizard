# Roadmap

This is a direction, not a promise. Security and compatibility work always
takes priority over new features.

## Next

- [ ] Optional IPv6 tunnel (not only host enable/disable).
- [ ] Import/adopt existing `/root/*.ovpn` profiles into the managed directory
      without copying private keys twice.
- [ ] A `vpn-installer audit` command that compares the live config with the
      generated plan.
- [ ] More distribution tests (Debian 12, Ubuntu 24.04) in CI.

## Considered

- WireGuard as a second transport.
- A read-only status dashboard that never serves private keys.
- Integration with external certificate authorities.

## Explicitly not planned

- A web panel that stores or serves client private keys.
- Automatically deleting or rewriting unrelated HAProxy sections.
- Disabling the firewall or flushing iptables during installation.
