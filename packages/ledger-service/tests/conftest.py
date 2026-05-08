import pytest


@pytest.fixture
def sample_journal_entry_data() -> dict:
    return {
        "tenant_id": "tenant-001",
        "entry_date": "2026-01-15",
        "reference": "JE-001",
        "description": "Test journal entry",
    }
