"""Common test utilities."""
from homeassistant.config_entries import ConfigEntry


class MockConfigEntry(ConfigEntry):
    """Mock config entry for testing."""

    def __init__(
        self,
        *,
        domain: str,
        data: dict,
        options: dict | None = None,
        unique_id: str | None = None,
        entry_id: str | None = None,
        **kwargs
    ):
        """Initialize mock config entry."""
        if entry_id is None:
            entry_id = "test_entry_id"
        super().__init__(
            version=1,
            minor_version=1,
            domain=domain,
            title=data.get("name", "Test"),
            data=data,
            options=options or {},
            unique_id=unique_id,
            entry_id=entry_id,
        )
