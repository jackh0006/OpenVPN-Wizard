# Upgrading from v1 to v2

## What changed

v1 had two installers: a Python TUI and a monolithic `install.sh` with
hardcoded credentials. Both could rewrite `/etc/haproxy/haproxy.cfg`, and the
Python version served private keys from a plain HTTP directory. v2 removes all
of that.

| Area | v1 | v2 |
|---|---|---|
| HAProxy | full file rewrite | append-only marked block, backup + rollback |
| Profiles | predictable HTTP URL | SSH/SCP or one-time token HTTPS |
| IP selection | auto-detected only | explicit IP + domain/IP endpoint |
| Transport | TCP only | TCP or UDP |
| Auth | password + cert | password + cert **or** cert only |
| Access | full tunnel only | free **or** locked |
| Users | one by default | 1–50 unique profiles at install time |
| Password hashing | `crypt` (removed in Python 3.13) | PBKDF2-HMAC-SHA256 |
| IPv6 | disabled system-wide | left alone; clients told to block it |
| CRL | empty placeholder in some paths | real generated CRL, verified |
| Cipher policy | TLS 1.3 only | TLS 1.2+ with TLS 1.3 when available |

## Before upgrading

1. Copy existing profiles somewhere safe.
2. Note the current HAProxy config:
   ```bash
   sudo cp -a /etc/haproxy/haproxy.cfg /root/haproxy.cfg.before-v2
   ```
3. Check which PKI path you have:
   ```bash
   ls /etc/openvpn/pki /etc/openvpn/easy-rsa/pki 2>/dev/null
   ```

## Upgrade

```bash
git -C /opt/openvpn-wizard-src pull   # or re-clone
sudo bash install.sh
```

or, if `vpn-installer` is already installed:

```bash
sudo pip install -e .   # in the source checkout, or use install.sh
sudo vpn-installer install
```

The installer:

* reuses a healthy PKI at `/etc/openvpn/pki` or
  `/etc/openvpn/easy-rsa/pki`;
* keeps a timestamped backup of the old HAProxy file;
* detects the exact v1 HAProxy layout and migrates it to the append-only
  layout (the backup path is printed);
* creates new standard `tls-crypt` profiles for the users you configure.

## After upgrading

1. Download the new profiles and test on a phone using mobile data.
2. Keep the old profiles until the new ones work.
3. If a device still uses a v1 `tls-crypt-v2` profile, it will not work with
   the v2 server. Re-download that user’s profile.
4. Run:
   ```bash
   sudo vpn-installer validate
   sudo vpn-installer doctor
   ```

## Rollback

The old HAProxy file is in `/var/backups/vpn-installer/`. To restore it:

```bash
sudo cp /var/backups/vpn-installer/haproxy.cfg.* /etc/haproxy/haproxy.cfg
sudo haproxy -c -f /etc/haproxy/haproxy.cfg && sudo systemctl reload-or-restart haproxy
```

The installer never deletes the old PKI; it either reuses it or moves an
unusable directory aside with a timestamp suffix.
