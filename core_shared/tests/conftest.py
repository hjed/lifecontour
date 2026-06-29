"""Top-level pytest configuration for the ``core_shared`` test suite.

Registers the shared worker fixtures (``core_shared.testing``) as a pytest
plugin so the package can self-test the fixtures it provides to the workers.
``pytest_plugins`` must live in the top-level conftest, which is why it is
declared here rather than in a nested ``conftest.py``.
"""

pytest_plugins = ["core_shared.testing"]
