import subprocess

class BaseMailboxHandler:
    agent_tag = "[default-agent]" 
    agent_command = "default-agent"

    def execute(self, thread_id: str, prompt_file: str, stdout_file: str) -> subprocess.Popen:
        """Spawns the agent process and pipes output to stdout_file."""
        return subprocess.Popen(
            [self.agent_command, "--prompt-file", prompt_file],
            stdout=open(stdout_file, "w"),
            stderr=subprocess.STDOUT,
            text=True
        )

    def process_result(self, thread_id: str, stdout_file: str, original_body: str) -> tuple[str, list]:
        """
        Reads execution stdout and returns the reply text and a list of attachment paths.
        Override this to scan stdout for file paths to attach, etc.
        """
        try:
            with open(stdout_file, "r") as f:
                output = f.read()
        except FileNotFoundError:
            output = "[Agent produced no output file]"
        return output, []
