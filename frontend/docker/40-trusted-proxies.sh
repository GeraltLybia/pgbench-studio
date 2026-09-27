#!/bin/sh
# Builds the real_ip and geo includes from TRUSTED_PROXIES (comma or space separated CIDRs).
set -eu
dir=/etc/nginx/trusted
mkdir -p "$dir"
: > "$dir/realip.conf"
: > "$dir/geo.conf"
for cidr in $(echo "${TRUSTED_PROXIES:-}" | tr ',' ' '); do
    case "$cidr" in
        *[!0-9a-fA-F:./]*) echo "40-trusted-proxies: invalid address '$cidr'" >&2; exit 1 ;;
    esac
    echo "set_real_ip_from $cidr;" >> "$dir/realip.conf"
    echo "$cidr 1;" >> "$dir/geo.conf"
done
echo "40-trusted-proxies: trusted balancers: ${TRUSTED_PROXIES:-<none>}"
