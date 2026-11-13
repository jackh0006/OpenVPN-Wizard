# FAQ

### Does this hide my VPN from my ISP?

It encrypts the connection and runs on TCP/443, so it looks like HTTPS at the
port level. A determined DPI system that blocks unknown protocols can still
identify OpenVPN. The optional VLESS/Reality path is the stronger anti-DPI
option. No tool can honestly guarantee invisibility on every network.

### Which protocol should I choose, TCP or UDP?

* **TCP** is more likely to pass restrictive networks and can share 443 with
  HAProxy. It can be slower on lossy links because of TCP-over-TCP.
* **UDP** is faster and lower latency, but some networks block it. It binds
  the public port directly and does not use HAProxy.

### What does “locked” mean?

Locked profiles can only reach the private VPN subnet. They do not route
internet traffic through the VPS, do not receive pushed DNS, and the VPS adds
no NAT rules. Use it for private services or to avoid acting as an exit node.

### Do I need a domain?

No. IP mode works and is the default. A domain is useful if you later enable
VLESS/Reality or want a human-readable endpoint.

### Do I need three domains?

No. VLESS/Reality is optional and disabled by default. OpenVPN needs only the
server IP/domain and one port.

### Can several users share one profile?

Technically yes, but don’t. Each user gets a unique certificate so one person
can be revoked independently. Sharing breaks that and makes attribution
impossible.

### Where are the passwords?

In `/root/openvpn-wizard-credentials.txt` (mode 600) after install, and shown
once in the wizard. The database stores only PBKDF2 hashes. If the file is
lost, set a new password with `vpn-installer manage`.

### Does uninstall delete my certificates?

Only with `--purge`. The default uninstall stops the service, removes the
managed HAProxy block and the firewall rules it added, and leaves the
certificates/profiles/DB in place.

### Will it overwrite my existing HAProxy config?

No. It appends one marked block, validates the result, and restores the
previous file if validation or reload fails. It refuses to touch a port that
another frontend already owns.

### Will it disable IPv6 or reset my firewall?

No. It never disables IPv6, never runs `ufw reset`, and never flushes iptables.
Free profiles push `block-ipv6` to clients instead.

### Does it work on ARM?

Yes, the Python code and packages support arm64. The test matrix runs on
Ubuntu 24.04; the packages come from the distribution.

### Does it work on Debian?

Yes, Debian 12 is supported. Ubuntu 22.04/24.04 is the primary target.

### How do I update?

```bash
sudo bash install.sh      # updates the source and reinstalls
sudo vpn-installer install
```

Or from a git checkout: `git pull && sudo pip install -e . && sudo vpn-installer install`.
Always run `vpn-installer plan` first if you changed modes.

### What if a profile stops working after an update?

Re-download it. v2 uses standard `tls-crypt`; v1 `tls-crypt-v2` profiles are
not compatible with the v2 server. See `docs/UPGRADING.md`.

### Is there a web UI?

No. A web panel that serves private keys is an unnecessary risk. The CLI and
the one-time HTTPS download server cover the practical cases.
