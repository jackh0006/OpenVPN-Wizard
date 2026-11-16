# OpenVPN Wizard v2.2.2 — profile compatibility and terminal usability

This patch release makes the installer more dependable when launched from a
one-line curl command and makes generated default TCP profiles follow the
tested reference layout exactly outside their generated certificate material.

## Highlights

- The installer restores interactive terminal input after `curl | sudo bash`.
  In a non-interactive environment it exits safely and gives the exact command
  to run later.
- Every default TCP profile has the reference OpenVPN directive order,
  authentication prompt, TLS policy, buffer settings, TCP settings and
  `tls-crypt` block placement.
- Multi-profile generation is tested with five independent users. Each gets a
  distinct certificate and private key; passwords are never embedded in a
  profile.
- The terminal UI is shorter and clearer in SSH and phone-terminal windows.

## Verification

- 55 automated tests pass.
- 2 integration tests remain intentionally skipped unless OpenVPN and HAProxy
  are installed on a real host.
