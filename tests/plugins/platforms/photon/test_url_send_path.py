"""Native Markdown must retain formatting whether or not it contains URLs.

The installed Spectrum renderer emits text plus UTF-16 formatting ranges for
Markdown; URLs do not require opting out of those ranges. Explicit plain-text
requests still remain plain. Execute the actual sidecar routing module.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

_MODULE = Path("plugins/platforms/photon/sidecar/send-format.mjs").resolve()

_CASES = {
    "markdown_without_url": ("markdown", "**bold** and `code`", "markdown"),
    "markdown_with_https_url": (
        "markdown", "see **this**: https://example.com/a?b=1", "markdown",
    ),
    "markdown_with_http_url": ("markdown", "http://example.com", "markdown"),
    "markdown_labeled_link": (
        "markdown", "**Source:** [docs](https://example.com/docs)", "markdown",
    ),
    "markdown_uppercase_scheme": (
        "markdown", "HTTPS://EXAMPLE.COM is **loud**", "markdown",
    ),
    "markdown_emoji_and_link": (
        "markdown", "☀️ **Today**\n• 🧘 *Read* [source](https://example.com)", "markdown",
    ),
    "explicit_plain_text": ("text", "**literal asterisks**", "text"),
    "explicit_plain_text_with_url": (
        "text", "https://example.com", "text",
    ),
}


@pytest.fixture(scope="module")
def verdicts():
    harness = (
        f"import {{ chooseSendFormat }} from {json.dumps(_MODULE.as_uri())};\n"
        "const chunks = [];\n"
        "process.stdin.on('data', (c) => chunks.push(c));\n"
        "process.stdin.on('end', () => {\n"
        "  const cases = JSON.parse(Buffer.concat(chunks).toString('utf-8'));\n"
        "  const out = {};\n"
        "  for (const [name, [format, text]] of Object.entries(cases)) {\n"
        "    out[name] = chooseSendFormat(format, text);\n"
        "  }\n"
        "  process.stdout.write(JSON.stringify(out));\n"
        "});\n"
    )
    payload = {name: [fmt, text] for name, (fmt, text, _) in _CASES.items()}
    run = subprocess.run(
        ["node", "--input-type=module", "-e", harness],
        input=json.dumps(payload), cwd=Path.cwd(), text=True,
        capture_output=True, check=False,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.parametrize("name", sorted(_CASES))
def test_send_builder_selection(name, verdicts):
    _, _, expected = _CASES[name]
    assert verdicts[name] == expected
