"""List generation models using the Bot's key; never print credentials."""

import os
from google import genai
from google.genai import types
from george_chat import describe_chat_error


def main():
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        print("GEMINI_API_KEY is not set in this environment.")
        return 1
    selected = os.getenv("GEMINI_MODEL", "").strip() or "gemini-flash-latest"
    names = []
    try:
        with genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30000)) as client:
            for model in client.models.list():
                if "generateContent" in (model.supported_actions or []):
                    names.append((model.name or "").removeprefix("models/"))
    except Exception as exc:
        diagnostic, _ = describe_chat_error(exc)
        print("Model listing failed: " + diagnostic)
        return 1
    print("Models advertising generateContent (generation is not tested):")
    for name in sorted(names):
        print(name)
    print("Configured model is listed: " + str(selected.removeprefix("models/") in names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
