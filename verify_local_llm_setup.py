#!/usr/bin/env python3
"""Verify a local LLM MinuteMaker setup before enabling cron or other automation."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"
DEFAULT_SAMPLE_FILE = REPO_ROOT / "exampledata" / "testing_minutes.txt"


class CheckRunner:
    """Collect and print pass/fail/skip results."""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def pass_(self, name: str, detail: str) -> None:
        self.passed += 1
        print(f"[PASS] {name}: {detail}")

    def fail(self, name: str, detail: str) -> None:
        self.failed += 1
        print(f"[FAIL] {name}: {detail}")

    def skip(self, name: str, detail: str) -> None:
        self.skipped += 1
        print(f"[SKIP] {name}: {detail}")

    @staticmethod
    def note(detail: str) -> None:
        print(f"[INFO] {detail}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run staged checks for MinuteMaker local LLM mode, including a live "
            "API check and a watcher smoke test."
        )
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the MinuteMaker config file (default: %(default)s)",
    )
    parser.add_argument(
        "--sample-file",
        default=str(DEFAULT_SAMPLE_FILE),
        help="Sample .txt file to drop into the watcher test (default: %(default)s)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run preflight checks and the live API test, but skip the watcher smoke test",
    )
    parser.add_argument(
        "--watcher-timeout",
        type=int,
        default=900,
        help="Seconds to wait for the watcher smoke test to finish (default: %(default)s)",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the temporary watcher test directory even if all checks pass",
    )
    return parser.parse_args()


def resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def check_python(runner: CheckRunner) -> str | None:
    if sys.version_info < (3, 10):
        runner.fail(
            "Python",
            f"MinuteMaker needs Python 3.10+, but this interpreter is {sys.version.split()[0]}",
        )
        return None

    runner.pass_("Python", f"{sys.version.split()[0]} ({sys.executable})")
    return sys.executable


def check_runtime_imports(runner: CheckRunner) -> tuple[object, object] | tuple[None, None]:
    try:
        import dotenv
        import openai
        import watchdog
        import yaml
    except Exception as exc:
        runner.fail(
            "Dependencies",
            "Could not import the Python packages MinuteMaker needs. "
            f"Activate the virtual environment and run `pip install -r requirements.txt`. Error: {exc}",
        )
        return None, None

    runner.pass_(
        "Dependencies",
        "Imported openai, PyYAML, watchdog, and python-dotenv successfully",
    )
    return yaml, openai


def check_pdflatex(runner: CheckRunner) -> str | None:
    pdflatex_path = shutil.which("pdflatex")
    if not pdflatex_path:
        runner.fail(
            "pdflatex",
            "Not found on PATH. Install TeX Live, MacTeX, or MiKTeX before enabling automation.",
        )
        return None

    runner.pass_("pdflatex", pdflatex_path)
    return pdflatex_path


def load_app_modules():
    from minutemaker.config import load_config, load_template_config
    from minutemaker.server import ServerManager

    return load_config, load_template_config, ServerManager


def load_effective_config(config_path: Path, load_config, load_template_config) -> tuple[dict, dict]:
    args = SimpleNamespace(
        config=str(config_path),
        input_dir=None,
        output_dir=None,
        template=None,
        provider=None,
        model=None,
        base_url=None,
        log_level=None,
    )
    config = load_config(args)
    template_config = load_template_config(config)
    return config, template_config


def resolve_server_binary(server_command: str) -> tuple[str | None, str | None]:
    if not server_command.strip():
        return None, None

    try:
        parts = shlex.split(server_command)
    except ValueError:
        return None, None

    if not parts:
        return None, None

    binary = parts[0]
    if os.path.isabs(binary):
        return binary, binary

    return binary, shutil.which(binary)


def check_local_config(
    runner: CheckRunner,
    config_path: Path,
    sample_file: Path,
    load_config,
    load_template_config,
) -> tuple[dict | None, dict | None, str | None]:
    if not config_path.exists():
        runner.fail(
            "Config file",
            f"{config_path} was not found. Run `python minutemaker.py --init` first.",
        )
        return None, None, None

    if not sample_file.exists():
        runner.fail("Sample file", f"{sample_file} was not found")
        return None, None, None

    try:
        config, template_config = load_effective_config(
            config_path,
            load_config,
            load_template_config,
        )
    except Exception as exc:
        runner.fail("Config load", f"Could not load {config_path}: {exc}")
        return None, None, None

    if config.get("provider") != "openai_compatible":
        runner.fail(
            "Provider",
            "This verifier is for local LLM mode. Set `provider: openai_compatible` "
            f"in {config_path.name} first (current value: {config.get('provider')!r}).",
        )
        return None, None, None

    model = config.get("model", "").strip()
    if not model:
        runner.fail("Model", f"No model is configured in {config_path.name}")
        return None, None, None

    base_url = config.get("base_url", "").strip()
    if not base_url:
        runner.fail("Base URL", f"No `base_url` is configured in {config_path.name}")
        return None, None, None

    managed_server = bool(config.get("managed_server", False))
    server_command = str(config.get("server_command", "") or "")
    server_binary, resolved_server_binary = resolve_server_binary(server_command)

    summary = (
        f"template={config['template']}, model={model}, base_url={base_url}, "
        f"managed_server={managed_server}"
    )
    runner.pass_("Config", summary)

    if managed_server:
        if not server_command.strip():
            runner.fail(
                "Server command",
                "`managed_server: true` is set, but `server_command` is empty.",
            )
            return None, None, None

        if resolved_server_binary:
            detail = f"{server_command} (resolved binary: {resolved_server_binary})"
            runner.pass_("Server command", detail)
        elif server_binary:
            runner.pass_(
                "Server command",
                f"{server_command} (binary could not be resolved ahead of time; live test will confirm it)",
            )
        else:
            runner.pass_(
                "Server command",
                f"{server_command} (using shell syntax; live test will confirm it)",
            )
    else:
        runner.pass_(
            "Server mode",
            "MinuteMaker will not start the LLM server for you; the live test will check the configured base_url directly",
        )

    runner.pass_("Template", template_config.get("name", config["template"]))
    return config, template_config, resolved_server_binary


def run_live_api_check(
    runner: CheckRunner,
    config: dict,
    openai_module,
    ServerManager,
) -> bool:
    runner.note(
        "Running a live local-LLM check. The first run may take a while if Ollama needs to download the model."
    )

    live_config = dict(config)
    live_config["max_tokens"] = min(int(config.get("max_tokens", 256)), 64)

    try:
        with ServerManager(live_config):
            client = openai_module.OpenAI(
                base_url=live_config.get("base_url", "http://localhost:11434/v1"),
                api_key=live_config.get("api_key", "not-needed") or "not-needed",
                timeout=60.0,
            )
            response = client.chat.completions.create(
                model=live_config["model"],
                max_tokens=live_config["max_tokens"],
                temperature=0,
                messages=[
                    {
                        "role": "system",
                        "content": "Reply with the single word OK.",
                    },
                    {
                        "role": "user",
                        "content": "Return only OK.",
                    },
                ],
            )
    except Exception as exc:
        runner.fail(
            "Live API check",
            "The local model could not answer a minimal test prompt. "
            f"Check Ollama, the configured model, and the base_url. Error: {exc}",
        )
        return False

    message = (response.choices[0].message.content or "").strip()
    if not message:
        runner.fail("Live API check", "The model returned an empty response")
        return False

    snippet = " ".join(message.split())[:80]
    runner.pass_("Live API check", f"Model responded successfully: {snippet!r}")
    return True


def build_temp_config(original_config: dict, input_dir: Path, output_dir: Path) -> dict:
    temp_config = {
        "template": original_config["template"],
        "provider": original_config["provider"],
        "model": original_config["model"],
        "max_tokens": original_config["max_tokens"],
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "log_level": original_config.get("log_level", "INFO"),
        "base_url": original_config.get("base_url", ""),
        "api_key": original_config.get("api_key", ""),
        "managed_server": bool(original_config.get("managed_server", False)),
    }

    if original_config.get("managed_server", False):
        temp_config["server_command"] = original_config.get("server_command", "")
        temp_config["server_startup_timeout"] = original_config.get(
            "server_startup_timeout", 120
        )

    return temp_config


def tail_text(path: Path, max_lines: int = 40) -> str:
    if not path.exists():
        return "(log file not found)"

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return "(log file is empty)"

    return "\n".join(lines[-max_lines:])


def wait_for_phrase(log_path: Path, phrase: str, timeout: int, proc: subprocess.Popen) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8", errors="replace")
            if phrase in text:
                return True
        time.sleep(1)
    return False


def wait_for_output(output_dir: Path, timeout: int, proc: subprocess.Popen) -> tuple[Path | None, Path | None]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        pdfs = sorted(output_dir.glob("*.pdf"))
        texs = sorted(output_dir.glob("*.tex"))
        if pdfs and texs and pdfs[0].stat().st_size > 0 and texs[0].stat().st_size > 0:
            return pdfs[0], texs[0]
        if proc.poll() is not None:
            return None, None
        time.sleep(2)
    return None, None


def stop_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return

    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)


def run_watcher_smoke_test(
    runner: CheckRunner,
    config: dict,
    yaml_module,
    sample_file: Path,
    watcher_timeout: int,
) -> Path | None:
    runner.note(
        "Running a full watcher smoke test in a temporary directory. This exercises the same path a cron-launched watcher would use."
    )

    temp_root = Path(tempfile.mkdtemp(prefix="minutemaker_local_check_"))
    input_dir = temp_root / "input"
    output_dir = temp_root / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_config = build_temp_config(config, input_dir, output_dir)
    temp_config_path = temp_root / "config.local-check.yaml"
    temp_config_path.write_text(
        yaml_module.safe_dump(temp_config, sort_keys=False),
        encoding="utf-8",
    )

    watcher_log = temp_root / "watcher.stdout.log"
    cmd = [
        sys.executable,
        str(REPO_ROOT / "minutemaker.py"),
        "--config",
        str(temp_config_path),
    ]

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{REPO_ROOT}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(REPO_ROOT)
    )

    proc = None
    try:
        with watcher_log.open("w", encoding="utf-8") as log_handle:
            proc = subprocess.Popen(
                cmd,
                cwd=temp_root,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )

        if not wait_for_phrase(watcher_log, "Watching", 60, proc):
            raise RuntimeError(
                "Watcher did not reach the ready state.\n\n"
                f"Recent output:\n{tail_text(watcher_log)}"
            )

        time.sleep(2)

        target_file = input_dir / "verification_notes.txt"
        target_file.write_text(sample_file.read_text(encoding="utf-8"), encoding="utf-8")

        pdf_path, tex_path = wait_for_output(output_dir, watcher_timeout, proc)
        if not pdf_path or not tex_path:
            raise RuntimeError(
                "No PDF/TEX output appeared before the timeout.\n\n"
                f"Recent output:\n{tail_text(watcher_log)}"
            )

        time.sleep(2)
        runner.pass_(
            "Watcher smoke test",
            f"Processed a dropped file successfully and created {pdf_path.name} and {tex_path.name}",
        )
        return temp_root

    except Exception as exc:
        runner.fail(
            "Watcher smoke test",
            f"{exc}\n\nTemporary test directory preserved at: {temp_root}",
        )
        return temp_root

    finally:
        if proc is not None:
            stop_process(proc)


def print_cron_notes(
    python_path: str | None,
    pdflatex_path: str | None,
    resolved_server_binary: str | None,
) -> None:
    print("\nCron-safe paths:")
    if python_path:
        print(f"- Python: {python_path}")
    if pdflatex_path:
        print(f"- pdflatex: {pdflatex_path}")
    if resolved_server_binary:
        print(f"- Ollama/server binary: {resolved_server_binary}")
        print(
            "- If cron cannot find Ollama, use the absolute binary path in "
            "`server_command`, for example: "
            f'"{resolved_server_binary} serve"'
        )
    print(
        "- When you create the cron entry, use absolute paths for the Python "
        "interpreter, the repo directory, and any server command."
    )


def main() -> int:
    args = parse_args()
    runner = CheckRunner()

    config_path = resolve_path(args.config)
    sample_file = resolve_path(args.sample_file)

    print("MinuteMaker local LLM verifier\n")
    print(f"Repo:   {REPO_ROOT}")
    print(f"Config: {config_path}")
    print(f"Sample: {sample_file}\n")

    python_path = check_python(runner)
    yaml_module, openai_module = check_runtime_imports(runner)
    pdflatex_path = check_pdflatex(runner)

    config = None
    resolved_server_binary = None
    temp_root = None

    if yaml_module is None:
        runner.skip("Config", "Skipped because required Python dependencies could not be imported")
    else:
        try:
            load_config, load_template_config, ServerManager = load_app_modules()
        except Exception as exc:
            runner.fail("MinuteMaker imports", f"Could not import the app modules: {exc}")
            ServerManager = None
            load_config = None
            load_template_config = None

        if load_config and load_template_config:
            config, _template_config, resolved_server_binary = check_local_config(
                runner,
                config_path,
                sample_file,
                load_config,
                load_template_config,
            )
        else:
            runner.skip("Config", "Skipped because MinuteMaker modules could not be imported")

        if config and ServerManager and openai_module:
            run_live_api_check(runner, config, openai_module, ServerManager)
        else:
            runner.skip(
                "Live API check",
                "Skipped because the config or runtime modules were not ready",
            )

        if args.quick:
            runner.skip(
                "Watcher smoke test",
                "Skipped because --quick was requested",
            )
        elif config and yaml_module and runner.failed == 0:
            temp_root = run_watcher_smoke_test(
                runner,
                config,
                yaml_module,
                sample_file,
                args.watcher_timeout,
            )
        else:
            runner.skip(
                "Watcher smoke test",
                "Skipped because an earlier check failed",
            )

    if temp_root and args.keep_temp:
        runner.note(f"Temporary watcher test directory kept at: {temp_root}")
    elif temp_root and runner.failed == 0:
        shutil.rmtree(temp_root, ignore_errors=True)

    print_cron_notes(python_path, pdflatex_path, resolved_server_binary)

    print("\nSummary:")
    print(f"- Passed: {runner.passed}")
    print(f"- Failed: {runner.failed}")
    print(f"- Skipped: {runner.skipped}")

    if runner.failed == 0:
        print(
            "\nEverything needed for local LLM mode looks healthy. "
            "You can now enable cron or another startup method with much more confidence."
        )
        return 0

    print(
        "\nOne or more checks failed. Fix those items first, then rerun "
        "`python verify_local_llm_setup.py`."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
