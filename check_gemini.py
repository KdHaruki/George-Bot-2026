"""List generation models using the Bot's key; never print credentials."""

import os
import argparse
import re
from functools import partial
from google import genai
from google.genai import errors, types
from george_chat import describe_chat_error

# Render must receive diagnostics immediately, even with buffered stdout.
print = partial(print, flush=True)


def safe_provider_message(exc):
    """Only for fixed-prompt diagnostics, never for Discord conversations."""
    if not isinstance(exc, errors.APIError):
        return "No provider message (transport or local error)."
    message = str(exc.message or "")
    for variable in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "DISCORD_TOKEN"):
        secret = os.getenv(variable, "").strip()
        if secret:
            message = message.replace(secret, "[REDACTED]")
    message = re.sub(r"AIza[\w-]+", "[REDACTED]", message)
    message = re.sub(r"(?i)(key|token|authorization)\s*[=:]\s*[^\s&,;]+", r"\1=[REDACTED]", message)
    return message.replace("\n", " ").replace("\r", " ")[:1500]


def main(test=False):
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        print("GEMINI_API_KEY is not set in this environment.")
        return 1
    selected = os.getenv("GEMINI_MODEL", "").strip() or "gemini-flash-latest"
    names = []
    try:
        with genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30000)) as client:
            if test:
                print("Diagnostic version: 2; fixed prompt; no Discord history")
                print("Configured model: " + repr(selected))
                result = client.models.generate_content(
                    model=selected, contents="Reply with OK.",
                    config=types.GenerateContentConfig(max_output_tokens=2048),
                )
                print("Generation succeeded; text returned: " + str(bool(result.text)))
                return 0
            for model in client.models.list():
                if "generateContent" in (model.supported_actions or []):
                    names.append((model.name or "").removeprefix("models/"))
    except Exception as exc:
        diagnostic, _ = describe_chat_error(exc)
        print("Diagnostic failed: " + diagnostic)
        print("Provider message: " + safe_provider_message(exc))
        return 1
    print("Models advertising generateContent (generation is not tested):")
    for name in sorted(names):
        print(name)
    print("Configured model is listed: " + str(selected.removeprefix("models/") in names))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Send one fixed prompt; consumes API quota and applicable charges.")
    args = parser.parse_args()
    raise SystemExit(main(test=args.test))
