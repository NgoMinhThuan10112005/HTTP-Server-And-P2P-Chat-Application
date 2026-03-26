#!/bin/bash

# Start the db
python3 db/app_state.py &

# Start auth 
python3 start_backend.py --module apps.auth_app --host 127.0.0.1 --port 9001 &
python3 start_backend.py --module apps.auth_app --host 127.0.0.1 --port 9002 &
python3 start_backend.py --module apps.auth_app --host 127.0.0.1 --port 9003 &

# Start p2p
python3 start_backend.py --module apps.p2p_app --host 127.0.0.1 --port 9004 &
python3 start_backend.py --module apps.p2p_app --host 127.0.0.1 --port 9005 &
python3 start_backend.py --module apps.p2p_app --host 127.0.0.1 --port 9006 &

# Start the proxy
python3 start_proxy.py --server-ip 127.0.0.1 --server-port 8080 --config config/proxy.conf &

wait
