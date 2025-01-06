#!/usr/bin/env python3

# Dumb, network agnostic server. Directly listens and accepts on the port provided.

import argparse
import socket

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", type=int)
    ap.add_argument("--reuse-port", action="store_true")
    args = ap.parse_args()

    print(f"Listening on port {args.port}...")
    sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    # Give us the option of playing nicely and avoiding LD_PRELOAD shenanigans.
    # This does give us the option of using a kinda-aware server that can use SO_REUSEPORT itself, or whether we want
    # to check that the LD_PRELOAD hack works.
    if (args.reuse_port):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind(("::", args.port))

    while True:
        data, addr = sock.recvfrom(1024)
        print("Server received datagram!")
        # Reply
        sock.sendto(b"Hello, client!", addr)

if __name__ == "__main__":
    main()
