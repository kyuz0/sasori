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
        For the test agent, we simply run python to write 'Test Agent: OK' into the stdout file.
        """
        return subprocess.Popen(
            [self.agent_command, "-c", "print('Test Agent: OK')"],
            stdout=open(stdout_file, "w"),
            stderr=subprocess.STDOUT,
            text=True
        )

# The daemon scans for this 'HANDLERS' object
HANDLERS = [TestAgentHandler()]
