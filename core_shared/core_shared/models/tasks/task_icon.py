"""The fixed set of icons a task or a task list may carry.

An icon is optional and, when set, must be one of these keys. The keys are the
published contract — the API and MCP accept only them, and they are what is
stored in the ``icon`` columns — while the web app maps each key to an icon
component. Each key currently matches a ``lucide-react`` icon name so that
mapping is obvious, but the key is ours: if the library renames an icon, the
frontend's mapping changes and the stored key does not.

**Keys are only ever added, never renamed or removed.** The database holds no
CHECK on icon values (so a new icon needs no migration on every table that
carries one); every write goes through an entity that accepts only a member of
this enum. A removed key would leave rows the entities cannot read back.

``flag`` is deliberately absent: the flag is a separate on/off marker on every
task, and an icon that looked like it would be confusing.
"""

from enum import StrEnum, unique


@unique
class TaskIcon(StrEnum):
    """An icon from the fixed set, identified by its stable kebab-case key."""

    LIST = "list"
    CLIPBOARD_LIST = "clipboard-list"
    BOOKMARK = "bookmark"
    STAR = "star"
    HEART = "heart"
    LIGHTBULB = "lightbulb"
    CALENDAR = "calendar"
    HOUSE = "house"
    BRIEFCASE = "briefcase"
    SHOPPING_CART = "shopping-cart"
    GIFT = "gift"
    PACKAGE = "package"
    WALLET = "wallet"
    PHONE = "phone"
    MAIL = "mail"
    USERS = "users"
    BABY = "baby"
    PAW_PRINT = "paw-print"
    PARTY_POPPER = "party-popper"
    TROPHY = "trophy"
    PLANE = "plane"
    LUGGAGE = "luggage"
    CAR = "car"
    BIKE = "bike"
    MAP = "map"
    TENT = "tent"
    MOUNTAIN = "mountain"
    LEAF = "leaf"
    SUN = "sun"
    DUMBBELL = "dumbbell"
    PILL = "pill"
    UTENSILS = "utensils"
    COFFEE = "coffee"
    SHIRT = "shirt"
    WRENCH = "wrench"
    HAMMER = "hammer"
    BOOK_OPEN = "book-open"
    GRADUATION_CAP = "graduation-cap"
    MUSIC = "music"
    CAMERA = "camera"
