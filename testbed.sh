#!/bin/bash

set -ex

# This script creates six network namespaces:
# - ns-server
#   - [fc00::d034:200]
# - ns-server-nat
#   - [fc00::d034:1] (to ns-server)
#   - [fc00::3145:66] (to ns-global)
# - ns-broker
#   - [fc00::3145:50]
# - ns-client-nat
#   - [fc00::3145:77] (to ns-global)
#   - [fc00::34d1:1] (to ns-client)
# - ns-client
#   - [fc00::34d1:200]
#
# Connected as follows:
#                          ns-broker
#                              |
#                          ns-global
#                           /     \
# ns-server -- ns-server-nat       ns-client-nat -- ns-client
#
# The script also configures NAT on the ns-server-nat and ns-client-nat
# namespaces.

setup() {
    # Create the namespaces
    ip netns add ns-server
    ip netns add ns-server-nat
    ip netns add ns-global
    ip netns add ns-broker
    ip netns add ns-client-nat
    ip netns add ns-client

    # Add the bridge on ns-global
    ip link add name ns-bridge netns ns-global type bridge 
    ip netns exec ns-global ip link set ns-bridge up

    # Create the veth pairs
    # Server and its NAT
    ip link add veth-nat netns ns-server type veth peer veth-server netns ns-server-nat
    # Global and the broker and NATs
    ip link add veth-global netns ns-server-nat type veth peer veth-server-nat netns ns-global
    ip link add veth-broker netns ns-global type veth peer veth-global netns ns-broker
    ip link add veth-client-nat netns ns-global type veth peer veth-global netns ns-client-nat
    # Client and its NAT
    ip link add veth-client netns ns-client-nat type veth peer veth-nat netns ns-client

    # Attach the veth pairs in ns-global to the bridge
    ip netns exec ns-global ip link set veth-server-nat master ns-bridge
    ip netns exec ns-global ip link set veth-broker master ns-bridge
    ip netns exec ns-global ip link set veth-client-nat master ns-bridge

    # Configure the veth pairs
    ip netns exec ns-server ip addr add fc00::d034:200/112 dev veth-nat
    ip netns exec ns-server-nat ip addr add fc00::d034:1/112 dev veth-server
    ip netns exec ns-server-nat ip addr add fc00::3145:66/112 dev veth-global
    ip netns exec ns-broker ip addr add fc00::3145:50/112 dev veth-global
    ip netns exec ns-client-nat ip addr add fc00::3145:77/112 dev veth-global
    ip netns exec ns-client-nat ip addr add fc00::34d1:1/112 dev veth-client
    ip netns exec ns-client ip addr add fc00::34d1:200/112 dev veth-nat

    # Bring up the interfaces
    ip netns exec ns-server ip link set veth-nat up
    ip netns exec ns-server-nat ip link set veth-server up
    ip netns exec ns-server-nat ip link set veth-global up
    ip netns exec ns-global ip link set veth-server-nat up
    ip netns exec ns-global ip link set veth-broker up
    ip netns exec ns-global ip link set veth-client-nat up
    ip netns exec ns-broker ip link set veth-global up
    ip netns exec ns-client-nat ip link set veth-global up
    ip netns exec ns-client-nat ip link set veth-client up
    ip netns exec ns-client ip link set veth-nat up

    # Add default routes towards the global namespace
    ip netns exec ns-server ip -6 route add default via fc00::d034:1 dev veth-nat
    ip netns exec ns-broker ip -6 route add default dev veth-global
    ip netns exec ns-client ip -6 route add default via fc00::34d1:1 dev veth-nat

    # Enable IPv6 forwarding
    # Possibly not needed twice?
    ip netns exec ns-server-nat sysctl net.ipv6.conf.all.forwarding=1
    ip netns exec ns-client-nat sysctl net.ipv6.conf.all.forwarding=1

    # Configure NAT
    ip netns exec ns-server-nat nft -f nftables-server-nat.conf
    ip netns exec ns-client-nat nft -f nftables-client-nat.conf
}

launch() {
    # Helper: Launch in a given network namespace, running a command a "nobody"
    local where="$1";
    shift;
    # -c is a bit nuts with positional arguments
    ip netns exec "$where" runuser -u nobody -- "$@"
}

SERVICE_NATIVE_PORT=5347

SERVER_PUBLIC_ADDRESS="fc00::3145:66"
SERVER_PRIVATE_ADDRESS="fc00::d034:200"

BROKER_PORT=5348
BROKER_ADDRESS="fc00::3145:50"

teardown() {
    # Remove the namespaces
    ip netns del ns-server
    ip netns del ns-server-nat
    ip netns del ns-global
    ip netns del ns-broker
    ip netns del ns-client-nat
    ip netns del ns-client
    # Kill our descendant processes
    kill 0
}

run() {
    source venv/bin/activate
    sleep 1

    # Start the stub service
    launch ns-server ./stub-service.py "$SERVICE_NATIVE_PORT" --reuse-port &
    STUB_SERVICE_PID=$!
    sleep 1

    # Attempt to connect to it directly, to verify that NAT prevents this
    if launch ns-client ./stub-client.py "${SERVER_PRIVATE_ADDRESS}" "${SERVICE_NATIVE_PORT}"; then
        echo "Client should not have been able to connect to the server directly"
        exit 1
    fi
    # Attempt to connect to its "public" address, to verify that NAT prevents this
    if launch ns-client ./stub-client.py "${SERVER_PUBLIC_ADDRESS}" "${SERVICE_NATIVE_PORT}"; then
        echo "Client should not have been able to traverse to the NAT protected server without NAT punching"
        exit 1
    fi

    # Start the nat punching broker
    launch ns-broker ./broker.py "$BROKER_PORT" &
    BROKER_PID=$!
    sleep 1

    # Start the nat punching server
    launch ns-server ./server.py "$BROKER_ADDRESS" "$BROKER_PORT" "$SERVICE_NATIVE_PORT" &
    SERVER_PID=$!
    sleep 1

    # Start the nat punching client
    launch ns-client ./client.py "$BROKER_ADDRESS" "$BROKER_PORT" > punched-addrinfo.tmp

    # Validate that the service client is able to connect to the server through the NAT punched hole
    launch ns-client xargs ./stub-client.py < punched-addrinfo.tmp

    echo "It works!"
}

interactive() {
    # General purpose pane in the root namespace up top
    tmux new-session -d -s testbed 'bash --init-file <(echo "echo \"ctrl-B o arrow keys to change panes. Use ctrl-B d to finish.\"") -i'
    # Three split panes below, one for each component namespace
    tmux split-window -t testbed -v -l 66% -F 'Client' 'ip netns exec ns-client bash --init-file <(echo "echo -e \"\e[01;31mClient\e[0m\"") -i'
    tmux split-window -t testbed -h -l 70% -F 'Broker' 'ip netns exec ns-broker bash --init-file <(echo "echo -e \"\e[01;31mBroker\e[0m\"") -i'
    tmux split-window -t testbed -h -l 75% -F 'Server' 'ip netns exec ns-server bash --init-file <(echo "echo -e \"\e[01;31mServer\e[0m\"") -i'
    tmux attach-session -t testbed
    tmux kill-session -t testbed
}

main() {
    case $1 in
        setup)
            setup
            ;;
        interactive-step)
            interactive
            ;;
        run)
            run
            ;;
        teardown)
            teardown
            ;;
        auto)
            trap teardown EXIT
            setup
            run
            ;;
        interactive)
            trap teardown EXIT
            setup
            interactive
            ;;
        *)
            echo "Usage: $0 {setup|run|teardown|auto|interactive|interactive-step}"
            exit 1
    esac
    exit 0
}

main "$@"
