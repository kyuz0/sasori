import os
import json
import shutil
import subprocess
from pathlib import Path

class BaseMailboxHandler:
    agent_tag = "[default-agent]" 
    agent_command = "default-agent"
    
    # Sandbox Configuration
    sandbox_enabled = False
    sandbox_network_domains = []
    sandbox_env_whitelist = ["PATH", "HOME", "USER", "SHELL", "TERM"]
    sandbox_deny_workspace_patterns = []
    sandbox_deny_binaries = []

    def _wrap_sandbox(self, command: list, thread_id: str) -> tuple[list, dict]:
        settings_file = f"/tmp/thread_{thread_id}_srt.json"
        
        home = str(Path.home())
        deny_read = [
            home, 
            os.path.join(home, ".config"),
            os.path.join(home, ".ssh"),
            os.path.join(home, ".aws")
        ]
        deny_write = []
        cwd = str(Path.cwd())
        
        for pattern in self.sandbox_deny_workspace_patterns:
            for p in Path(cwd).rglob(pattern):
                deny_read.append(str(p))
                deny_write.append(str(p))
                
        for binary in self.sandbox_deny_binaries:
            if binary.startswith("/"):
                deny_read.append(binary)
            else:
                abs_path = shutil.which(binary)
                if abs_path:
                    deny_read.append(abs_path)
                    
        config = {
            "network": {
                "allowedDomains": self.sandbox_network_domains if self.sandbox_network_domains else ["sandbox.local"],
                "deniedDomains": []
            },
            "filesystem": {
                "denyRead": deny_read,
                "allowRead": [cwd, "/tmp"],
                "allowWrite": [cwd, "/tmp"],
                "denyWrite": deny_write
            }
        }
        
        import shlex
        
        with open(settings_file, "w") as f:
            json.dump(config, f)
            
        srt_path = shutil.which("srt") or "npx" # Default to npx if srt globally unavailable
        if srt_path == "npx":
            # Using local sandbox-runtime logic
            args_base = ["npx", "--yes", "@anthropic-ai/sandbox-runtime", "--settings", settings_file]
        else:
            args_base = [srt_path, "--settings", settings_file]
            
        command_str = " ".join(shlex.quote(str(arg)) for arg in command)
        wrapped_command = args_base + ["-c", command_str]
        
        safe_env = {}
        for key in self.sandbox_env_whitelist:
            if key in os.environ:
                safe_env[key] = os.environ[key]
                
        return wrapped_command, safe_env

    def execute(self, thread_id: str, prompt_file: str, stdout_file: str) -> subprocess.Popen:
        """Spawns the agent process and pipes output to stdout_file."""
        cmd = [self.agent_command, "--prompt-file", prompt_file]
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
