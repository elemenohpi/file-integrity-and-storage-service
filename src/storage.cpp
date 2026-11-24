// storage.cpp
// The storage node. It keeps the library and the uploaded files on its disk,
// together with an index that lists every stored file.
//
// Requests:
//   PUT  name=<file> arg="<area> <owner>" data=<contents>   store a file
//   GET  name=<file> arg="<area> <owner>"                   return a file
//   DEL  name=<file> arg="<area> <owner>"                   delete a file
//
// The area is "library" or "upload". Library files have the owner "-".

#include "common.h"
#include "sim.h"

#include <cstdio>
#include <fstream>
#include <pthread.h>
#include <sstream>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>

const std::string DATA_DIR = "/data";
const std::string INDEX_FILE = "/data/index.txt";

// One line of the index.
struct Entry {
    std::string area;
    std::string owner;
    std::string name;
    std::string state;  // "stored" or "deleted"
};

std::vector<Entry> load_index() {
    std::vector<Entry> index;
    std::ifstream file(INDEX_FILE.c_str());
    std::string line;
    while (std::getline(file, line)) {
        std::vector<std::string> fields = split(line, '\t');
        if (fields.size() == 4) {
            Entry entry;
            entry.area = fields[0];
            entry.owner = fields[1];
            entry.name = fields[2];
            entry.state = fields[3];
            index.push_back(entry);
        }
    }
    return index;
}

void save_index(const std::vector<Entry>& index) {
    std::ofstream file(INDEX_FILE.c_str(), std::ios::trunc);
    for (size_t i = 0; i < index.size(); i++) {
        file << index[i].area << '\t' << index[i].owner << '\t'
             << index[i].name << '\t' << index[i].state << '\n';
    }
}

void append_to_index(const Entry& entry) {
    std::ofstream file(INDEX_FILE.c_str(), std::ios::app);
    file << entry.area << '\t' << entry.owner << '\t' << entry.name << '\t' << entry.state << '\n';
}

// Looks through the index for a stored file. Returns its position, or -1.
int find_entry(const std::vector<Entry>& index, const std::string& area,
               const std::string& owner, const std::string& name) {
    for (size_t i = 0; i < index.size(); i++) {
        if (index[i].state != "deleted" && index[i].area == area &&
            index[i].owner == owner && index[i].name == name) {
            disk_search_delay(i + 1);
            return i;
        }
    }
    disk_search_delay(index.size());
    return -1;
}

std::string path_of(const std::string& area, const std::string& owner, const std::string& name) {
    if (area == "library") {
        return DATA_DIR + "/library/" + name;
    }
    return DATA_DIR + "/uploads/" + owner + "/" + name;
}

Message handle_put(const std::string& area, const std::string& owner, const Message& request) {
    if (area != "library") {
        mkdir((DATA_DIR + "/uploads/" + owner).c_str(), 0777);
    }

    std::string path = path_of(area, owner, request.name);
    FILE* file = fopen(path.c_str(), "wb");
    if (file == NULL) {
        return make_reply("ERROR", "could not store the file");
    }
    fwrite(request.data.data(), 1, request.data.size(), file);
    fclose(file);
    disk_write_delay(request.data.size());

    Entry entry;
    entry.area = area;
    entry.owner = owner;
    entry.name = request.name;
    entry.state = "stored";
    append_to_index(entry);

    return make_reply("OK", "stored");
}

Message handle_get(const std::string& area, const std::string& owner, const Message& request) {
    std::vector<Entry> index = load_index();
    if (find_entry(index, area, owner, request.name) < 0) {
        return make_reply("ERROR", "not found");
    }

    std::string path = path_of(area, owner, request.name);
    FILE* file = fopen(path.c_str(), "rb");
    if (file == NULL) {
        return make_reply("ERROR", "not found");
    }
    std::string contents;
    int c;
    while ((c = fgetc(file)) != EOF) {
        contents += (char)c;
    }
    fclose(file);
    disk_read_delay(contents.size());

    return make_reply("OK", contents);
}

Message handle_del(const std::string& area, const std::string& owner, const Message& request) {
    std::vector<Entry> index = load_index();
    int position = find_entry(index, area, owner, request.name);
    if (position < 0) {
        return make_reply("ERROR", "not found");
    }

    // The file is only marked as deleted. It stays on the disk.
    // A file can have more than one entry, so all of them are marked.
    for (size_t i = position; i < index.size(); i++) {
        if (index[i].area == area && index[i].owner == owner && index[i].name == request.name) {
            index[i].state = "deleted";
        }
    }
    disk_write_delay(index.size() * 64);
    save_index(index);

    return make_reply("OK", "deleted");
}

void* serve(void* argument) {
    int fd = (int)(long)argument;

    Message request;
    if (recv_message(fd, request)) {
        long long start = now_ms();

        std::vector<std::string> parts = split(request.arg, ' ');
        std::string area = parts.size() > 0 ? parts[0] : "";
        std::string owner = parts.size() > 1 ? parts[1] : "-";

        Message reply;
        if (request.type == "PUT") {
            reply = handle_put(area, owner, request);
        } else if (request.type == "GET") {
            reply = handle_get(area, owner, request);
        } else if (request.type == "DEL") {
            reply = handle_del(area, owner, request);
        } else {
            reply = make_reply("ERROR", "unknown request");
        }
        send_message(fd, reply);

        log_event("event=storage op=" + request.type + " area=" + area +
                  " result=" + reply.type + " ms=" + std::to_string(now_ms() - start));
    }

    close(fd);
    return NULL;
}

int main() {
    start_node("storage");

    mkdir((DATA_DIR + "/library").c_str(), 0777);
    mkdir((DATA_DIR + "/uploads").c_str(), 0777);

    int listener = listen_on(STORAGE_PORT);
    while (true) {
        int fd = accept(listener, NULL, NULL);
        if (fd < 0) {
            continue;
        }
        // One thread for each request.
        pthread_t thread;
        pthread_create(&thread, NULL, serve, (void*)(long)fd);
        pthread_detach(thread);
    }
    return 0;
}
