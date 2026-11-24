CXX = g++
CXXFLAGS = -std=c++17 -Wall -O1 -pthread
COMMON = src/common.cpp src/sim.cpp
HEADERS = src/common.h src/sim.h

all: bin/gateway bin/scheduler bin/storage bin/execnode bin/fis

bin/gateway: src/gateway.cpp $(COMMON) $(HEADERS)
	mkdir -p bin
	$(CXX) $(CXXFLAGS) -o $@ src/gateway.cpp $(COMMON)

bin/scheduler: src/scheduler.cpp $(COMMON) $(HEADERS)
	mkdir -p bin
	$(CXX) $(CXXFLAGS) -o $@ src/scheduler.cpp $(COMMON)

bin/storage: src/storage.cpp $(COMMON) $(HEADERS)
	mkdir -p bin
	$(CXX) $(CXXFLAGS) -o $@ src/storage.cpp $(COMMON)

bin/execnode: src/execnode.cpp $(COMMON) $(HEADERS)
	mkdir -p bin
	$(CXX) $(CXXFLAGS) -o $@ src/execnode.cpp $(COMMON)

bin/fis: src/client.cpp $(COMMON) $(HEADERS)
	mkdir -p bin
	$(CXX) $(CXXFLAGS) -o $@ src/client.cpp $(COMMON)

clean:
	rm -rf bin
