#!/usr/bin/env python3

# NAT hole punching broker. This runs on a public reachable server, and accepts connections from all servers and
# clients.

import argparse
import asyncio
import websockets
import json
from sys import argv

# Protocol for UDP handling
class BrokerProtocol(asyncio.Protocol):
    def __init__(self, broker: 'Broker'):
        self.broker = broker

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

class Broker(object):
    def __init__(self):
        # This is a dict for practical purposes, mapping remote addresses to websockets.
        # In the real world, the external address in one connection is not guaranteed to be the same as the external
        # address from another connection. So while this is helpful for troubleshooting or inspection, it's not
        # something we can rely on.
        self._connected_servers = {}
        # Clients are just stored by an incrementing sequential ID
        self._connected_clients = {}
        self._next_connected_client_id = 0
        # Keep track of data on the UDP channel, and how old this information is
        self._last_update = None
        self._server_external_address = None
        self._server_external_port = 0

    def update(self, address, port):
        self._last_update = asyncio.get_event_loop().time()
        self._server_external_address = address
        self._server_external_port = port

    async def server_handler(self, websocket):
        await websocket.send(json.dumps({"result": "ok"}))
        try:
            self._connected_servers[websocket.remote_address] = websocket
            async for message in websocket:
                match message.request:
                    case _:
                        # Unknown request
                        await websocket.send(json.dumps({"result": "error", "why": "unknown request"}))
        finally:
            del self._connected_servers[websocket.remote_address]

    def request_punch(self, reply_id, address, port):
        # If the client that requested the punch isn't connected, don't bother
        if reply_id not in self._connected_clients:
            return
        # Ask any connected servers to punch
        for server in self._connected_servers.values():
            asyncio.create_task(self._request_punch(server, reply_id, address, port))

    async def _request_punch(self, server, reply_id, address, port):
        await server.send(json.dumps({
            "request": "punch",
            "client_address": address,
            "client_port": port
        }))
        # See what the server says
        response = await server.recv()
        # If the client that requested the punch is still connected, notify them
        if reply_id not in self._connected_clients:
            return
        client = self._connected_clients[reply_id]
        # Forward the server's reply verbatim
        await client.send(response)

    async def client_handler(self, websocket):
        id = self._next_connected_client_id
        self._next_connected_client_id += 1
        await websocket.send(json.dumps({"result": "ok", "id": id}))
        try:
            self._connected_clients[id] = websocket
            async for message in websocket:
                print("Got message (client): ", message)
                data = json.loads(message)
                match data['request']:
                    case "info":
                        # If we haven't heard from the server yet (or in a while), we can't return usable information
                        if self._last_update is None or asyncio.get_event_loop().time() - self._last_update > 60:
                            await websocket.send(json.dumps({"result": "error", "why": "no servers available"}))
                            continue
                        # Return the server's external address and port
                        await websocket.send(json.dumps({
                            "result": "ok",
                            "address": self._server_external_address,
                            "port": self._server_external_port
                        }))
                    case _:
                        # Unknown request
                        await websocket.send(json.dumps({"result": "error", "why": "unknown request"}))
                        await websocket.close()
        finally:
            del self._connected_clients[id]

    async def handler(self, websocket):
        async for message in websocket:
            print("Got message (new): ", message)
            match json.loads(message)['new']:
                case "client":
                    # Connection identifies as a client
                    # Delegate to client handler
                    await self.client_handler(websocket)
                case "server":
                    # Connection identifies as a server
                    # Delegate to server handler
                    await self.server_handler(websocket)
                case _:
                    # Unknown connection type
                    await websocket.send(json.dumps({"result": "error", "why": "unknown connection type"}))
                    await websocket.close()

    async def receive_keepalives(self, broker_port):
        return await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: BrokerProtocol(self),
            local_addr=("::", broker_port),
            reuse_port=True
        )

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", type=int)
    args = ap.parse_args()

    addr = "::"

    broker = Broker()
    # Listen on TCP for a reliable websocket connection, and on UDP for keepalives from the actual NAT punched flow
    async with websockets.serve(broker.handler, addr, args.port):
        asyncio.create_task(broker.receive_keepalives(args.port))
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
