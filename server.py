#!/usr/bin/env python3

# NAT hole punching server. This runs on the machine a service behind a NAT is running on, connects to a
# public reachable broker, and waits to receive hole punching requests as the broker receives requests
# from clients.

import argparse
import asyncio
from websockets.asyncio.client import connect, ClientConnection
import json
import socket
from sys import argv

# Protocol for UDP handling
class ServerProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        if data == b"|keepalive|":
            # Always update with the most recently received keepalive
            self.broker.update(addr[0], addr[1])
            return
        if data.startswith(b"|punchme|"):
            # Send a punch based on the observed client address and port
            _, reply_id = data.rsplit(b"|", 1)
            self.broker.request_punch(int(reply_id), addr[0], addr[1])

def punch_hole(client_address, client_port, local_port, message=b"Pew!"):
    with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as oneshot:
        oneshot.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        oneshot.bind(("::", local_port))
        oneshot.sendto(message, (client_address, client_port))

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("broker_addr", type=str)
    ap.add_argument("broker_port", type=int)
    ap.add_argument("service_port", type=int)
    args = ap.parse_args()

    # Periodically send a message to the broker to keep the NAT entry alive. The broker relies on this to update its
    # record of our external address and port.
    async def keepalive():
        while True:
            punch_hole(args.broker_addr, args.broker_port, args.service_port, b"|keepalive|")
            await asyncio.sleep(60)
    asyncio.create_task(keepalive())

    # Create a control channel, a websocket TCP connection to the broker
    async for websocket in connect(f'ws://[{args.broker_addr}]:{args.broker_port}'):
        # Avoid accidental DDoS
        await asyncio.sleep(.1)
        # Connect to broker
        await websocket.send(json.dumps({"new": "server"}))
        # Check if the connection was successful
        response = await websocket.recv()
        match json.loads(response)['result']:
            case "ok":
                pass
            case _:
                raise Exception("Connection failed: " + response)
 
        # Wait for the broker to make requests of us
        async for message in websocket:
            data = json.loads(message)
            match data['request']:
                case "punch":
                    # Punch a new NAT hole
                    await punch_hole(data['client_address'], data['client_port'], args.service_port)

                    # Notify the broker that the connection is ready
                    await websocket.send(json.dumps({"result": "ok"}))
                case _:
                    # Unknown request
                    await websocket.send(json.dumps({"result": "error"}))
                    await websocket.close()

if __name__ == "__main__":
    asyncio.run(main())
