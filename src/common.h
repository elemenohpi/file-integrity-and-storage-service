// common.h
// Code shared by every node and by the client: the message format, the
// socket helpers and the log.

#ifndef COMMON_H
#define COMMON_H

#include <string>
#include <vector>

// The port each kind of node listens on.
const int GATEWAY_PORT = 9000;
const int SCHEDULER_PORT = 9001;
const int STORAGE_PORT = 9002;
const int EXEC_PORT = 9003;

// One message between two programs. A request and its reply are both
// messages. Not every field is used by every type of message.
struct Message {
    std::string type;    // what is asked, or "OK" / "ERROR" in a reply
    std::string sender;  // who sent the message
    std::string token;   // the login token of the person making the request
    std::string name;    // a file name or a user name
    std::string arg;     // a small extra value, for example a job number
    std::string data;    // the payload, for example the contents of a file
};

// Call once at the start of a node. Sets the name used in the log.
void start_node(const std::string& name);

// Opens a listening socket on the port. Exits the program on failure.
int listen_on(int port);

// Connects to host:port. Returns the socket, or -1 on failure.
int connect_to(const std::string& host, int port);

// Sends or receives one message on a connected socket.
bool send_message(int fd, const Message& message);
bool recv_message(int fd, Message& message);

// Connects to host:port, sends the request, waits for the reply and closes
// the connection. Returns false if any step fails.
bool call(const std::string& host, int port, const Message& request, Message& reply);

// Builds a reply.
Message make_reply(const std::string& type, const std::string& data);

// The current time in milliseconds.
long long now_ms();

// Adds one line to the log of this node. The text is a list of key=value
// pairs separated by spaces, for example "event=job_done job=12".
void log_event(const std::string& text);

// Splits text at every occurrence of the separator.
std::vector<std::string> split(const std::string& text, char separator);

// Removes spaces, tabs and line endings from both ends.
std::string trim(const std::string& text);

#endif
