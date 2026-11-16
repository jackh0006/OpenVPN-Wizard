# OpenVPN Wizard v2.2.3 — reliable bootstrap-to-wizard handoff

This patch fixes the final handoff in the one-line installer.

- Interactive use through `curl | sudo bash` now reconnects standard input,
  output, and error to the controlling terminal before the wizard starts.
- The bootstrap prints `Launching the setup wizard...` immediately before the
  handoff. If no interactive terminal is available, it exits safely and tells
  the operator to run `sudo vpn-installer install` later.
- Existing virtual environments now force-reinstall the checked-out package,
  preventing stale Python files from surviving an update.
- Non-interactive and dry-run commands remain suitable for automation and do
  not attempt to acquire a terminal.
