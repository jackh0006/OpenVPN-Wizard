# Documentation index

| Document | Contents |
|---|---|
| [BEGINNER-GUIDE.md](BEGINNER-GUIDE.md) | Plain-English start-to-finish walkthrough |
| [INSTALL.md](INSTALL.md) | Requirements, bootstrap, interactive and dry-run install |
| [DOWNLOAD.md](DOWNLOAD.md) | SCP, Windows, Android, one-time HTTPS links |
| [SECURITY.md](SECURITY.md) | Threat model, cryptography, permissions, honest limits |
| [MANAGEMENT.md](MANAGEMENT.md) | Add/revoke/rotate users, database contents |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Port conflicts, service failures, DNS/IPv6, logs |
| [UPGRADING.md](UPGRADING.md) | v1 → v2 migration and rollback |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, data flow, design rules |
| [FAQ.md](FAQ.md) | Short answers to common questions |
| [COMPARISON.md](COMPARISON.md) | Comparison and limitations |
| [TERMUX.md](TERMUX.md) | Android profile download |
| [LIVE-VERIFICATION.md](LIVE-VERIFICATION.md) | Read-only proof against a working Ubuntu 22.04 VPS |
| [../DONATIONS.md](../DONATIONS.md) | Optional crypto donation addresses |
| [../README.md](../README.md) | Main overview and quick start |

## Five commands to remember

```bash
sudo vpn-installer install            # deploy / re-apply configuration
sudo vpn-installer plan -o ./plan     # render everything without changes
sudo vpn-installer manage             # users, keys, profiles
sudo vpn-installer doctor             # diagnose with exact fixes
sudo vpn-installer download NAME      # show secure download options
```
