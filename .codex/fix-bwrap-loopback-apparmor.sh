#!/usr/bin/env bash
set -euo pipefail

profile=/etc/apparmor.d/bwrap-userns-restrict
template=/usr/share/apparmor/extra-profiles/bwrap-userns-restrict
diverted_template=${template}.distrib
backup=/etc/apparmor.d/bwrap-userns-restrict.codex-loopback.stock.bak

if (( EUID != 0 )); then
    exec sudo -- "$0" "$@"
fi
if [[ ! -f "$profile" || ( ! -f "$template" && ! -f "$diverted_template" ) ]]; then
    echo "missing AppArmor live profile or stock/diverted template" >&2
    echo "profile=$profile template=$template" >&2
    exit 1
fi

patch_profile() {
    local source=$1
    local destination=$2
    local temporary
    local deny_count
    local allow_count

    deny_count=$(grep -Fxc '  audit deny capability,' "$source" || true)
    allow_count=$(grep -Fxc '  allow capability net_admin,' "$source" || true)
    if [[ "$allow_count" == 1 && "$deny_count" == 0 ]]; then
        install -o root -g root -m 0644 "$source" "$destination"
        return
    fi
    if [[ "$allow_count" != 0 || "$deny_count" != 1 ]]; then
        echo "refusing unexpected bwrap profile shape: $source" >&2
        echo "deny_count=$deny_count allow_count=$allow_count" >&2
        exit 1
    fi
    temporary=$(mktemp /tmp/bwrap-userns-restrict.XXXXXX)
    awk '
        $0 == "  audit deny capability," {
            print "  # The sandbox child needs only CAP_NET_ADMIN to raise loopback."
            print "  allow capability net_admin,"
            next
        }
        { print }
    ' "$source" >"$temporary"
    install -o root -g root -m 0644 "$temporary" "$destination"
    rm -f "$temporary"
}

# apparmor-profiles ships this policy under /usr/share and aa-enforce copies it
# into /etc.  Divert the package-owned template so reinstalls/upgrades refresh
# only the .distrib copy instead of silently restoring the blanket deny.
if ! dpkg-divert --list "$template" | grep -Fq -- "$template"; then
    [[ -e "$backup" ]] || cp -a "$profile" "$backup"
    dpkg-divert --add --local --rename \
        --divert "$diverted_template" "$template"
fi

if [[ ! -f "$diverted_template" ]]; then
    echo "missing diverted stock template: $diverted_template" >&2
    exit 1
fi

patch_profile "$diverted_template" "$template"
patch_profile "$template" "$profile"

apparmor_parser -r "$profile"
sysctl -w kernel.unprivileged_userns_clone=1 >/dev/null

test_user=${SUDO_USER:-}
if [[ -z "$test_user" || "$test_user" == root ]]; then
    echo "run this script through sudo from the non-root Codex user" >&2
    exit 1
fi
sudo -u "$test_user" bwrap \
    --unshare-user --uid 0 --gid 0 --unshare-net \
    --ro-bind / / --dev /dev --proc /proc -- \
    python3 -c '
import socket
server = socket.socket()
server.bind(("127.0.0.1", 0))
server.listen(1)
client = socket.socket()
client.connect(server.getsockname())
peer, _ = server.accept()
client.sendall(b"ok")
assert peer.recv(2) == b"ok"
peer.sendall(b"yes")
assert client.recv(3) == b"yes"
'

echo "bubblewrap loopback capability verified for $test_user"
echo "persistent template diversion: $template -> $diverted_template"
echo "stock live-profile backup: $backup"
