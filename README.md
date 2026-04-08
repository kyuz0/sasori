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

### Writing Agent Handlers

Each handler should inherit from `BaseMailboxHandler` and define how it responds to specific email tags. Here is a basic structure:

```python
import subprocess
import os
from sasori.handler import BaseMailboxHandler

class MyAgentHandler(BaseMailboxHandler):
    # What string triggers this agent? (e.g. Subject: [my-agent] Fix my issue!)
    agent_tag = "[my-agent]" 
    
    # Path or CLI binary for the agent
    agent_command = "echo"

    def execute(self, thread_id: str, prompt_file: str, stdout_file: str) -> subprocess.Popen:
        """Called automatically when an email thread targets this agent."""
        cmd = [self.agent_command, "Hello from the new agent!"]
        agent_cwd = self.get_agent_workspace()
        
        return subprocess.Popen(
            cmd,
            cwd=agent_cwd,
            stdout=open(stdout_file, "w"),
            stderr=subprocess.STDOUT,
            text=True,
            env=dict(os.environ)
        )

# Tell the daemon about your handlers
HANDLERS = [MyAgentHandler()]
```

### Security & Agent Sandboxing

If you are running dynamic CLI agents that execute generated code (or perform unverified read/writes), you can optionally sandbox them using Anthropic's Sandbox Runtime (`srt`). 

Sandboxing uses native OS isolation primitives (e.g., `bubblewrap` on Linux) to tightly control an agent's filesystem and egress permissions. 

**Execution CWD (`Current Working Directory`)**
By default, the daemon launches your agent processes attached directly to a dedicated workspace folder specifically created for that agent inside `agent_workspaces/`. 
When sandboxing is enabled:
* Write access is strictly denied everywhere system-wide by default.
* Your agent's unique workspace (CWD) and `/tmp` are explicitly granted read/write approval.
* Any paths mapping to `sandbox_deny_workspace_patterns` are stripped of write/read permissions natively inside that workspace folder!

Enable isolation securely in your handler class:

```python
class IsolatedAgentHandler(BaseMailboxHandler):
    agent_tag = "[isolated-agent]"
    agent_command = "python3"

    # 1. Enable Sandbox Primitives natively
    sandbox_enabled = True
    
    # 2. Network domains (forces air-gap if omitted)
    sandbox_network_domains = ["pip.pypa.io", "github.com", "registry.npmjs.org"]
    
    # 3. Restrict host environment variable poisoning
    sandbox_env_whitelist = ["PATH", "HOME", "USER", "SHELL", "TERM"]
    
    # 4. Explicit read/write denial within the writable workspace zone
    sandbox_deny_workspace_patterns = ["**/*.secret", ".env*"]
    
    # 5. Prevent escalation vectors structurally
    sandbox_deny_binaries = ["docker", "terraform"]

    def execute(self, thread_id: str, prompt_file: str, stdout_file: str) -> subprocess.Popen:
        cmd = [self.agent_command, "agent.py", "--prompt", prompt_file]
        env = dict(os.environ)

        # Call the sandbox wrapper generator before you construct the Popen stream
        if self.sandbox_enabled:
            cmd, env = self._wrap_sandbox(cmd, thread_id)
            
        agent_cwd = self.get_agent_workspace()

        return subprocess.Popen(
            cmd,
            cwd=agent_cwd,
            stdout=open(stdout_file, "w"),
            stderr=subprocess.STDOUT,
            text=True,
            env=env
        )
```

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
