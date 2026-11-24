# CSE 325 Final Project: Improving a File Integrity Service

Read the specification first: `CSE325_Final_Project.pdf` in this folder. This file is only a quick start. The system itself is documented in the Documentation tab of its dashboard.

## What you need

Docker Desktop (Windows, macOS) or Docker Engine with the Compose plugin (Linux). Nothing else.

## Run the system

Run these commands in this folder.

```
docker compose up --build      build and start everything
docker compose down -v         stop everything and delete all stored data
```

Then open http://localhost:8080 for the dashboard. Its Documentation tab explains the parts of the system, the code files and every measurement.

A run plays one sequence of 60 simulated minutes. With the default speed this takes about six real minutes, and up to one more minute while the last jobs finish. The dashboard shows `finished` when the run is over. The measurements of each run are saved in a new folder under `runs/`.

## Settings

The file `.env` holds the settings of a run. Its name starts with a dot, so Linux and macOS hide it: list it with `ls -a`, or show hidden files in your file manager (Ctrl+H on most Linux desktops, Cmd+Shift+. in the macOS Finder). Any text editor can open it.

| Setting | Meaning | Default |
|---|---|---|
| `SPEED` | Simulated seconds per real second | `10` |
| `SEQUENCE` | The sequence to play: `normal`, `hostile`, or a file of your own in `monitor/sequences/` | `normal` |
| `DASHBOARD_PORT` | The port of the dashboard on your computer | `8080` |

## Try the client by hand

```
docker compose exec client fis login tester tester123
docker compose exec client fis upload report.txt
docker compose exec client fis submit check.txt
docker compose exec client fis status 12
docker compose exec client fis result 12
```

Here 12 stands for the job number that `fis submit` printed.

The files `report.txt`, `check.txt` and `add.txt` are in `samples/`. Use the accounts `tester` (a user, password `tester123`) and `trainee` (an employee, password `trainee123`). The other accounts in `config/users.txt` are played by the monitor during a run, so do not use them by hand.

## What is in this folder

| Path | Contents |
|---|---|
| `src/` | The C++ source of the nodes and the client |
| `Makefile`, `Dockerfile` | Build the programs and the image that every node uses |
| `compose.yml` | The containers, their limits and their network |
| `.env` | The settings of a run |
| `config/users.txt` | The accounts of the service |
| `samples/` | A few files for trying the client by hand |
| `monitor/`, `outside/` | Programs that belong to the course staff |
| `runs/` | The measurements of every run |
| `report/report.docx` | The template of the written document (Word) |

## Do not modify

- `src/sim.h` and `src/sim.cpp`
- anything in `monitor/` and `outside/` (you may add sequence files of your own to `monitor/sequences/`)
- the services `client`, `monitor` and `outside` in `compose.yml`

The specification (item 5) lists everything that must stay the same.

## First steps

1. Run the `normal` sequence on the system exactly as you received it, and keep the folder that appears under `runs/`.
2. Set `SEQUENCE=hostile` in `.env`, run `docker compose down -v`, and run again. Keep that folder too.
3. These two runs are your "before" measurements.
