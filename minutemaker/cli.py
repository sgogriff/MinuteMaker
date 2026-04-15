"""Command-line interface and entry point."""

import argparse
import logging
import logging.handlers
import shutil
import sys
import time
from pathlib import Path

from watchdog.observers import Observer

from .config import (
    DEFAULT_CONFIG,
    list_templates,
    load_config,
    load_template_config,
)
from .pipeline import (
    MinutesHandler,
    build_json_system_prompt,
    build_latex_system_prompt,
    process_file,
)

logger = logging.getLogger("minutemaker")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="MinuteMaker — meeting notes to LaTeX/PDF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--config", default="config.yaml", help="Path to config file")
    p.add_argument("--input-dir", dest="input_dir", help="Override input directory")
    p.add_argument("--output-dir", dest="output_dir", help="Override output directory")
    p.add_argument("--template", help="Template name (directory under templates/)")
    p.add_argument(
        "--provider",
        choices=["anthropic", "openai_compatible"],
        help="LLM provider",
    )
    p.add_argument("--model", help="Override model name")
    p.add_argument("--base-url", dest="base_url", help="Base URL for OpenAI-compatible provider")
    p.add_argument("--log-level", dest="log_level", help="Override log level")
    p.add_argument(
        "--once",
        metavar="FILE",
        help="Process a single .txt file and exit (no watcher)",
    )
    p.add_argument(
        "--list-templates",
        action="store_true",
        help="List available templates and exit",
    )
    p.add_argument(
        "--init",
        action="store_true",
        help="Interactive setup: create config.yaml and directories",
    )
    return p.parse_args()


def setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    root.setLevel(level)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(ch)

    fh = logging.handlers.RotatingFileHandler(
        "minutemaker.log", maxBytes=5 * 1024 * 1024, backupCount=3
    )
    fh.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(fh)


def run_init() -> None:
    """Interactive setup wizard."""
    print("MinuteMaker — Setup\n")

    # List templates
    templates = list_templates()
    if not templates:
        print("No templates found. Please ensure a templates/ directory exists.")
        sys.exit(1)

    print("Available templates:")
    for i, t in enumerate(templates, 1):
        print(f"  {i}. {t['id']} — {t['name']}")

    # Template choice
    while True:
        choice = input(f"\nSelect template [1-{len(templates)}, default=1]: ").strip()
        if not choice:
            choice = "1"
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(templates):
                selected = templates[idx]
                break
        except ValueError:
            pass
        print("Invalid choice, try again.")

    print(f"\nSelected: {selected['name']}")

    # Provider choice
    print("\nLLM Provider:")
    print("  1. anthropic — Anthropic Claude API (cloud, requires ANTHROPIC_API_KEY)")
    print("  2. openai_compatible — Local or remote OpenAI-compatible API (Ollama, etc.)")

    while True:
        choice = input("\nSelect provider [1-2, default=1]: ").strip()
        if not choice:
            choice = "1"
        if choice == "1":
            provider = "anthropic"
            break
        elif choice == "2":
            provider = "openai_compatible"
            break
        print("Invalid choice, try again.")

    model = DEFAULT_CONFIG["model"]
    base_url = ""
    managed_server = False
    server_command = ""

    if provider == "openai_compatible":
        base_url = input(
            "\nBase URL [default: http://localhost:11434/v1]: "
        ).strip() or "http://localhost:11434/v1"
        model = input("\nModel name [default: llama3.1]: ").strip() or "llama3.1"

        manage = input(
            "\nShould MinuteMaker start/stop the server automatically? [y/N]: "
        ).strip().lower()
        if manage in ("y", "yes"):
            managed_server = True
            server_command = input(
                "Server start command [default: ollama serve]: "
            ).strip() or "ollama serve"

    # Write config.yaml
    config_lines = [
        "# MinuteMaker configuration",
        f"template: {selected['id']}",
        f"provider: {provider}",
        f"model: {model}",
        f"max_tokens: {DEFAULT_CONFIG['max_tokens']}",
        "input_dir: ./input",
        "output_dir: ./output",
        f"log_level: {DEFAULT_CONFIG['log_level']}",
    ]

    if provider == "openai_compatible":
        config_lines.append(f"base_url: {base_url}")
        if managed_server:
            config_lines.append(f"managed_server: true")
            config_lines.append(f'server_command: "{server_command}"')
            config_lines.append(f"server_startup_timeout: 120")

    config_path = Path("config.yaml")
    if config_path.exists():
        overwrite = input("\nconfig.yaml already exists. Overwrite? [y/N]: ").strip().lower()
        if overwrite not in ("y", "yes"):
            print("Aborted.")
            return

    config_path.write_text("\n".join(config_lines) + "\n")
    print(f"\nWritten: {config_path}")

    # Create directories
    Path("input").mkdir(exist_ok=True)
    Path("output").mkdir(exist_ok=True)
    print("Created: input/ and output/")

    # Create .env.example
    env_example = Path(".env.example")
    if not env_example.exists():
        if provider == "anthropic":
            env_example.write_text("ANTHROPIC_API_KEY=your-key-here\n")
        else:
            env_example.write_text(
                "# ANTHROPIC_API_KEY=your-key-here  # only needed for anthropic provider\n"
            )
        print(f"Created: {env_example}")

    # Next steps
    print("\n--- Setup complete ---\n")
    if provider == "anthropic":
        print("Next steps:")
        print("  1. Copy .env.example to .env and add your Anthropic API key")
        print("  2. Drop a .txt file into input/ or run:")
        print("     python minutemaker.py --once path/to/notes.txt")
    else:
        print("Next steps:")
        print(f"  1. Ensure your LLM server is accessible at {base_url}")
        if managed_server:
            print(f"     (MinuteMaker will start it automatically with: {server_command})")
        print("  2. Drop a .txt file into input/ or run:")
        print("     python minutemaker.py --once path/to/notes.txt")


def main() -> None:
    args = parse_args()

    # Handle --list-templates before logging setup
    if args.list_templates:
        templates = list_templates()
        if not templates:
            print("No templates found.")
        else:
            print("Available templates:")
            for t in templates:
                print(f"  {t['id']} — {t['name']}")
        return

    # Handle --init before logging setup
    if args.init:
        run_init()
        return

    # Set up logging
    setup_logging(args.log_level or DEFAULT_CONFIG["log_level"])

    from dotenv import load_dotenv
    load_dotenv()

    config = load_config(args)

    # Re-adjust log level if config changed it
    logging.getLogger().setLevel(
        getattr(logging, config["log_level"].upper(), logging.INFO)
    )

    # Check pdflatex
    if not shutil.which("pdflatex"):
        logger.error(
            "pdflatex not found — install TeX Live (Linux), MacTeX (macOS), "
            "or MiKTeX (Windows)"
        )
        sys.exit(1)

    # Load template
    template_config = load_template_config(config)

    # Ensure directories exist
    Path(config["input_dir"]).mkdir(parents=True, exist_ok=True)
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)

    # Build provider-specific prompts once
    system_prompts = {
        "json": build_json_system_prompt(config, template_config),
        "latex": build_latex_system_prompt(config, template_config),
    }
    logger.info(
        "System prompts built (json=%d chars, latex=%d chars)",
        len(system_prompts["json"]),
        len(system_prompts["latex"]),
    )

    # --once mode
    if args.once:
        once_path = Path(args.once)
        if not once_path.exists():
            logger.error("File not found: %s", once_path)
            sys.exit(1)
        process_file(str(once_path), config, template_config, system_prompts)
        return

    # Watcher mode
    handler = MinutesHandler(config, template_config, system_prompts)
    observer = Observer()
    observer.schedule(handler, config["input_dir"], recursive=False)
    observer.start()
    logger.info("Watching %s for .txt files (Ctrl+C to stop)", config["input_dir"])

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        observer.stop()
    observer.join()
