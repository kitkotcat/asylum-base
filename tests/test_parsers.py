from __future__ import annotations

from bot.app.services.parsers import (
    _google_play_signature,
)


def test_google_play_signature_is_stable() -> None:
    html = """
    <html>
      <body>
        <div>Updated on</div>
        <div>Jul 30, 2026</div>
        <h2>What's new</h2>
        <div>Bug fixes and optimizations</div>
        <div>Data safety</div>
      </body>
    </html>
    """

    first = _google_play_signature(html)
    second = _google_play_signature(html)

    assert first == second
    assert first[1] == "Jul 30, 2026"
    assert "Bug fixes" in first[2]
