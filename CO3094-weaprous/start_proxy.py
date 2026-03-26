# reverse_proxy.py
#
# Copyright (C) 2025 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course,
# and is released under the "MIT License Agreement". Please see the LICENSE
# file that should have been included as part of this package.
#
# WeApRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#


# start_proxy.py
# -----------------------------------------------------------------------------
# Entry point: parses config/proxy.conf, builds routing policy, launches proxy.
# -----------------------------------------------------------------------------

import argparse
import re
from itertools import cycle
from daemon import create_proxy


class RoundRobinPool:
    """Thread-safe round-robin over a list of (host, port) tuples."""
    def __init__(self, backends):
        self._backs = list(backends) if backends else [("127.0.0.1", 9)]
        self._it = cycle(self._backs)
        # If extremely high contention, add a Lock; for per-conn threads this is usually fine.
        # self._lock = threading.Lock()

    def pick(self):
        # with self._lock: return next(self._it)
        return next(self._it)


def parse_virtual_hosts(config_file: str):
    """
    Parse proxy.conf host blocks:
      host "NAME" {
          proxy_set_header Host $host;      # optional
          proxy_pass http://127.0.0.1:9001; # one or more
          dist_policy round-robin            # optional (only round-robin used here)
      }
    Returns raw map:
      NAME -> { 'proxy_pass': ['http://ip:port', ...],
                'preserve_host': bool,
                'policy': 'round-robin' }
    """
    with open(config_file, "r", encoding="utf-8") as f:
        text = f.read()

    blocks = re.findall(r'host\s+"([^"]+)"\s*\{(.*?)\}', text, re.DOTALL)
    routes = {}
    for host, block in blocks:
        proxy_passes = re.findall(r'proxy_pass\s+http://([^\s;]+);', block)
        keep_host = re.search(r'proxy_set_header\s+Host\s+\$host\s*;', block) is not None
        policy_m = re.search(r'dist_policy\s+([-\w]+)', block)
        policy = policy_m.group(1) if policy_m else "round-robin"

        routes[host] = {
            "proxy_pass": [f"http://{p}" for p in proxy_passes],
            "preserve_host": keep_host,
            "policy": policy,
        }

    # debug print
    for k, v in routes.items():
        print("[config]", k, "=>", v)
    return routes


def build_policy(raw_routes: dict):
    """
    Compile raw config to the normalized map consumed by daemon/proxy.py:
      host -> { 'pool': RoundRobinPool([(ip,port), ...]),
                'preserve_host': bool,
                'policy': 'round-robin' }
    """
    canon = {}
    for host, conf in (raw_routes or {}).items():
        backs = []
        for url in conf.get("proxy_pass", []):
            val = url.split("://", 1)[-1]
            h, p = val.split(":", 1)
            backs.append((h.strip(), int(p)))
        if not backs:
            backs = [("127.0.0.1", 9)]  # cause 502 if used

        canon[host] = {
            "pool": RoundRobinPool(backs),
            "preserve_host": bool(conf.get("preserve_host", False)),
            "policy": conf.get("policy", "round-robin"),
        }
    return canon


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="Proxy", description="Reverse proxy daemon")
    parser.add_argument("--server-ip", default="0.0.0.0")
    parser.add_argument("--server-port", type=int, default=8080)
    parser.add_argument("--config", default="config/proxy.conf")
    
    args = parser.parse_args()
    print(f"Using config file: {args.config}")

    raw_routes = parse_virtual_hosts(args.config)
    routes = build_policy(raw_routes)
    create_proxy(args.server_ip, args.server_port, routes)
