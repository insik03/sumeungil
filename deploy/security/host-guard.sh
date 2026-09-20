#!/bin/sh
# Narrow host-input guard. Leaves SSH/HTTP/HTTPS and Docker forwarding intact.
set -eu
case "${1:-}" in apply|remove|check) ;; *) echo 'Usage: host-guard.sh apply|remove|check' >&2; exit 2 ;; esac
for fw in iptables ip6tables; do
  command -v "$fw" >/dev/null
  case "$1" in
    apply)
      "$fw" -w -N SUMEUNGIL-HOST 2>/dev/null || "$fw" -w -S SUMEUNGIL-HOST >/dev/null
      # Build the dedicated chain before attaching; never flush INPUT/DOCKER.
      "$fw" -w -C SUMEUNGIL-HOST -i lo -j RETURN 2>/dev/null || "$fw" -w -I SUMEUNGIL-HOST 1 -i lo -j RETURN
      for proto in tcp udp; do
        "$fw" -w -C SUMEUNGIL-HOST -p "$proto" -m multiport --dports 111,5355 -j DROP 2>/dev/null || \
          "$fw" -w -A SUMEUNGIL-HOST -p "$proto" -m multiport --dports 111,5355 -j DROP
      done
      "$fw" -w -C INPUT -j SUMEUNGIL-HOST 2>/dev/null || "$fw" -w -I INPUT 1 -j SUMEUNGIL-HOST
      ;;
    remove)
      if "$fw" -w -C INPUT -j SUMEUNGIL-HOST 2>/dev/null; then "$fw" -w -D INPUT -j SUMEUNGIL-HOST; fi
      if "$fw" -w -S SUMEUNGIL-HOST >/dev/null 2>&1; then
        "$fw" -w -F SUMEUNGIL-HOST
        "$fw" -w -X SUMEUNGIL-HOST
      fi
      ;;
    check)
      "$fw" -w -C INPUT -j SUMEUNGIL-HOST
      "$fw" -w -C SUMEUNGIL-HOST -i lo -j RETURN
      for proto in tcp udp; do "$fw" -w -C SUMEUNGIL-HOST -p "$proto" -m multiport --dports 111,5355 -j DROP; done
      ;;
  esac
done
