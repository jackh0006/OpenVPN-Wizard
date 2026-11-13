# How v2 compares

| Feature | OpenVPN Wizard v2 | Typical “one-click” scripts | Commercial VPN |
|---|---|---|---|
| You own the server | ✅ | ✅ | ❌ |
| Non-destructive HAProxy merge | ✅ append-only + backup + rollback | ❌ often rewrites the file | N/A |
| Unique cert/key per user | ✅ | Sometimes | N/A |
| Certificate + password or cert-only | ✅ both | Usually one | N/A |
| Free vs locked access | ✅ | Rarely | N/A |
| TCP and UDP | ✅ | Usually one | N/A |
| Valid CRL and revocation | ✅ | Often missing/empty | N/A |
| Plain-HTTP key delivery | ❌ never | Sometimes | N/A |
| Per-install dry run | ✅ `vpn-installer plan` | ❌ | N/A |
| Diagnostics with fixes | ✅ `doctor` | ❌ | ❌ |
| Tests in CI | ✅ real config parsing | Rarely | N/A |
| Open source | ✅ MIT | Varies | ❌ |
| Monthly fee | $0 + VPS | $0 + VPS | $5–15 |

## Honest limitations

* Not a magic DPI-proof tunnel. TCP/443 + `tls-crypt` is good, but an active
  DPI system can still block unknown protocols. Optional VLESS/Reality is the
  stronger option.
* TCP-over-TCP can be slower on lossy links; choose UDP when possible.
* The VPS provider can observe metadata and terminates traffic.
* You are responsible for DNS records if you use domain mode.

## What “best” means here

Not the longest feature list — the fewest ways to silently break an existing
server. That is why v2 appends instead of overwriting, validates before
reloading, keeps timestamped backups, and prints an exact fix when it refuses
to continue.
