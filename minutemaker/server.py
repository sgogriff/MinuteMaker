"""Local LLM server lifecycle management — start/stop/health check/model pull."""

import json
import logging
import signal
import subprocess
import time
import urllib.request
import urllib.error

logger = logging.getLogger("minutemaker")


class ServerManager:
    """Context manager that starts a local LLM server on entry and stops it on exit.

    Does nothing when:
    - provider is 'anthropic' (cloud, no local server needed)
    - managed_server is False (server managed externally)

    Usage:
        with ServerManager(config):
            response = provider.generate(...)
    """

    def __init__(self, config: dict):
        self.config = config
        self._process = None
        self._should_manage = (
            config.get("provider") != "anthropic"
            and config.get("managed_server", False)
            and config.get("server_command", "")
        )

    def __enter__(self):
        if self._should_manage:
            self.start()
        elif self.config.get("provider") != "anthropic":
            # Server is external but still check model availability
            self._ensure_model_available()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._should_manage:
            self.stop()
        return False

    def start(self) -> None:
        """Start the LLM server subprocess and wait for it to be ready."""
        cmd = self.config["server_command"]
        timeout = self.config.get("server_startup_timeout", 120)

        logger.info("Starting local LLM server: %s", cmd)

        self._process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN),
        )

        # Wait for the server to be ready
        if not self._wait_for_ready(timeout):
            self.stop()
            raise RuntimeError(
                f"Local LLM server did not start within {timeout}s. "
                f"Command: {cmd}"
            )

        logger.info("Local LLM server is ready")

        # Ensure the configured model is available
        self._ensure_model_available()

    def stop(self) -> None:
        """Stop the LLM server subprocess."""
        if self._process is None:
            return

        logger.info("Stopping local LLM server...")

        try:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Server did not stop gracefully, killing...")
                self._process.kill()
                self._process.wait(timeout=5)
        except Exception as exc:
            logger.warning("Error stopping server: %s", exc)
        finally:
            self._process = None
            logger.info("Local LLM server stopped")

    def is_running(self) -> bool:
        """Check if the server health endpoint responds."""
        base_url = self.config.get("base_url", "http://localhost:11434/v1")
        # Strip /v1 suffix to get the base URL for health check
        health_url = base_url.rstrip("/")
        if health_url.endswith("/v1"):
            health_url = health_url[:-3]
        health_url = health_url.rstrip("/") + "/api/tags"  # Ollama health endpoint

        try:
            req = urllib.request.Request(health_url, method="GET")
            with urllib.request.urlopen(req, timeout=5):
                return True
        except (urllib.error.URLError, OSError):
            return False

    def _ollama_base_url(self) -> str:
        """Get the Ollama native API base URL (without /v1)."""
        base_url = self.config.get("base_url", "http://localhost:11434/v1")
        url = base_url.rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        return url.rstrip("/")

    def _ensure_model_available(self) -> None:
        """Check if the configured model is available locally. Pull it if not."""
        model = self.config.get("model", "")
        if not model:
            return

        # List local models via Ollama API
        try:
            url = self._ollama_base_url() + "/api/tags"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            logger.debug("Could not check model availability, skipping auto-pull")
            return

        # Check if our model is in the list
        available = [m.get("name", "") for m in data.get("models", [])]
        # Ollama model names may or may not include a tag — match flexibly
        # e.g. "llama3:8b" matches "llama3:8b", "llama3" matches "llama3:latest"
        model_found = any(
            m == model or m.startswith(model + ":") or model.startswith(m + ":")
            for m in available
        )

        if model_found:
            logger.info("Model '%s' is available locally", model)
            return

        # Model not found — pull it
        logger.info(
            "Model '%s' not found locally. Pulling from Ollama registry "
            "(this may take a while on first run)...",
            model,
        )
        try:
            pull_url = self._ollama_base_url() + "/api/pull"
            payload = json.dumps({"name": model, "stream": False}).encode()
            req = urllib.request.Request(
                pull_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=600) as resp:
                resp.read()
            logger.info("Model '%s' pulled successfully", model)
        except Exception as exc:
            logger.error(
                "Failed to pull model '%s': %s. "
                "You can pull it manually with: ollama pull %s",
                model, exc, model,
            )
            raise RuntimeError(f"Model '{model}' is not available and auto-pull failed") from exc

    def _wait_for_ready(self, timeout: int) -> bool:
        """Poll until the server responds or timeout is reached."""
        deadline = time.time() + timeout
        interval = 1.0

        while time.time() < deadline:
            # Check if the process has crashed
            if self._process.poll() is not None:
                stderr = self._process.stderr.read().decode(errors="replace")
                logger.error("Server process exited early: %s", stderr[-500:])
                return False

            if self.is_running():
                return True

            time.sleep(interval)
            # Increase interval up to 5s to avoid excessive polling
            interval = min(interval * 1.5, 5.0)

        return False
