"""Configuration loading and template management."""

import logging
import sys
from pathlib import Path

import yaml

logger = logging.getLogger("minutemaker")

DEFAULT_CONFIG = {
    "input_dir": "./input",
    "output_dir": "./output",
    "template": "default",
    "provider": "anthropic",
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 8192,
    "log_level": "INFO",
    # Local LLM server management
    "base_url": "",
    "api_key": "",
    "managed_server": False,
    "server_command": "",
    "server_startup_timeout": 120,
}


def _find_templates_dir() -> Path:
    """Locate the templates/ directory relative to this package."""
    # Check relative to the package first (installed location)
    pkg_dir = Path(__file__).resolve().parent
    templates = pkg_dir.parent / "templates"
    if templates.is_dir():
        return templates
    # Fallback: relative to CWD (development location)
    cwd_templates = Path.cwd() / "templates"
    if cwd_templates.is_dir():
        return cwd_templates
    return templates  # return the package-relative path even if missing


def load_config(args) -> dict:
    """Merge defaults <- config.yaml <- CLI args."""
    config = dict(DEFAULT_CONFIG)

    # Layer 2: config.yaml
    config_path = Path(args.config)
    if config_path.exists():
        with open(config_path) as f:
            file_cfg = yaml.safe_load(f) or {}
        config.update({k: v for k, v in file_cfg.items() if v is not None})
        logger.info("Loaded config from %s", config_path)
    else:
        logger.info("No config file at %s, using defaults", config_path)

    # Layer 3: CLI overrides
    cli_fields = [
        "input_dir", "output_dir", "template", "provider",
        "model", "base_url", "log_level",
    ]
    for field in cli_fields:
        val = getattr(args, field.replace("-", "_"), None)
        if val is not None:
            config[field] = val

    # Resolve directory paths
    for key in ("input_dir", "output_dir"):
        config[key] = str(Path(config[key]).resolve())

    # Resolve template directory
    templates_root = _find_templates_dir()
    template_dir = templates_root / config["template"]
    config["template_dir"] = str(template_dir)

    return config


def load_template_config(config: dict) -> dict:
    """Load and return the template.yaml for the selected template."""
    template_dir = Path(config["template_dir"])
    yaml_path = template_dir / "template.yaml"

    if not yaml_path.exists():
        logger.error("Template config not found at %s", yaml_path)
        logger.error(
            "Available templates: %s",
            ", ".join(
                d.name
                for d in _find_templates_dir().iterdir()
                if d.is_dir() and (d / "template.yaml").exists()
            ),
        )
        sys.exit(1)

    with open(yaml_path) as f:
        template_config = yaml.safe_load(f)

    logger.info("Loaded template: %s", template_config.get("name", config["template"]))
    return template_config


def load_template_spec(config: dict) -> str:
    """Load TEMPLATE_SPEC.md for the selected template."""
    template_dir = Path(config["template_dir"])
    spec_path = template_dir / "TEMPLATE_SPEC.md"

    if not spec_path.exists():
        logger.error("Template spec not found at %s", spec_path)
        sys.exit(1)

    text = spec_path.read_text(encoding="utf-8")
    logger.info("Loaded template spec (%d chars)", len(text))
    return text


def load_prompt_rules(config: dict) -> str:
    """Load prompt_rules.md for the selected template. Returns empty string if not found."""
    template_dir = Path(config["template_dir"])
    rules_path = template_dir / "prompt_rules.md"

    if not rules_path.exists():
        return ""

    text = rules_path.read_text(encoding="utf-8")
    logger.info("Loaded prompt rules (%d chars)", len(text))
    return text


def list_templates() -> list[dict]:
    """List all available templates with their names."""
    templates_root = _find_templates_dir()
    result = []
    if not templates_root.is_dir():
        return result
    for d in sorted(templates_root.iterdir()):
        yaml_path = d / "template.yaml"
        if d.is_dir() and yaml_path.exists():
            with open(yaml_path) as f:
                tc = yaml.safe_load(f)
            result.append({
                "id": d.name,
                "name": tc.get("name", d.name),
            })
    return result
