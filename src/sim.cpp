// sim.cpp
// DO NOT MODIFY THIS FILE OR sim.h. See sim.h.

#include "sim.h"

#include <cstdlib>
#include <unistd.h>

// All times are in simulated milliseconds.
static const double SEARCH_MS_PER_ENTRY = 1.0;
static const double READ_MS_BASE = 30.0;
static const double READ_MS_PER_KB = 2.0;
static const double WRITE_MS_BASE = 40.0;
static const double WRITE_MS_PER_KB = 3.0;

double sim_speed() {
    static double speed = 0.0;
    if (speed == 0.0) {
        const char* text = getenv("SIM_SPEED");
        speed = (text != NULL) ? atof(text) : 1.0;
        if (speed <= 0.0) {
            speed = 1.0;
        }
    }
    return speed;
}

void sim_sleep_ms(double milliseconds) {
    double real_microseconds = milliseconds * 1000.0 / sim_speed();
    if (real_microseconds >= 1.0) {
        usleep((useconds_t)real_microseconds);
    }
}

void disk_search_delay(size_t entries_scanned) {
    sim_sleep_ms(SEARCH_MS_PER_ENTRY * entries_scanned);
}

void disk_read_delay(size_t bytes) {
    sim_sleep_ms(READ_MS_BASE + READ_MS_PER_KB * (bytes / 1024.0));
}

void disk_write_delay(size_t bytes) {
    sim_sleep_ms(WRITE_MS_BASE + WRITE_MS_PER_KB * (bytes / 1024.0));
}
