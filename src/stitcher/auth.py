"""Credential resolution chain.

Resolution order (first match wins):
  1. Explicit environment variable (GITHUB_TOKEN, ANTHROPIC_API_KEY, etc.)
  2. .env file in current directory
  3. gh CLI auth token (GitHub only, with user notification)
  4. System keychain (macOS Keychain, Linux secret-service, Windows Credential Manager)
  5. Interactive prompt (asks user, offers to save to keychain)

The principle: use what the user has already put in your path.
Don't go looking for things they didn't offer you.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

logger = logging.getLogger("stitcher.auth")

KEYCHAIN_SERVICE = "stitcher-scout"


def resolve_github_token(*, interactive: bool = False, verbose: bool = False) -> str | None:
    """Resolve GitHub token through the credential chain."""

    # 1. Environment variable (includes .env via pydantic-settings)
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        if verbose:
            logger.info("Using GITHUB_TOKEN from environment")
        return token

    # 2. gh CLI auth
    token = _get_gh_token()
    if token:
        if verbose:
            logger.info("Using GitHub token from gh CLI")
        return token

    # 3. System keychain
    token = _keychain_get("github_token")
    if token:
        if verbose:
            logger.info("Using GitHub token from system keychain")
        return token

    # 4. Interactive prompt (only in CLI context)
    if interactive:
        return _prompt_github_token()

    return None


def resolve_llm_key(model: str, *, interactive: bool = False, verbose: bool = False) -> str | None:
    """Resolve the LLM API key for the given model."""
    from .config import _MODEL_KEY_MAP

    model_lower = model.lower()
    env_var = ""
    for prefix, key_name in _MODEL_KEY_MAP.items():
        if model_lower.startswith(prefix):
            env_var = key_name
            break

    # Local models don't need a key
    if not env_var:
        return ""

    # 1. Environment variable (includes .env)
    key = os.environ.get(env_var)
    if key:
        if verbose:
            logger.info(f"Using {env_var} from environment")
        return key

    # 2. System keychain
    key = _keychain_get(env_var.lower())
    if key:
        if verbose:
            logger.info(f"Using {env_var} from system keychain")
        # Set in environment so litellm picks it up
        os.environ[env_var] = key
        return key

    # 3. Interactive prompt
    if interactive:
        return _prompt_llm_key(env_var, model)

    return None


def save_to_keychain(key_name: str, value: str) -> bool:
    """Save a credential to the system keychain. Returns True on success."""
    try:
        import keyring
        keyring.set_password(KEYCHAIN_SERVICE, key_name, value)
        return True
    except ImportError:
        logger.debug("keyring not installed — cannot save to system keychain")
        return False
    except Exception as e:
        logger.debug(f"Failed to save to keychain: {e}")
        return False


def _keychain_get(key_name: str) -> str | None:
    """Read a credential from the system keychain."""
    try:
        import keyring
        value = keyring.get_password(KEYCHAIN_SERVICE, key_name)
        return value if value else None
    except ImportError:
        return None
    except Exception:
        return None


def _get_gh_token() -> str | None:
    """Get the GitHub token from the gh CLI, if installed and authenticated."""
    if not shutil.which("gh"):
        return None

    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _prompt_github_token() -> str | None:
    """Interactively prompt for a GitHub token."""
    from rich.console import Console
    from rich.prompt import Confirm, Prompt

    console = Console(stderr=True)
    console.print("\n[bold]GitHub token required[/bold]")
    console.print(
        "Create one at [link=https://github.com/settings/personal-access-tokens/new]"
        "github.com/settings/tokens[/link] (read-only public repo access)\n"
    )

    token = Prompt.ask("  GitHub token", console=console)
    if not token.strip():
        return None

    token = token.strip()

    if _try_save_to_keychain("github_token", token, console):
        os.environ["GITHUB_TOKEN"] = token

    return token


def _prompt_llm_key(env_var: str, model: str) -> str | None:
    """Interactively prompt for an LLM API key."""
    from rich.console import Console
    from rich.prompt import Prompt

    console = Console(stderr=True)
    console.print(f"\n[bold]{env_var} required[/bold] for model '{model}'")

    key = Prompt.ask(f"  {env_var}", console=console)
    if not key.strip():
        return None

    key = key.strip()

    if _try_save_to_keychain(env_var.lower(), key, console):
        os.environ[env_var] = key

    return key


def _try_save_to_keychain(key_name: str, value: str, console) -> bool:
    """Try to save to keychain, asking the user first."""
    from rich.prompt import Confirm

    try:
        import keyring  # noqa: F401
    except ImportError:
        console.print("  [dim]Tip: pip install keyring to save credentials securely[/dim]")
        return True  # still set env var

    if Confirm.ask("  Save to system keychain?", console=console, default=True):
        if save_to_keychain(key_name, value):
            console.print("  [green]Saved to keychain[/green]")
            return True
        else:
            console.print("  [yellow]Could not save to keychain[/yellow]")
    return True  # still set env var
