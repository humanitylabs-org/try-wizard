"""Runs INSIDE the hermes-agent app's engine container (stock Hermes), started by the onboarding server with
`docker exec -i -u hermes <engine> python -c <this file> <command>`. Secrets arrive on stdin, never in argv.

Commands (one JSON object per output line):
  free            mint the Nous free-tier guest identity and use it
  apikey          stdin {"provider": "anthropic"|"openrouter", "key": "..."}
  codex           ChatGPT device login: prints {"status":"waiting","userCode":...}, then {"status":"signed-in",...}
  soul            stdin {"name": "..."}: write SOUL.md
"""
import json
import os
import sys

sys.path.insert(0, "/opt/hermes")
API_KEY_PROVIDERS = {
    "anthropic": {"env": "ANTHROPIC_API_KEY", "base_url": "https://api.anthropic.com", "label": "Anthropic"},
    "openrouter": {"env": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1", "label": "OpenRouter"},
}
CODEX_DEVICE_URL = "https://auth.openai.com/codex/device"


def say(obj):
    print(json.dumps(obj), flush=True)


def set_model(provider, base_url, model):
    from hermes_cli.auth import _update_config_for_provider
    from hermes_cli.config import atomic_config_write, get_config_path, read_raw_config
    _update_config_for_provider(provider, base_url, default_model=model)
    config = read_raw_config() or {}
    model_cfg = dict(config.get("model") or {})
    model_cfg["default"] = model
    model_cfg["provider"] = provider
    config["model"] = model_cfg
    atomic_config_write(get_config_path(), config)


def default_model(provider):
    from hermes_cli.models import _PROVIDER_MODELS
    if provider == "openrouter":
        options = _PROVIDER_MODELS.get("nous") or []
        return options[0] if options else "anthropic/claude-opus-4.6"
    options = _PROVIDER_MODELS.get(provider) or []
    if not options:
        raise RuntimeError(f"No default model is known for {provider}.")
    return options[0]


def free():
    os.environ["HERMES_GUEST_ONBOARDING"] = "1"
    from hermes_cli.anon_auth import GUEST_MODEL
    from hermes_cli.config import save_env_value
    from hermes_cli.free_tier_bootstrap import run_bootstrap
    record = run_bootstrap(announce=False)
    if not getattr(record, "has_identity", False):
        raise RuntimeError(getattr(record, "error", "") or "The free tier is not available right now.")
    # The gateway reads the launch gate from its .env on every start.
    save_env_value("HERMES_GUEST_ONBOARDING", "1")
    set_model("nous", "", GUEST_MODEL)
    say({"kind": "free", "provider": "nous", "model": GUEST_MODEL, "label": "Free starter brain"})


def apikey():
    body = json.loads(sys.stdin.read() or "{}")
    spec = API_KEY_PROVIDERS.get(str(body.get("provider", "")))
    if not spec:
        raise RuntimeError("Choose Anthropic or OpenRouter.")
    key = str(body.get("key", "")).strip()
    if len(key) < 20 or any(ch.isspace() for ch in key):
        raise RuntimeError("That key doesn't look right. Paste the whole key.")
    from hermes_cli.config import save_env_value
    save_env_value(spec["env"], key)
    os.environ[spec["env"]] = key
    provider = str(body["provider"])
    model = default_model(provider)
    set_model(provider, spec["base_url"], model)
    say({"kind": "apikey", "provider": provider, "model": model, "label": f"{spec['label']} key"})


def codex():
    from hermes_cli.auth import _utc_now_z
    from hermes_cli.auth_codex import (_codex_base_url, _codex_exchange_authorization_code,
                                       _codex_poll_authorization_code, _codex_request_device_code,
                                       _save_codex_tokens)
    from hermes_cli.auth_constants import CODEX_OAUTH_CLIENT_ID
    issuer = "https://auth.openai.com"
    device = _codex_request_device_code(issuer, CODEX_OAUTH_CLIENT_ID)
    say({"status": "waiting", "userCode": device["user_code"], "url": CODEX_DEVICE_URL})
    code = _codex_poll_authorization_code(issuer, device_auth_id=device["device_auth_id"],
                                          user_code=device["user_code"], poll_interval=device["interval"])
    tokens = _codex_exchange_authorization_code(issuer, CODEX_OAUTH_CLIENT_ID, code)
    _save_codex_tokens({"access_token": tokens.get("access_token", ""),
                        "refresh_token": tokens.get("refresh_token", "")}, _utc_now_z())
    model = default_model("openai-codex")
    set_model("openai-codex", _codex_base_url(), model)
    say({"status": "signed-in", "brain": {"kind": "chatgpt", "provider": "openai-codex", "model": model,
                                           "label": "ChatGPT account"}})


def soul():
    name = " ".join(str(json.loads(sys.stdin.read() or "{}").get("name", "")).split())[:40] or "Wizard"
    from hermes_constants import get_hermes_home
    path = get_hermes_home() / "SOUL.md"
    path.write_text(
        f"# {name}\n\n"
        f"You are {name}, the user's personal AI wizard. You live on Wizard OS, a small computer running inside "
        "the user's Mac, together with the apps installed there (Files, Transcriber, Browser, Secret Drop and any the "
        "user adds from the App Store). The user's files are in their Wizard folder (~/Wizard on the Mac): Inbox, "
        "Documents, Videos, Meetings and Exports.\n\n"
        "Be warm, direct, and capable. Prefer doing over describing: when the user asks for something you can do, "
        "do it, then report what happened in plain words.\n")
    say({"ok": True, "name": name})


if __name__ == "__main__":
    try:
        {"free": free, "apikey": apikey, "codex": codex, "soul": soul}[sys.argv[1]]()
    except Exception as error:  # surfaced to the onboarding page
        say({"error": str(error) or error.__class__.__name__})
        sys.exit(1)
