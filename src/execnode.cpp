// execnode.cpp
// An execution node. It receives one job at a time from the scheduler, runs
// the script of the job line by line and sends the output back.
//
// Request:
//   RUN  name=<user> arg="<job number> <role>" data=<script>   reply: data=<output>
//
// A script has one command per line:
//   check <file>     compare the user's uploaded file with the library copy
//   add <file>       employees only: put the uploaded file into the library
//   modify <file>    employees only: replace the library copy with the uploaded file
//   remove <file>    employees only: delete the file from the library

#include "common.h"
#include "sim.h"

#include <cstdio>
#include <cstdlib>
#include <sstream>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>

const std::string WORK_DIR = "/work";
const std::string RESULTS_DIR = "/tmp/results";

std::string node_id = "exec";

// Adds one line to the output of the job.
void write_output(const std::string& dir, const std::string& text) {
    std::string command = "echo \"" + text + "\" >> " + dir + "/output.txt";
    system(command.c_str());
}

// Asks the storage node for a file. Returns false if it is not there.
bool fetch(const std::string& area, const std::string& owner, const std::string& name,
           std::string& contents) {
    Message request;
    request.type = "GET";
    request.sender = node_id;
    request.name = name;
    request.arg = area + " " + owner;

    Message reply;
    if (!call("storage", STORAGE_PORT, request, reply) || reply.type != "OK") {
        return false;
    }
    contents = reply.data;
    return true;
}

void save_file(const std::string& path, const std::string& contents) {
    FILE* file = fopen(path.c_str(), "wb");
    if (file != NULL) {
        fwrite(contents.data(), 1, contents.size(), file);
        fclose(file);
    }
}

// Compares two files one character at a time.
bool same_contents(const std::string& first_path, const std::string& second_path) {
    FILE* first = fopen(first_path.c_str(), "rb");
    FILE* second = fopen(second_path.c_str(), "rb");
    if (first == NULL || second == NULL) {
        if (first != NULL) fclose(first);
        if (second != NULL) fclose(second);
        return false;
    }

    bool same = true;
    while (true) {
        int a = fgetc(first);
        int b = fgetc(second);
        if (a != b) {
            same = false;
            break;
        }
        if (a == EOF) {
            break;
        }
    }
    fclose(first);
    fclose(second);
    return same;
}

std::string do_check(const std::string& dir, const std::string& owner, const std::string& name) {
    std::string uploaded;
    if (!fetch("upload", owner, name, uploaded)) {
        return "not uploaded";
    }
    save_file(dir + "/" + name, uploaded);

    std::string original;
    if (!fetch("library", "-", name, original)) {
        return "not in library";
    }
    save_file(dir + "/" + name + ".library", original);

    if (same_contents(dir + "/" + name, dir + "/" + name + ".library")) {
        return "intact";
    }
    return "modified";
}

// Used by both add and modify.
std::string do_store(const std::string& dir, const std::string& owner, const std::string& name,
                     const std::string& done) {
    std::string uploaded;
    if (!fetch("upload", owner, name, uploaded)) {
        return "not uploaded";
    }
    save_file(dir + "/" + name, uploaded);

    Message request;
    request.type = "PUT";
    request.sender = node_id;
    request.name = name;
    request.arg = "library -";
    request.data = uploaded;

    Message reply;
    if (!call("storage", STORAGE_PORT, request, reply) || reply.type != "OK") {
        return "failed";
    }
    return done;
}

std::string do_remove(const std::string& name) {
    Message request;
    request.type = "DEL";
    request.sender = node_id;
    request.name = name;
    request.arg = "library -";

    Message reply;
    if (!call("storage", STORAGE_PORT, request, reply) || reply.type != "OK") {
        return "not in library";
    }
    return "removed";
}

// Keeps a copy of the result on this node.
void archive_result(const std::string& job, const std::string& output) {
    std::string path = RESULTS_DIR + "/job-" + job + ".txt";

    // An older result is never overwritten.
    struct stat info;
    if (lstat(path.c_str(), &info) == 0) {
        log_event("event=archive_skipped job=" + job);
        return;
    }

    disk_write_delay(output.size());
    FILE* file = fopen(path.c_str(), "w");
    if (file != NULL) {
        fwrite(output.data(), 1, output.size(), file);
        fclose(file);
    }
}

std::string run_job(const std::string& job, const std::string& owner, const std::string& role,
                    const std::string& script) {
    std::string dir = WORK_DIR + "/job-" + job;
    mkdir(dir.c_str(), 0777);

    std::vector<std::string> lines = split(script, '\n');
    for (size_t i = 0; i < lines.size(); i++) {
        std::string line = trim(lines[i]);
        if (line == "") {
            continue;
        }

        // The first word is the command. The rest of the line is the file name.
        std::string command = line;
        std::string name = "";
        size_t space = line.find(' ');
        if (space != std::string::npos) {
            command = line.substr(0, space);
            name = trim(line.substr(space + 1));
        }

        std::string verdict;
        if (command == "check") {
            verdict = do_check(dir, owner, name);
        } else if (command == "add" || command == "modify" || command == "remove") {
            if (role != "employee") {
                verdict = "permission denied";
            } else if (command == "add") {
                verdict = do_store(dir, owner, name, "added");
            } else if (command == "modify") {
                verdict = do_store(dir, owner, name, "updated");
            } else {
                verdict = do_remove(name);
            }
        } else {
            write_output(dir, "unknown command: " + command);
            continue;
        }
        write_output(dir, name + ": " + verdict);
    }

    // Read the whole output back.
    std::string output;
    FILE* file = fopen((dir + "/output.txt").c_str(), "rb");
    if (file != NULL) {
        int c;
        while ((c = fgetc(file)) != EOF) {
            output += (char)c;
        }
        fclose(file);
    }

    archive_result(job, output);
    return output;
}

int main() {
    const char* name = getenv("NODE_NAME");
    if (name != NULL) {
        node_id = name;
    }
    start_node(node_id);

    mkdir(WORK_DIR.c_str(), 0777);
    mkdir(RESULTS_DIR.c_str(), 0777);
    chmod(RESULTS_DIR.c_str(), 0777);

    int listener = listen_on(EXEC_PORT);
    while (true) {
        int fd = accept(listener, NULL, NULL);
        if (fd < 0) {
            continue;
        }

        Message request;
        if (recv_message(fd, request)) {
            Message reply;
            if (request.type == "RUN") {
                long long start = now_ms();

                std::vector<std::string> parts = split(request.arg, ' ');
                std::string job = parts.size() > 0 ? parts[0] : "0";
                std::string role = parts.size() > 1 ? parts[1] : "user";

                std::string output = run_job(job, request.name, role, request.data);
                reply = make_reply("OK", output);

                log_event("event=job_run job=" + job + " user=" + request.name +
                          " ms=" + std::to_string(now_ms() - start));
            } else {
                reply = make_reply("ERROR", "unknown request");
            }
            send_message(fd, reply);
        }
        close(fd);
    }
    return 0;
}
