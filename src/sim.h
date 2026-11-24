// sim.h
// The simulation clock and the simulated disk.
//
// DO NOT MODIFY THIS FILE OR sim.cpp.
//
// The storage node pretends to have a slow disk. Every search of the index
// and every read or write of a stored file must be charged with the matching
// delay below. You may make the system faster by doing less disk work (for
// example by keeping a copy of a file in memory), but not by removing or
// shortening the delay for disk work that still happens.

#ifndef SIM_H
#define SIM_H

#include <cstddef>

// How many times faster than normal the simulation is running (SIM_SPEED).
double sim_speed();

// Sleeps for the given amount of simulated time.
void sim_sleep_ms(double milliseconds);

// The cost of looking through this many entries of the index on disk.
void disk_search_delay(size_t entries_scanned);

// The cost of reading a file of this size from disk into memory.
void disk_read_delay(size_t bytes);

// The cost of writing a file of this size from memory to disk.
void disk_write_delay(size_t bytes);

#endif
