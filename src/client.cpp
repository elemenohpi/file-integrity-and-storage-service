// client.cpp
// The command line client, "fis". Users and employees use it to talk to the
// gateway.
//
//   fis login <user> <password>   log in; the session is remembered in a file
//   fis upload <file>             upload a file
//   fis submit <script-file>      submit a script as a job; prints "job <number>"
//   fis status <job>              print the state of a job
//   fis result <job>              print the output of a finished job
//   fis request <file>            print the library copy of a file
//
// The exit status is 0 when the request worked and 1 when it did not.
//
// Environment variables:
//   FIS_GATEWAY   host name of the gateway (default: gateway)
//   FIS_SESSION   file that remembers the session (default: $HOME/.fis_session)

#include "common.h"

#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>

std::string session_file() {
    const char* path = getenv("FIS_SESSION");
    if (path != NULL) {
        return path;
    }
    const char* home = getenv("HOME");
    return std::string(home != NULL ? home : ".") + "/.fis_session";
}

std::string gateway_host() {
    const char* host = getenv("FIS_GATEWAY");
    return host != NULL ? host : "gateway";
}

bool read_file(const std::string& path, std::string& contents) {
    std::ifstream file(path.c_str(), std::ios::binary);
    if (!file) {
        return false;
    }
    std::ostringstream buffer;
    buffer << file.rdbuf();
    contents = buffer.str();
    return true;
}

// Removes the directories from a path: "docs/a.txt" becomes "a.txt".
std::string base_name(const std::string& path) {
    size_t slash = path.find_last_of("/\\");
    if (slash == std::string::npos) {
        return path;
    }
    return path.substr(slash + 1);
}

int usage() {
    std::cerr << "error: wrong arguments. The commands are:\n"
              << "  fis login <user> <password>\n"
              << "  fis upload <file>\n"
              << "  fis submit <script-file>\n"
              << "  fis status <job>\n"
              << "  fis result <job>\n"
              << "  fis request <file>\n";
    return 1;
}

int main(int argc, char* argv[]) {
    // A connection that closes while we write must not kill the client.
    signal(SIGPIPE, SIG_IGN);

    if (argc < 3) {
        return usage();
    }
    std::string command = argv[1];

    Message request;
    request.sender = "client";

    if (command == "login") {
        if (argc != 4) {
            return usage();
        }
        request.type = "LOGIN";
        request.name = argv[2];
        request.data = argv[3];
    } else {
        if (argc != 3) {
            return usage();
        }
        std::string token;
        if (!read_file(session_file(), token)) {
            std::cerr << "error: please log in first\n";
            return 1;
        }
        request.token = trim(token);

        if (command == "upload") {
            request.type = "UPLOAD";
            request.name = base_name(argv[2]);
            if (!read_file(argv[2], request.data)) {
                std::cerr << "error: cannot read " << argv[2] << "\n";
                return 1;
            }
        } else if (command == "submit") {
            request.type = "SUBMIT";
            if (!read_file(argv[2], request.data)) {
                std::cerr << "error: cannot read " << argv[2] << "\n";
                return 1;
            }
        } else if (command == "status") {
            request.type = "STATUS";
            request.arg = argv[2];
        } else if (command == "result") {
            request.type = "RESULT";
            request.arg = argv[2];
        } else if (command == "request") {
            request.type = "REQUEST";
            request.name = argv[2];
        } else {
            return usage();
        }
    }

    Message reply;
    int fd = connect_to(gateway_host(), GATEWAY_PORT);
    if (fd < 0 || !send_message(fd, request) || !recv_message(fd, reply)) {
        std::cerr << "error: cannot reach the gateway\n";
        return 1;
    }

    if (reply.type != "OK") {
        std::cerr << "error: " << reply.data << "\n";
        return 1;
    }

    if (command == "login") {
        std::ofstream file(session_file().c_str(), std::ios::trunc);
        file << reply.data << "\n";
        file.close();
        if (!file) {
            std::cerr << "error: cannot write " << session_file() << "\n";
            return 1;
        }
        std::cout << "logged in as " << argv[2] << "\n";
    } else if (command == "upload") {
        std::cout << "uploaded " << request.name << "\n";
    } else if (command == "submit") {
        std::cout << "job " << reply.arg << "\n";
    } else if (command == "status") {
        std::cout << reply.data << "\n";
    } else {
        // result and request print exactly what came back
        std::cout << reply.data;
    }
    return 0;
}
