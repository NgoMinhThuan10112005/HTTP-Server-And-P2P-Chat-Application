#
# Copyright (C) 2025 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# WeApRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#

"""
daemon.backend
~~~~~~~~~~~~~~~~~

This module provides a backend object to manage and persist backend daemon. 
It implements a basic backend server using Python's socket and threading libraries.
It supports handling multiple client connections concurrently and routing requests using a
custom HTTP adapter.

Requirements:
--------------
- socket: provide socket networking interface.
- threading: Enables concurrent client handling via threads.
- response: response utilities.
- httpadapter: the class for handling HTTP requests.
- CaseInsensitiveDict: provides dictionary for managing headers or routes.


Notes:
------
- The server create daemon threads for client handling.
- The current implementation error handling is minimal, socket errors are printed to the console.
- The actual request processing is delegated to the HttpAdapter class.

Usage Example:
--------------
>>> create_backend("127.0.0.1", 9000, routes={})

"""

# daemon/backend.py
# -----------------------------------------------------------------------------
# Minimal TCP backend that accepts sockets and serves each with HttpAdapter
# -----------------------------------------------------------------------------
import socket
import threading

from .httpadapter import HttpAdapter

def handle_client(ip, port, conn, addr, routes):
    try:
        daemon = HttpAdapter(ip, port, conn, addr, routes)
        # IMPORTANT: our HttpAdapter signature is (conn, addr, routes)
        daemon.handle_client(conn, addr, routes)
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        print(f"[Backend] client handler error from {addr}: {e}")

def run_backend(ip: str, port: int, routes: dict):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((ip, port))
    srv.listen(64)
    print(f"[Backend] Listening on port {port}")
    if routes != {}:
            print(f"[Backend] route settings {routes}")

    try:
        while True:
            conn, addr = srv.accept()
            t = threading.Thread(
                target=handle_client, args=(ip, port, conn, addr, routes), daemon=False
            )
            t.start()
    finally:
        srv.close()

def create_backend(ip: str, port: int, routes: dict):
    run_backend(ip, port, routes)