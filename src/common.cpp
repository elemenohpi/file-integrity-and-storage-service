// common.cpp
// See common.h.

#include "common.h"

#include <arpa/inet.h>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <netdb.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

static std::string node_name = "node";

// Every message starts with this header. Each field is text, padded with
// zero bytes up to its full size.
struct Header {
    char type[16];
    char sender[32];
    char token[64];
    char name[128];
    char arg[64];
    char length[16];     // number of payload bytes that follow the header
    char reserved[192];  // kept for future use
};

void start_node(const std::string& name) {
    node_name = name;
    signal(SIGPIPE, SIG_IGN);
    setvbuf(stdout, NULL, _IOLBF, 0);
    log_event("event=node_started");
}

long long now_ms() {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return tv.tv_sec * 1000LL + tv.tv_usec / 1000;
}

void log_event(const std::string& text) {
    std::string line = "ts=" + std::to_string(now_ms()) + " node=" + node_name + " " + text + "\n";
    fputs(line.c_str(), stdout);

    std::string path = "/logs/" + node_name + ".log";
    FILE* file = fopen(path.c_str(), "a");
    if (file != NULL) {
        fputs(line.c_str(), file);
        fclose(file);
    }
}

int listen_on(int port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        perror("socket");
        exit(1);
    }

    int yes = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));

    struct sockaddr_in address;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_ANY);
    address.sin_port = htons(port);

    if (bind(fd, (struct sockaddr*)&address, sizeof(address)) < 0) {
        perror("bind");
        exit(1);
    }
    if (listen(fd, 64) < 0) {
        perror("listen");
        exit(1);
    }
    return fd;
}

int connect_to(const std::string& host, int port) {
    struct addrinfo hints;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;

    struct addrinfo* result = NULL;
    std::string port_text = std::to_string(port);
    if (getaddrinfo(host.c_str(), port_text.c_str(), &hints, &result) != 0) {
        return -1;
    }

    int fd = socket(result->ai_family, result->ai_socktype, result->ai_protocol);
    if (fd < 0) {
        freeaddrinfo(result);
        return -1;
    }
    if (connect(fd, result->ai_addr, result->ai_addrlen) < 0) {
        close(fd);
        freeaddrinfo(result);
        return -1;
    }
    freeaddrinfo(result);
    return fd;
}

static bool send_all(int fd, const char* buffer, size_t count) {
    size_t sent = 0;
    while (sent < count) {
        ssize_t n = send(fd, buffer + sent, count - sent, 0);
        if (n <= 0) {
            return false;
        }
        sent += n;
    }
    return true;
}

static bool recv_all(int fd, char* buffer, size_t count) {
    size_t received = 0;
    while (received < count) {
        ssize_t n = recv(fd, buffer + received, count - received, 0);
        if (n <= 0) {
            return false;
        }
        received += n;
    }
    return true;
}

static void put_field(char* field, size_t size, const std::string& value) {
    memset(field, 0, size);
    strncpy(field, value.c_str(), size - 1);
}

static std::string get_field(const char* field, size_t size) {
    return std::string(field, strnlen(field, size));
}

bool send_message(int fd, const Message& message) {
    Header header;
    memset(&header, 0, sizeof(header));
    put_field(header.type, sizeof(header.type), message.type);
    put_field(header.sender, sizeof(header.sender), message.sender);
    put_field(header.token, sizeof(header.token), message.token);
    put_field(header.name, sizeof(header.name), message.name);
    put_field(header.arg, sizeof(header.arg), message.arg);
    put_field(header.length, sizeof(header.length), std::to_string(message.data.size()));

    if (!send_all(fd, (const char*)&header, sizeof(header))) {
        return false;
    }
    return send_all(fd, message.data.data(), message.data.size());
}

bool recv_message(int fd, Message& message) {
    Header header;
    if (!recv_all(fd, (char*)&header, sizeof(header))) {
        return false;
    }
    message.type = get_field(header.type, sizeof(header.type));
    message.sender = get_field(header.sender, sizeof(header.sender));
    message.token = get_field(header.token, sizeof(header.token));
    message.name = get_field(header.name, sizeof(header.name));
    message.arg = get_field(header.arg, sizeof(header.arg));

    long length = atol(get_field(header.length, sizeof(header.length)).c_str());
    message.data.assign(length, '\0');
    if (length == 0) {
        return true;
    }
    return recv_all(fd, &message.data[0], length);
}

bool call(const std::string& host, int port, const Message& request, Message& reply) {
    long long start = now_ms();
    bool ok = false;

    int fd = connect_to(host, port);
    if (fd >= 0) {
        ok = send_message(fd, request) && recv_message(fd, reply);
        close(fd);
    }

    log_event("event=call to=" + host + " type=" + request.type +
              " ms=" + std::to_string(now_ms() - start) + " ok=" + (ok ? "1" : "0"));
    return ok;
}

Message make_reply(const std::string& type, const std::string& data) {
    Message reply;
    reply.type = type;
    reply.sender = node_name;
    reply.data = data;
    return reply;
}

std::vector<std::string> split(const std::string& text, char separator) {
    std::vector<std::string> parts;
    std::string current;
    for (size_t i = 0; i < text.size(); i++) {
        if (text[i] == separator) {
            parts.push_back(current);
            current.clear();
        } else {
            current += text[i];
        }
    }
    parts.push_back(current);
    return parts;
}

std::string trim(const std::string& text) {
    size_t first = text.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) {
        return "";
    }
    size_t last = text.find_last_not_of(" \t\r\n");
    return text.substr(first, last - first + 1);
}
