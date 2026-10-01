"""The REST API names itself with the shared product identity."""

from core_shared.product import PRODUCT_NAME, PRODUCT_TAGLINE

from app.main import create_app


def test_openapi_info_uses_product_identity() -> None:
    info = create_app().openapi()["info"]

    assert info["title"] == PRODUCT_NAME
    assert info["description"] == PRODUCT_TAGLINE
