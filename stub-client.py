#!/usr/bin/env python3

# Dumb, network agnostic client. Attempt to connect directly to the address and port provided.

import argparse
import sys
import socket

def make_socket(reuse_port=False):
    sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    # Hahaha, good luck finding clients that let you do something like this
    if reuse_port:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.settimeout(.4)
    return sock

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("address", type=str)
    ap.add_argument("port", type=int)
    ap.add_argument("--fresh_retry", action="store_true")
    ap.add_argument("--reuse-port", action="store_true")
    args = ap.parse_args()

    # Try a bunch of times. UDP is unreliable, so it's not too unreasonable to expect a client to have something
    # like this.
    try:
        sock = make_socket(args.reuse_port)
        for _ in range(4):
            try:
                print(f"Attempting to reach server at {args.address}:{args.port}")
                sock.sendto(b"Hello, server!", (args.address, args.port))
                data, addr = sock.recvfrom(1024)
                print("Client: Connection OK")
                sys.exit(0)
            except socket.timeout:
                print("Client: No reply")
            # Hope that the client doesn't create a fresh socket every time, because otherwise we're out of luck, as
            # this can demonstrate
            if args.fresh_retry:
                sock.close()
                sock = make_socket(args.reuse_port)
        sys.exit(1)
    finally:
        sock.close()

if __name__ == "__main__":
    main()
