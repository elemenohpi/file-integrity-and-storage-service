// scheduler.cpp
// The scheduler node. It keeps the queue of jobs, hands each job to an
// execution node and remembers the result.
//
// Requests:
//   SUBMIT  name=<user> arg=<role> data=<script>   reply: arg=<job number>
//   STATUS  arg=<job number>                       reply: data=<state>
//   RESULT  arg=<job number>                       reply: data=<output>

#include "common.h"
#include "sim.h"

#include <cstdlib>
#include <pthread.h>
#include <sys/socket.h>
#include <unistd.h>

struct Job {
    int id;
    std::string owner;
    std::string role;
    std::string script;
    std::string state;   // "waiting", "running" or "done"
    std::string output;
    int node;            // which execution node runs this job
    long long submitted;
};

std::vector<Job> jobs;
std::vector<std::string> nodes;  // the names of the execution nodes
pthread_mutex_t jobs_lock = PTHREAD_MUTEX_INITIALIZER;

int count_waiting() {
    int count = 0;
    for (size_t i = 0; i < jobs.size(); i++) {
        if (jobs[i].state == "waiting") {
            count++;
        }
    }
    return count;
}

// One of these threads runs for each execution node. It sends that node its
// jobs, one at a time.
void* dispatch(void* argument) {
    int me = (int)(long)argument;

    while (true) {
        // Look for work once per second.
        sim_sleep_ms(1000);

        int found = -1;
        Message run;
        pthread_mutex_lock(&jobs_lock);
        for (size_t i = 0; i < jobs.size(); i++) {
            if (jobs[i].state == "waiting" && jobs[i].node == me) {
                found = i;
                jobs[i].state = "running";
                run.type = "RUN";
                run.sender = "scheduler";
                run.name = jobs[i].owner;
                run.arg = std::to_string(jobs[i].id) + " " + jobs[i].role;
                run.data = jobs[i].script;
                log_event("event=job_started job=" + std::to_string(jobs[i].id) +
                          " exec=" + nodes[me] +
                          " wait_ms=" + std::to_string(now_ms() - jobs[i].submitted) +
                          " queue=" + std::to_string(count_waiting()));
                break;
            }
        }
        pthread_mutex_unlock(&jobs_lock);

        if (found < 0) {
            continue;
        }

        long long start = now_ms();
        Message reply;
        if (!call(nodes[me], EXEC_PORT, run, reply)) {
            log_event("event=node_failed exec=" + nodes[me]);
            continue;
        }

        pthread_mutex_lock(&jobs_lock);
        jobs[found].state = "done";
        jobs[found].output = reply.data;
        log_event("event=job_done job=" + std::to_string(jobs[found].id) +
                  " exec=" + nodes[me] + " run_ms=" + std::to_string(now_ms() - start));
        pthread_mutex_unlock(&jobs_lock);
    }
    return NULL;
}

Message handle_submit(const Message& request) {
    pthread_mutex_lock(&jobs_lock);
    Job job;
    job.id = jobs.size() + 1;
    job.owner = request.name;
    job.role = request.arg;
    job.script = request.data;
    job.state = "waiting";
    job.node = (job.id - 1) % nodes.size();  // the nodes take turns
    job.submitted = now_ms();
    jobs.push_back(job);
    log_event("event=job_submitted job=" + std::to_string(job.id) + " user=" + job.owner +
              " queue=" + std::to_string(count_waiting()));
    pthread_mutex_unlock(&jobs_lock);

    Message reply = make_reply("OK", "submitted");
    reply.arg = std::to_string(job.id);
    return reply;
}

Message handle_status(const Message& request) {
    int id = atoi(request.arg.c_str());
    Message reply = make_reply("ERROR", "no such job");

    pthread_mutex_lock(&jobs_lock);
    for (size_t i = 0; i < jobs.size(); i++) {
        if (jobs[i].id == id) {
            reply = make_reply("OK", jobs[i].state);
        }
    }
    pthread_mutex_unlock(&jobs_lock);
    return reply;
}

Message handle_result(const Message& request) {
    int id = atoi(request.arg.c_str());
    Message reply = make_reply("ERROR", "no such job");

    pthread_mutex_lock(&jobs_lock);
    for (size_t i = 0; i < jobs.size(); i++) {
        if (jobs[i].id == id) {
            if (jobs[i].state == "done") {
                reply = make_reply("OK", jobs[i].output);
            } else {
                reply = make_reply("ERROR", "the job is not finished");
            }
        }
    }
    pthread_mutex_unlock(&jobs_lock);
    return reply;
}

int main() {
    start_node("scheduler");

    const char* list = getenv("EXEC_NODES");
    nodes = split(list != NULL ? list : "exec1,exec2,exec3", ',');

    for (size_t i = 0; i < nodes.size(); i++) {
        pthread_t thread;
        pthread_create(&thread, NULL, dispatch, (void*)(long)i);
        pthread_detach(thread);
    }

    int listener = listen_on(SCHEDULER_PORT);
    while (true) {
        int fd = accept(listener, NULL, NULL);
        if (fd < 0) {
            continue;
        }

        Message request;
        if (recv_message(fd, request)) {
            Message reply;
            if (request.type == "SUBMIT") {
                reply = handle_submit(request);
            } else if (request.type == "STATUS") {
                reply = handle_status(request);
            } else if (request.type == "RESULT") {
                reply = handle_result(request);
            } else {
                reply = make_reply("ERROR", "unknown request");
            }
            send_message(fd, reply);
        }
        close(fd);
    }
    return 0;
}
