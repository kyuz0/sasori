# Repository Development Guidelines

This file provides system context for coding assistants tasked with modifying or extending *this* repository (`sasori`).

## Project Purpose
Sasori is a minimal, globally deployed IMAP polling daemon that creates a bridge between an email inbox and standalone local LLM agents (e.g. CLI applications). It uses a standard library SQLite queuing system to throttle execution concurrency, preventing VRAM overflow on consumer hardware.

## Technical Scope & Constraints
When making changes to the orchestrator logic (`sasori/daemon.py`), keeping it minimal and standard-library dependent is critical:

1. **No External Packages**: You MUST NOT introduce external requirements like `SQLAlchemy`, `asyncio` networking extensions, or third-party IMAP wrappers to this repository. The entire system must function across environments using standard default Python 3.10+ libraries.
2. **Safe Executions**: The daemon spawns agent logic completely asynchronously via `subprocess.Popen` attached to dynamic output `.out` files. DO NOT pipe subprocess outputs via standard in-memory byte arrays (e.g. `stdout=subprocess.PIPE`). If you do this, the `--STATUS` intercept blocks will fatally hang while trying to read the process stream dynamically.
3. **Queue Preservation**: Changing `MAX_CONCURRENT_AGENTS` logic MUST respect the SQLite `status` locks (`PENDING`, `QUEUED`, `RUNNING`, `DONE`, `STOPPED`).

## Plugin System Rule
When modifying this system to support new file types or agent interactions, do NOT hardcode agent logic into `daemon.py`. Assume you are providing a framework that users implement by extending `BaseMailboxHandler` inside their workspace `handlers/` directory.
