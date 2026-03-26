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

import argparse
import importlib

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Run a WeApRous app on host:port")
    p.add_argument("--module", required=True, help="Python module path that exposes `app` (e.g. apps.auth_app)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, required=True)
    args = p.parse_args()

    mod = importlib.import_module(args.module)
    app = getattr(mod, "app", None)
    if app is None:
        raise SystemExit(f"Module {args.module} does not expose `app`")

    app.prepare_address(args.host, args.port)
    app.run()



