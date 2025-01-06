#!/usr/bin/env python3

# NAT hole punching client.
# Stages:
# - Connect to a public reachable broker.
# - Fetches the service's last known external address and port. It is assumes that the external address and port as seen
#   by the broker is the same as the external address and port as seen by the service.
# - Present this address and port to the user.
# - Watch local network connections until we see a connection to the address and port we provided. Assume that this is
#   the connection made by the service client.
# - Send the local port used by the service client to the broker. The broker then sends this to the server, and asks
#   the server to punch a hole through to the client.
# - The server punches a hole through to the client. Depending on NAT type, the client can now communicate with the
#   server.
# - The server indicates that it has sent its punch, and the broker forwards this to the client to indicate success.

# Different types of NAT can succeed or fail at different stages:
# - A NAT which only stores (protocol, internal address, internal port) as the mapping to its allocated
#   (external address, external port) may succeed without the server needing to make a dedicated punch towards the
#   client, as the regular keepalives it sends to the broker will be enough.
# - A NAT which additionally tracks which destinations the internal address has sent packets to, but still uses the
#   same (protocol, internal address, internal port) mapping, will require the server to make a dedicated punch towards
#   the client.
# - A NAT which uses a full (protocol, internal address, internal port, destination address, destination port) mapping
#   will not work with this system, as it will allocate a unique (external address, external port) for each
#   destination, even from the same port. Real libraries can use a mix of heuristics and scanning to guess the external
#   port, but it's beyond the scope of what is interesting to explore here. Symmetric NAT is *hard* to punch through.

import argparse
import asyncio
import websockets
import json
import psutil
import socket
from sys import stderr

async def watch_for_outbound_connections(service_addr, service_port):
    while True:
        await asyncio.sleep(1)
        # Poll currently open connections to see if any match this description
        for conn in psutil.net_connections(kind='udp6'):
            # Check if the connection is to the service
            if conn.raddr != (service_addr, service_port):
                continue
            # We have a match
            return conn.lport

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("broker_addr", type=str)
    ap.add_argument("broker_port", type=int)
    args = ap.parse_args()

    async with websockets.connect(f'ws://[{args.broker_addr}]:{args.broker_port}') as websocket:
        # Connect the broker, get acknowledged as a client
        await websocket.send(json.dumps({"new": "client"}))
        response = await websocket.recv()
        data = json.loads(response)
        match data['result']:
            case "ok":
                id = data['id']
                pass
            case _:
                raise Exception("Connection failed: " + response)

        # Ask the broker what the server's details are, from its perspective
        await websocket.send(json.dumps({"request": "info"}))
        response = await websocket.recv()
        data = json.loads(response)
        match data['result']:
            case 'ok':
                service_addr, service_port = data['address'], data['port']
            case _:
                raise Exception("Unknown failure: " + response)
        # Present this information to the user. Eventually, the user will have a local process connect to this
        # address and port.
        print(f"{service_addr}:{service_port}")

        # When they do, retrieve the local port allocated and race to punch a hole to it.
        # Realistically, if we're running anything which is this intrusive, we should just be running ahead and making
        # the connection ourselves, and providing a proxied connection on localhost for the service client to connect
        # to. This is a fun digression, though.
        print("Now waiting for the user to make a connection to the address and port we provided.", file=stderr)
        local_port = await watch_for_outbound_connections(service_addr, service_port)

        # Use this local port to ask the broker what our address looks like from the outside.
        # We must make this request over UDP, as the broker will use the source address and port to determine what our
        # external address and port are, and there is no guarantee that NAT will map a UDP connection the same way it
        # maps our TCP connection.

        while True:
            # XXX: Here's a sticking point. The service client is unlikely to set SO_REUSEPORT, so setting the local
            # port will likely fail. We can't wait for the service client to give up, as it is extremely unlikely that
            # the system will give it the same local port again.
            # We could forge packets with the correct source port, but this requires root (or more specifically,
            # CAP_NET_RAW) on the client system. If we're going to require elevated privileges, we might as well
            # perform a full MITM using IP_TRANSPARENT.

            # If the client service allows specifying the local port, this also becomes much easier, as we can perform
            # the punch ourselves and then tell the client what local port we used. This is not common functionality,
            # and it's also not that different from what is traditionally done with a NAT punching aware library and
            # process.
            with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as broker_request:
                # On the off chance that the client used SO_REUSEPORT, this is much simpler
                broker_request.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                # TODO: Something spicier when this fails.
                broker_request.bind(("::", local_port))
                data = b'|punchme|' + str(id).encode()
                broker_request.sendto(data, (args.broker_addr, args.broker_port))
                # Receive a response on the websocket
                try:
                    async with asyncio.timeout(2):
                        response = await websocket.recv()
                        data = json.loads(response)
                        match data['result']:
                            case "ok":
                                print("Punch successful!", file=stderr)
                                break
                            case _:
                                print("Punch failed: " + response, file=stderr)
                        break
                except TimeoutError:
                    continue

if __name__ == "__main__":
    asyncio.run(main())
