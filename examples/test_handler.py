import subprocess
from sasori.handler import BaseMailboxHandler

class TestAgentHandler(BaseMailboxHandler):
    # To test this agent, send an email with a subject like: "[test-agent] Hello!"
    agent_tag = "[test-agent]" 
    # Use standard python execution to bypass the need for a globally installed dummy executable
    agent_command = "python3"

    def execute(self, thread_id: str, prompt_file: str, stdout_file: str) -> subprocess.Popen:
        """
        Usually this runs your pipx command.
        For the test agent, we simulate a 60 second job with status outputs every 10 seconds.
        """
        script = """import time, sys
for i in range(6):
    print(f'Running step {i+1}/6 (elapsed: {i*10}s)...', flush=True)
    time.sleep(10)
print('Test Agent: DONE', flush=True)
"""
        return subprocess.Popen(
            [self.agent_command, "-c", script],
            stdout=open(stdout_file, "w"),
            stderr=subprocess.STDOUT,
            text=True
        )

# The daemon scans for this 'HANDLERS' object
HANDLERS = [TestAgentHandler()]
