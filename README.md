
This is a simple exploration of NAT traversal. The aim is to allow a NAT-oblivious client to connect to a service,
even when the service is behind a NAT, with minimal changes to the service. NAT punching is normally done by libraries
within a process designed to be fully aware of NAT punching. It is done this way for good reason, but it's surprising
how far you can get before compromises.

Key components:

- [Service](stub-service.py): Stands in for a simple service for clients to connect to. This listens on a simple UDP
  socket, and is oblivious to the NAT punching we want to perform. For simplicity, it also sets `SO_REUSEPORT` on bind
  with the `--reuse-port` flag, but a fully oblivious process can have this forced via `LD_PRELOAD` with a library
  built from [force_reuseport.c](force_reuseport.c). This isn't strictly necessary, but it's much friendlier on the
  number of entries which need to be made in the NAT table, and saves needing to locally proxy the service (though
  `splice(2)` is very efficient, and python 3.10+ even provides native access via `os`).
- [Client](stub-client.py): Stands in for a simple client of the service. This connects to the service, and is
  oblivious to the NAT punching we want to perform, beyond being given a normal address and port.
- [Server](server.py): A NAT punching service, running on the server that clients ultimately want connect to.
- [Client](client.py): A NAT punching client, on the other side of the network. The client may also be behind a NAT.
  It will retry a few times if nothing gets through, which is reasonable to expect from a client given UDP is an
  unreliable protocol.
- [Broker](broker.py): The broker that helps endpoints connect to each other. Must be directly accessible.

[testbed.sh](testbed.sh) is a script that sets up a lightweight test environment using linux network namespaces.
It creates an environment separating the client, server, and broker, and handles intermediate namespaces providing
NAT and bridging functionality. In `auto` mode, this simply tests the components. In `interactive` mode, it runs
`tmux` and sets up panes for each component, allowing you to experiment with network configuration or run custom
commands.

Testbed namespace layout:
```
                         ns-broker
                             |
                         ns-global
                          /     \
ns-server -- ns-server-nat       ns-client-nat -- ns-client
```
