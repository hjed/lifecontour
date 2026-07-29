# Contact Fixtures Usage Examples

This document demonstrates how to use the shared contact fixtures to reduce duplication across test files.

## Before and After Examples

### Before: Duplicated Contact Setup

```python
# OLD WAY - Duplicated in multiple test files
@pytest.fixture
def sample_contact(self):
    """Create a sample contact for testing."""
    contact = Contact(
        id=123,
        first_name="John",
        last_name="Doe",
    )

    contact.methods = [
        ContactMethod(
            id=1,
            contact_id=123,
            method_type=MethodType.EMAIL,
            value="john@example.com",
            is_primary=True,
        ),
        ContactMethod(
            id=2,
            contact_id=123,
            method_type=MethodType.PHONE,
            value="+1234567890",
            is_primary=True,
        ),
    ]

    contact.tags = [
        Tag(id=1, name=TagName("friend")),
        Tag(id=2, name=TagName("work")),
    ]

    contact.notes = [
        ContactNote(
            id=1,
            contact_id=123,
            content="Great colleague and friend",
            created_at=None,
        ),
    ]

    return contact
```

### After: Using Shared Fixtures

```python
# NEW WAY - Using shared fixtures
from tests.fixtures.contact_fixtures import create_full_contact


@pytest.fixture
def sample_contact(self):
    """Create a sample contact for testing."""
    return create_full_contact(contact_id=123)
```

## Usage Patterns

### 1. Factory Functions (Recommended for Customization)

```python
from tests.fixtures.contact_fixtures import (
    create_basic_contact,
    create_contact_with_email,
    create_contact_with_methods,
    create_full_contact,
)


def test_something():
    # Basic contact
    contact = create_basic_contact(first_name="Jane", last_name="Smith")

    # Contact with custom email
    contact = create_contact_with_email(
        first_name="Bob", email="bob.wilson@company.com"
    )

    # Contact with both email and phone
    contact = create_contact_with_methods(
        first_name="Alice", email="alice@example.com", phone="+1-555-9999"
    )

    # Full contact with all related entities
    contact = create_full_contact(
        first_name="David",
        tags=["client", "important"],
        notes=["VIP customer", "Prefers email contact"],
    )
```

### 2. Pytest Fixtures (For Standard Cases)

```python
def test_with_fixtures(basic_contact, contact_with_methods, full_contact):
    """Use pre-configured fixtures for common patterns."""
    assert basic_contact.first_name == "John"
    assert len(contact_with_methods.methods) == 2
    assert len(full_contact.tags) == 2
```

### 3. Legacy Compatibility

```python
# These fixtures provide backward compatibility
def test_legacy_code(sample_contact, sample_contact_entity):
    """Existing tests can use legacy fixture names."""
    assert sample_contact.id == 123
    assert sample_contact_entity.id == 123
```

## Migration Guide

### Step 1: Add Import
```python
from tests.fixtures.contact_fixtures import create_full_contact, create_basic_contact
```

### Step 2: Replace Inline Creation
```python
# Before
contact = Contact(first_name="John", last_name="Doe")

# After
contact = create_basic_contact(first_name="John", last_name="Doe")
```

### Step 3: Replace Complex Fixtures
```python
# Before - 40+ lines of setup code
@pytest.fixture
def complex_contact(self):
    contact = Contact(...)
    # ... lots of setup code
    return contact


# After - 1 line
@pytest.fixture
def complex_contact(self):
    return create_full_contact(contact_id=123)
```

## Benefits

1. **Reduced Duplication**: ~200+ lines of duplicated setup code eliminated
2. **Consistency**: All tests use the same realistic test data patterns
3. **Maintainability**: Changes to test data only need to be made in one place
4. **Readability**: Tests focus on logic, not setup boilerplate
5. **Flexibility**: Factory functions allow customization when needed

## Files to Migrate

High priority (most duplication):
- `tests/unit/mcp/domains/contacts/test_tools.py` ✅ (example shown)
- `tests/integration/mcp/test_contact_tools_integration.py` ✅ (partially done)
- `tests/unit/contacts/test_contact_service.py`
- `tests/integration/contacts/test_contact_service_integration.py`
- `tests/unit/api/test_contact_converters.py`

Medium priority:
- `tests/integration/contacts/test_contact_repository_integration.py`
- Other files with inline Contact creation
