/*
 * agentjail-egress: the sandbox side of allowlisted network egress.
 *
 *   agentjail-egress PORT SOCKET -- COMMAND [ARGS...]
 *
 * Runs inside the jail's network namespace, which has only a loopback
 * interface. It listens on 127.0.0.1:PORT, starts COMMAND, and relays every
 * accepted connection to the Unix SOCKET that agentjail bind-mounts into the
 * jail. The filtering proxy listens on the other end of that socket, outside
 * the jail; this program makes no policy decisions.
 *
 * It exits with COMMAND's status (128 + signal when COMMAND was killed). As
 * PID 1 of the jail it also reaps orphans, and its exit tears down any relay
 * still running.
 */

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <unistd.h>

static int write_all(int fd, const char *buf, ssize_t len) {
    while (len > 0) {
        ssize_t written = write(fd, buf, (size_t)len);
        if (written < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        buf += written;
        len -= written;
    }
    return 0;
}

static int relay(int client, int upstream) {
    struct pollfd fds[2] = {{client, POLLIN, 0}, {upstream, POLLIN, 0}};
    int peers[2] = {upstream, client};
    int open_streams = 2;
    char buf[65536];

    while (open_streams > 0) {
        if (poll(fds, 2, -1) < 0) {
            if (errno == EINTR) continue;
            return 1;
        }
        for (int i = 0; i < 2; i++) {
            if (fds[i].fd < 0 || !(fds[i].revents & (POLLIN | POLLHUP | POLLERR))) continue;
            ssize_t len = read(fds[i].fd, buf, sizeof buf);
            if (len < 0 && errno == EINTR) continue;
            if (len <= 0) {
                shutdown(peers[i], SHUT_WR);
                fds[i].fd = -1;
                open_streams--;
                continue;
            }
            if (write_all(peers[i], buf, len) < 0) return 1;
        }
    }
    return 0;
}

static void serve_connection(int client, const char *socket_path) {
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof addr);
    addr.sun_family = AF_UNIX;
    strcpy(addr.sun_path, socket_path);

    int upstream = socket(AF_UNIX, SOCK_STREAM, 0);
    if (upstream < 0 || connect(upstream, (struct sockaddr *)&addr, sizeof addr) < 0) {
        perror("agentjail-egress: connect to proxy");
        _exit(1);
    }
    _exit(relay(client, upstream));
}

int main(int argc, char **argv) {
    if (argc < 5 || strcmp(argv[3], "--") != 0) {
        fprintf(stderr, "usage: agentjail-egress PORT SOCKET -- COMMAND [ARGS...]\n");
        return 125;
    }

    char *end;
    long port = strtol(argv[1], &end, 10);
    const char *socket_path = argv[2];
    if (*end || port <= 0 || port > 65535 ||
        strlen(socket_path) >= sizeof(((struct sockaddr_un *)0)->sun_path)) {
        fprintf(stderr, "agentjail-egress: invalid port or socket path\n");
        return 125;
    }

    int listener = socket(AF_INET, SOCK_STREAM, 0);
    int one = 1;
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof addr);
    addr.sin_family = AF_INET;
    addr.sin_port = htons((unsigned short)port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (listener < 0 || fcntl(listener, F_SETFD, FD_CLOEXEC) < 0 ||
        setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one) < 0 ||
        bind(listener, (struct sockaddr *)&addr, sizeof addr) < 0 || listen(listener, 64) < 0) {
        perror("agentjail-egress: listen");
        return 125;
    }

    pid_t command = fork();
    if (command < 0) {
        perror("agentjail-egress: fork");
        return 125;
    }
    if (command == 0) {
        execvp(argv[4], argv + 4);
        perror("agentjail-egress: exec");
        _exit(127);
    }

    /* After the fork, so the command keeps the default SIGPIPE disposition. */
    signal(SIGPIPE, SIG_IGN);

    for (;;) {
        int status;
        pid_t done;
        while ((done = waitpid(-1, &status, WNOHANG)) > 0) {
            if (done == command) {
                return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
            }
        }

        struct pollfd ready = {listener, POLLIN, 0};
        if (poll(&ready, 1, 50) <= 0) continue;

        int client = accept(listener, NULL, NULL);
        if (client < 0) continue;
        pid_t handler = fork();
        if (handler == 0) {
            close(listener);
            serve_connection(client, socket_path);
        }
        close(client);
    }
}
