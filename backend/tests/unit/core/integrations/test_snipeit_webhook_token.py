"""Unit tests for Snipe-IT webhook token generation."""

import string

from app.core.integrations.models.snipeit import generate_webhook_token

URL_SAFE_CHARACTERS = set(string.ascii_letters + string.digits + "-_")


def test_generated_tokens_are_url_safe_and_distinct() -> None:
    tokens = {generate_webhook_token() for _ in range(20)}

    assert len(tokens) == 20
    assert all(len(token) == 43 for token in tokens)
    assert all(set(token) <= URL_SAFE_CHARACTERS for token in tokens)
