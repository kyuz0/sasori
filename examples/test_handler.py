import subprocess
import os
from sasori.handler import BaseMailboxHandler

class TestAgentHandler(BaseMailboxHandler):
    # To test this agent, send an email with a subject like: "[test-agent] Hello!"
    agent_tag = "[test-agent]" 
    # Use standard python execution to bypass the need for a globally installed dummy executable
    agent_command = "python3"

    sandbox_enabled = True
    sandbox_network_domains = ["pip.pypa.io", "github.com"]

    def execute(self, thread_id: str, prompt_file: str, stdout_file: str) -> subprocess.Popen:
        """
        Usually this runs your pipx command.
        For the test agent, we simulate a 60 second job with status outputs every 10 seconds.
        """
        script = """import time, sys, os
print(f'Starting sandboxed test... Current ENV limits: {[k for k in os.environ.keys()]}', flush=True)
for i in range(6):
    print(f'Running step {i+1}/6 (elapsed: {i*5}s)...', flush=True) # Speeding up output for debugging
    time.sleep(5)
print('Test Agent: DONE', flush=True)
"""
        cmd = [self.agent_command, "-c", script]
        env = dict(os.environ)

        if self.sandbox_enabled:
            cmd, env = self._wrap_sandbox(cmd, thread_id)

        return subprocess.Popen(
            cmd,
            stdout=open(stdout_file, "w"),
            stderr=subprocess.STDOUT,
            text=True,
            env=env
        )

# The daemon scans for this 'HANDLERS' object
HANDLERS = [TestAgentHandler()]
