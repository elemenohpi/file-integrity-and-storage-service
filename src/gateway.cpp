// gateway.cpp
// The gateway node. Every request from a user or an employee arrives here.
// The gateway checks who is asking and passes the request into the system.
//
// Requests from the client:
//   LOGIN    name=<user> data=<password>         reply: data=<token>
//   UPLOAD   token name=<file> data=<contents>
//   SUBMIT   token data=<script>                 reply: arg=<job number>
//   STATUS   token arg=<job number>              reply: data=<state>
//   RESULT   token arg=<job number>              reply: data=<output>
//   REQUEST  token name=<file>                   reply: data=<contents>

#include "common.h"

#include <fstream>
#include <sstream>
#include <sys/socket.h>
#include <unistd.h>

const std::string USERS_FILE = "/config/users.txt";

// Looks the user up in the users file. Returns the role, or "" if the name
// or the password is wrong.
std::string check_password(const std::string& user, const std::string& password) {
    std::ifstream file(USERS_FILE.c_str());
    std::string line;
    while (std::getline(file, line)) {
        std::istringstream fields(line);
        std::string name, secret, role;
        fields >> name >> secret >> role;
        if (name == user && secret == password) {
            return role;
        }
    }
    return "";
}

Message handle_login(const Message& request) {
    std::string role = check_password(request.name, trim(request.data));
    if (role == "") {
        return make_reply("ERROR", "wrong user name or password");
    }
    // The token tells the gateway who is asking and what they may do.
    return make_reply("OK", request.name + ":" + role);
}

Message handle(const Message& request) {
    if (request.type == "LOGIN") {
        return handle_login(request);
    }

    // Every other request needs a token.
    std::vector<std::string> parts = split(request.token, ':');
    if (parts.size() != 2 || parts[0] == "") {
        return make_reply("ERROR", "please log in first");
    }
    std::string user = parts[0];
    std::string role = parts[1];

    Message forward;
    forward.sender = "gateway";
    Message reply;
    bool ok = false;

    if (request.type == "UPLOAD") {
        forward.type = "PUT";
        forward.name = request.name;
        forward.arg = "upload " + user;
        forward.data = request.data;
        ok = call("storage", STORAGE_PORT, forward, reply);
    } else if (request.type == "REQUEST") {
        forward.type = "GET";
        forward.name = request.name;
        forward.arg = "library -";
        ok = call("storage", STORAGE_PORT, forward, reply);
    } else if (request.type == "SUBMIT") {
        forward.type = "SUBMIT";
        forward.name = user;
        forward.arg = role;
        forward.data = request.data;
        ok = call("scheduler", SCHEDULER_PORT, forward, reply);
    } else if (request.type == "STATUS" || request.type == "RESULT") {
        forward.type = request.type;
        forward.arg = request.arg;
        ok = call("scheduler", SCHEDULER_PORT, forward, reply);
    } else {
        return make_reply("ERROR", "unknown request");
    }

    if (!ok) {
        return make_reply("ERROR", "the service is not available");
    }
    return reply;
}

int main() {
    start_node("gateway");

    int listener = listen_on(GATEWAY_PORT);
    while (true) {
        int fd = accept(listener, NULL, NULL);
        if (fd < 0) {
            continue;
        }

        Message request;
        if (recv_message(fd, request)) {
            long long start = now_ms();
            Message reply = handle(request);
            send_message(fd, reply);
            log_event("event=request type=" + request.type + " result=" + reply.type +
                      " ms=" + std::to_string(now_ms() - start));
        }
        close(fd);
    }
    return 0;
}
