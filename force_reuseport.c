/*
 * Simple LD_PRELOAD hack to force SO_REUSEADDR for bind() calls.
 */

#define _GNU_SOURCE

#include <stdio.h>
#include <stdlib.h>
#include <dlfcn.h>
#include <sys/socket.h>

static int (*real_bind)(int, const struct sockaddr *, socklen_t) = 0;

__attribute__((constructor))
void init(void)
{
    real_bind = dlsym(RTLD_NEXT, "bind");
}

int bind(int sockfd, const struct sockaddr *addr, socklen_t addrlen)
{
    int value = 1;

    if (setsockopt(sockfd, SOL_SOCKET, SO_REUSEPORT, &value, sizeof(value)) < 0) {
        perror("setsockopt");
        exit(EXIT_FAILURE);
    }

    return real_bind(sockfd, addr, addrlen);
}

// Compile: gcc -shared -fPIC -o force_reuseaddr.so force_reuseaddr.c -ldl
