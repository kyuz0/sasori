# Sasori

This is a personal project I built while learning how to build and orchestrate local AI agents that could run on consumer hardware like the AMD Strix Halo. 

Sasori is a simple Python-based IMAP polling daemon that queues inbound email tasks and dispatches them to CLI agents one at a time to keep local hardware from crashing.

## Installation

Sasori runs entirely on Python Standard Libraries.

```bash
# Clone the repository
git clone https://github.com/kyuz0/sasori
cd sasori

# Install globally using pipx
sudo pipx install --global .
```

This makes the `sasori` CLI command available system-wide.

## Configuration & Handlers

Sasori operates using a "workspace" pattern based on your current working directory.

Upon first run, Sasori automatically creates a `handlers/` directory and a `sasori.db` database inside the directory from which you launch it.

Place Python scripts representing your agents inside this `handlers/` directory. The daemon will dynamically load any scripts mapping subject tags to system executables.

See the `examples/test_handler.py` file for a simple example of how an agent integrates with Sasori.

## Gmail Setup (App Passwords)

To connect Sasori to a Gmail mailbox, you cannot use your regular account password due to modern security restrictions. You must generate a dedicated "App Password":

1. Go to your Google Account settings (Manage your Google Account).
2. Navigate to the **Security** tab.
3. Under "How you sign in to Google", ensure **2-Step Verification** is turned on.
4. Search for **App passwords** (or go right to the bottom of the 2-Step Verification page).
5. Create a new App Password (e.g., name it "Sasori Agent").
6. Google will give you a 16-character password. Use this exact string (without spaces) as your `EMAIL_PASSWORD` when configuring the daemon in the exported environment variables or your `sasori.service` file.

## Running as a systemd Service (Linux)

To ensure Sasori runs perpetually in the background securely, we recommend running it as a dedicated system user.

1. Create a dedicated system user and workspace for the daemon:
   ```bash
   sudo useradd -r -s /sbin/nologin sasori
   sudo mkdir -p /opt/sasori
   sudo chown -R sasori:sasori /opt/sasori
   ```
2. Copy the provided `.service` template to your systemd folder:
   ```bash
   sudo cp sasori.service /etc/systemd/system/sasori.service
   ```
3. Edit the service to set your Email credentials and ensure `WorkingDirectory=` points to your workspace (e.g., `/opt/sasori`):
   ```bash
   sudo nano /etc/systemd/system/sasori.service
   ```
3. Enable and start the daemon:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable sasori
   sudo systemctl start sasori
   sudo systemctl status sasori
   ```

## User Interaction Commands

When the daemon is running, users can interact with it simply by sending emails:

- **Global Status:** Send an email with exactly the word `STATUS` (and no thread tags). It will reply with a list of all currently running agents.
- **Thread Status:** Reply `STATUS` inside an active thread. Sasori will dynamically read the console output text logs of the running agent and send you the tail, showing its reasoning.
- **Cancel a Task:** Reply `STOP`. The daemon will send `SIGTERM` to the agent hardware process, killing it gracefully, and flag the database thread as `STOPPED`.
