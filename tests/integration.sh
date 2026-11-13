#!/usr/bin/env bash
# Post-install integration checks for OpenVPN Wizard v2.
# Run as root on the VPS: sudo tests/integration.sh

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
TESTS=0; PASSED=0
pass() { echo -e "${GREEN}[PASS]${NC} $*"; PASSED=$((PASSED + 1)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
run() {
    local name="$1"; shift
    TESTS=$((TESTS + 1))
    if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name"; fi
}

echo "OpenVPN Wizard v2 - integration checks"
echo "======================================"

run "OpenVPN config exists" test -s /etc/openvpn/server.conf
run "CA exists" test -s /etc/openvpn/ca.crt
run "Server cert exists" test -s /etc/openvpn/server.crt
run "Server key exists" test -s /etc/openvpn/server.key
run "TLS-crypt key exists" test -s /etc/openvpn/ta.key
run "CRL is valid" bash -c "grep -q 'BEGIN X509 CRL' /etc/openvpn/crl.pem"
run "Profiles directory is 700" bash -c "[[ \$(stat -c '%a' /etc/openvpn/clients) == '700' ]]"
run "At least one profile" bash -c "ls /etc/openvpn/clients/*.ovpn >/dev/null"

for profile in /etc/openvpn/clients/*.ovpn; do
    run "Profile $(basename "$profile") mode 600" bash -c "[[ \$(stat -c '%a' '$profile') == '600' ]]"
    run "Profile $(basename "$profile") has tls-crypt" grep -q '^<tls-crypt>' "$profile"
    run "Profile $(basename "$profile") has remote" grep -q '^remote ' "$profile"
done

run "OpenVPN service active" systemctl is-active --quiet openvpn@server
run "No compression in server config" bash -c "! grep -Eq '^(comp-lzo|compress)' /etc/openvpn/server.conf"
run "No plaintext web profile directory" test ! -d /var/www/vpn-profiles

if grep -q '^plugin .*openvpn-plugin-auth-pam.so' /etc/openvpn/server.conf; then
    run "PAM plugin present" test -f "$(grep '^plugin ' /etc/openvpn/server.conf | awk '{print $2}')"
fi

if command -v vpn-installer >/dev/null 2>&1; then
    run "vpn-installer doctor" vpn-installer doctor
    run "vpn-installer validate" vpn-installer validate
fi

echo
echo "Results: $PASSED/$TESTS"
[[ $PASSED -eq $TESTS ]]
