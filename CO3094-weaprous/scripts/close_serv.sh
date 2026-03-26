#!/bin/bash

echo "Stopping all app services and proxy..."

pkill -f "python3 start_backend.py"

pkill -f "python3 start_proxy.py"

pkill -f "python3 db/app_state.py"

echo "All services have been stopped."
