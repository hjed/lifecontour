"""The Snipe-IT settings schemas describe the user mapping in product terms."""

import pytest
from core_shared.product import PRODUCT_NAME
from pydantic import BaseModel

from app.api.integrations.snipeit_settings_schemas import (
    SnipeItSettingsAttributes,
    SnipeItSettingsRequest,
)


@pytest.mark.parametrize("model", [SnipeItSettingsRequest, SnipeItSettingsAttributes])
def test_user_id_description_names_the_product(model: type[BaseModel]) -> None:
    properties = model.model_json_schema()["properties"]

    description = properties["snipeit_user_id"]["description"]
    assert PRODUCT_NAME in description
    assert "PMS" not in description
