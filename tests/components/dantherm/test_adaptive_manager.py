"""Tests for Dantherm adaptive manager functionality."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from config.custom_components.dantherm.adaptive_manager import (
    AdaptiveEventStack,
    DanthermAdaptiveManager,
)
from config.custom_components.dantherm.device_map import (
    CONF_BOOST_MODE_TRIGGER,
    STATE_WEEKPROGRAM,
)
from homeassistant.const import STATE_OFF, STATE_ON
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.util.dt import now as ha_now


class MockCalendarEvent:
    """Mock calendar event for testing."""

    def __init__(
        self,
        uid: str,
        summary: str,
        start: datetime,
        end: datetime,
        rrule: str | None = None,
    ) -> None:
        """Initialize mock calendar event."""
        self.uid = uid
        self.summary = summary
        self.start = start
        self.end = end
        self.rrule = rrule


class MockCalendar:
    """Mock calendar for testing."""

    def __init__(self, events: list[MockCalendarEvent] | None = None) -> None:
        """Initialize mock calendar."""
        self._events = events or []


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry_id"
    mock_entry.options = {}
    return mock_entry


@pytest.fixture
def adaptive_manager(hass: HomeAssistant, mock_config_entry):
    """Create an adaptive manager instance for testing."""
    return DanthermAdaptiveManager(hass, mock_config_entry)


@pytest.fixture
def event_stack():
    """Create an event stack instance for testing."""
    return AdaptiveEventStack()


class TestAdaptiveEventStack:
    """Test the AdaptiveEventStack class."""

    def test_initialization(self, event_stack):
        """Test that event stack initializes correctly."""
        assert len(event_stack) == 0
        assert event_stack._calendar is None

    def test_set_calendar(self, event_stack):
        """Test setting calendar reference."""
        mock_calendar = MockCalendar()
        event_stack.set_calendar(mock_calendar)
        assert event_stack._calendar is mock_calendar

    def test_clear_all_events(self, event_stack):
        """Test clearing all events from stack."""
        # Add some test events
        event_stack.append({"event": "test1", "event_id": "id1"})
        event_stack.append({"event": "test2", "event_id": "id2"})

        assert len(event_stack) == 2

        removed_count = event_stack.clear_all_events()

        assert len(event_stack) == 0
        assert removed_count == 2

    def test_clear_all_events_empty_stack(self, event_stack):
        """Test clearing events from empty stack."""
        removed_count = event_stack.clear_all_events()
        assert removed_count == 0


class TestAdaptiveManagerCleanup:
    """Test cleanup functionality in adaptive manager."""

    def test_cleanup_stale_events_no_calendar(self, adaptive_manager):
        """Test cleanup when no calendar is available."""
        # Add some events to the stack
        adaptive_manager.events.append({"event": "test", "event_id": "missing_id"})

        removed_count = adaptive_manager.cleanup_stale_events()

        # Should not remove events without calendar reference
        assert removed_count == 0
        assert len(adaptive_manager.events) == 1

    def test_cleanup_stale_events_with_valid_events(self, adaptive_manager):
        """Test cleanup with events that exist in calendar."""
        # Setup calendar with events
        calendar_events = [
            MockCalendarEvent(
                "valid_id", "Valid Event", ha_now(), ha_now() + timedelta(hours=1)
            )
        ]
        mock_calendar = MockCalendar(calendar_events)
        adaptive_manager._calendar = mock_calendar
        adaptive_manager.events.set_calendar(mock_calendar)

        # Add event that exists in calendar
        adaptive_manager.events.append({"event": "test", "event_id": "valid_id"})

        removed_count = adaptive_manager.cleanup_stale_events()

        # Should not remove valid events
        assert removed_count == 0
        assert len(adaptive_manager.events) == 1

    def test_cleanup_stale_events_with_invalid_events(self, adaptive_manager):
        """Test cleanup with events that don't exist in calendar."""
        # Setup calendar with one event
        calendar_events = [
            MockCalendarEvent(
                "valid_id", "Valid Event", ha_now(), ha_now() + timedelta(hours=1)
            )
        ]
        mock_calendar = MockCalendar(calendar_events)
        adaptive_manager._calendar = mock_calendar
        adaptive_manager.events.set_calendar(mock_calendar)

        # Add event that doesn't exist in calendar
        adaptive_manager.events.append({"event": "test", "event_id": "invalid_id"})

        removed_count = adaptive_manager.cleanup_stale_events()

        # Should remove invalid events
        assert removed_count == 1
        assert len(adaptive_manager.events) == 0

    def test_cleanup_stale_events_mixed_events(self, adaptive_manager):
        """Test cleanup with mix of valid and invalid events."""
        # Setup calendar with one event
        calendar_events = [
            MockCalendarEvent(
                "valid_id", "Valid Event", ha_now(), ha_now() + timedelta(hours=1)
            )
        ]
        mock_calendar = MockCalendar(calendar_events)
        adaptive_manager._calendar = mock_calendar
        adaptive_manager.events.set_calendar(mock_calendar)

        # Add mix of valid and invalid events
        adaptive_manager.events.append({"event": "valid", "event_id": "valid_id"})
        adaptive_manager.events.append({"event": "invalid", "event_id": "invalid_id"})
        adaptive_manager.events.append({"event": "no_id"})  # No event_id

        removed_count = adaptive_manager.cleanup_stale_events()

        # Should remove only the invalid event
        assert removed_count == 1
        assert len(adaptive_manager.events) == 2

    def test_cleanup_calendar_access_error(self, adaptive_manager):
        """Test cleanup when calendar access fails."""
        # Setup calendar that will cause an error
        mock_calendar = MagicMock()
        mock_calendar._events = None  # This will cause AttributeError
        adaptive_manager._calendar = mock_calendar
        adaptive_manager.events.set_calendar(mock_calendar)

        # Add event
        adaptive_manager.events.append({"event": "test", "event_id": "some_id"})

        # Should still remove events when calendar access fails (fail-safe behavior)
        removed_count = adaptive_manager.cleanup_stale_events()
        assert removed_count == 1  # Event gets removed in error case
        assert len(adaptive_manager.events) == 0


class TestCalculateEventEndTime:
    """Test end time calculation for calendar events."""

    def test_calculate_end_time_non_recurring(self, adaptive_manager):
        """Test end time calculation for non-recurring events."""
        start_time = ha_now()
        end_time = start_time + timedelta(hours=2)

        event = MockCalendarEvent("test_id", "Test Event", start_time, end_time)

        calculated_end = adaptive_manager._calculate_event_end_time(event)

        # For non-recurring events, should return the original end time
        assert calculated_end == end_time

    def test_calculate_end_time_recurring(self, adaptive_manager):
        """Test end time calculation for recurring events."""
        start_time = ha_now()
        # Create a reasonable duration - 2 hours
        original_end = start_time + timedelta(hours=2)

        event = MockCalendarEvent(
            "test_id", "Test Event", start_time, original_end, rrule="FREQ=DAILY"
        )

        calculated_end = adaptive_manager._calculate_event_end_time(event)

        # For recurring events with reasonable duration, should return original calculation
        expected_duration = original_end - start_time
        expected_end = start_time + expected_duration
        assert calculated_end == expected_end

    def test_calculate_end_time_recurring_suspicious_duration(self, adaptive_manager):
        """Test end time calculation for recurring events with suspicious long duration."""
        start_time = ha_now()
        # Create an end time that's more than a year in the future
        original_end = start_time + timedelta(days=400)

        event = MockCalendarEvent(
            "test_id", "Test Event", start_time, original_end, rrule="FREQ=DAILY"
        )

        with patch(
            "config.custom_components.dantherm.adaptive_manager._LOGGER"
        ) as mock_logger:
            calculated_end = adaptive_manager._calculate_event_end_time(event)

            # Should limit to 24 hours maximum
            expected_end = start_time + timedelta(hours=24)
            assert calculated_end == expected_end

            # Should log a warning
            mock_logger.warning.assert_called_once()


class TestEventStackIntegration:
    """Test integration between event stack and cleanup."""

    async def test_startup_cleanup_called(self, adaptive_manager):
        """Test that cleanup is called during setup."""
        # Create mock attributes the setup method needs
        with (
            patch.object(
                adaptive_manager,
                "get_device_id",
                return_value="device_123",
                create=True,
            ),
            patch.object(adaptive_manager, "_adaptive_triggers", {}),
            patch.object(
                adaptive_manager, "cleanup_stale_events", return_value=2
            ) as mock_cleanup,
        ):
            await adaptive_manager.async_set_up_adaptive_manager()
            mock_cleanup.assert_called_once()


class TestBoostModeTimeout:
    """Test boost mode timeout behavior."""

    def setup_mock_manager(self):
        """Create a mock device manager with necessary methods."""
        # Create mock hass and config entry
        mock_hass = MagicMock()
        mock_config_entry = MagicMock()
        mock_config_entry.entry_id = "test_entry"
        mock_config_entry.options = {}
        
        # Create manager
        manager = DanthermAdaptiveManager(mock_hass, mock_config_entry)
        
        # Mock the required mixin methods
        manager.get_device_id = MagicMock(return_value="test_device")
        manager.get_entity_state_from_coordinator = MagicMock(
            side_effect=lambda key, default=None: {
                "boost_mode": True,
                "boost_mode_timeout": 5,  # 5 minutes timeout
            }.get(key, default)
        )
        manager.get_current_operation = MagicMock(
            return_value=STATE_WEEKPROGRAM
        )
        manager.set_operation_selection = AsyncMock()
        manager.get_device_entities = MagicMock(return_value=[])

        # Set up the mock hass states
        mock_state = MagicMock()
        mock_state.state = STATE_OFF
        mock_hass.states.get = MagicMock(return_value=mock_state)

        return manager

    @pytest.mark.asyncio
    async def test_boost_mode_timeout_reverts_to_week_program(self):
        """Test that boost mode properly reverts to week program after timeout.

        This test reproduces the issue where boost mode would "stick" instead of
        reverting to the configured week program after the timeout period.
        """
        manager = self.setup_mock_manager()

        # Set up trigger configuration
        trigger_entity_id = "binary_sensor.test_boost_trigger"
        manager._adaptive_triggers[CONF_BOOST_MODE_TRIGGER]["trigger"] = (
            trigger_entity_id
        )

        # Initial state: boost mode switch is ON
        manager.get_entity_state_from_coordinator.side_effect = lambda key, default=None: {
            "boost_mode": True,
            "boost_mode_timeout": 5,
            "boost_operation_selection": "level_4",
        }.get(
            key, default
        )

        # Simulate boost trigger being detected
        manager._adaptive_triggers[CONF_BOOST_MODE_TRIGGER]["detected"] = ha_now()

        # First update: trigger is detected, should create event
        await manager._update_adaptive_trigger_state(CONF_BOOST_MODE_TRIGGER)

        # Verify event was created
        assert len(manager.events) == 1
        event = manager.events[0]
        assert event["event"] == "boost"
        assert event["end_time"] is not None

        # Verify timeout was set
        timeout = manager._adaptive_triggers[CONF_BOOST_MODE_TRIGGER]["timeout"]
        assert timeout is not None

        # Now simulate that operation has changed to level_4 (boost mode is active)
        manager.get_current_operation.return_value = "level_4"

        # Simulate time passing and trigger turning OFF
        manager._adaptive_triggers[CONF_BOOST_MODE_TRIGGER]["detected"] = None
        manager._adaptive_triggers[CONF_BOOST_MODE_TRIGGER]["undetected"] = ha_now()

        # Mock the trigger entity state as OFF
        mock_state = MagicMock()
        mock_state.state = STATE_OFF
        manager._hass.states.get = MagicMock(return_value=mock_state)

        # Second update: trigger is undetected, should update timeout but not clear it
        await manager._update_adaptive_trigger_state(CONF_BOOST_MODE_TRIGGER)

        # The timeout should still be set (this is where the bug was - it was being set to None)
        timeout_after_undetect = manager._adaptive_triggers[CONF_BOOST_MODE_TRIGGER][
            "timeout"
        ]
        assert (
            timeout_after_undetect is not None
        ), "Timeout should not be None after trigger turns off"

        # Verify event still exists
        assert len(manager.events) == 1

        # Simulate time passing beyond the timeout
        # Set the event's end_time to the past
        manager.events[0]["end_time"] = ha_now() - timedelta(minutes=1)

        # Process expired events - this should remove the boost event
        await manager.async_process_expired_events()

        # Verify the event was removed
        assert (
            len(manager.events) == 0
        ), "Boost mode event should be removed after timeout"

        # Verify that set_operation_selection was called twice:
        # 1. First to activate boost mode (level_4)
        # 2. Second to revert to week program
        assert manager.set_operation_selection.call_count == 2
        # The last call should be to revert to week program
        manager.set_operation_selection.assert_called_with(STATE_WEEKPROGRAM)

    @pytest.mark.asyncio
    async def test_boost_mode_trigger_extends_timeout_when_on(self):
        """Test that boost mode timeout is extended when trigger stays ON."""
        manager = self.setup_mock_manager()

        # Set up trigger configuration
        trigger_entity_id = "binary_sensor.test_boost_trigger"
        manager._adaptive_triggers[CONF_BOOST_MODE_TRIGGER]["trigger"] = (
            trigger_entity_id
        )

        # Initial state: boost mode switch is ON
        manager.get_entity_state_from_coordinator.side_effect = lambda key, default=None: {
            "boost_mode": True,
            "boost_mode_timeout": 5,
            "boost_operation_selection": "level_4",
        }.get(
            key, default
        )

        # Simulate boost trigger being detected
        manager._adaptive_triggers[CONF_BOOST_MODE_TRIGGER]["detected"] = ha_now()

        # First update: trigger is detected, should create event
        await manager._update_adaptive_trigger_state(CONF_BOOST_MODE_TRIGGER)

        # Get the initial timeout
        initial_timeout = manager._adaptive_triggers[CONF_BOOST_MODE_TRIGGER]["timeout"]
        assert initial_timeout is not None

        # Mock the trigger entity state as still ON
        mock_state = MagicMock()
        mock_state.state = STATE_ON
        manager._hass.states.get = MagicMock(return_value=mock_state)

        # Clear detected/undetected for the next update
        manager._adaptive_triggers[CONF_BOOST_MODE_TRIGGER]["detected"] = None
        manager._adaptive_triggers[CONF_BOOST_MODE_TRIGGER]["undetected"] = None

        # Simulate some time passing
        import time

        time.sleep(0.1)

        # Second update: trigger is still ON, should extend timeout
        await manager._update_adaptive_trigger_state(CONF_BOOST_MODE_TRIGGER)

        # The timeout should be extended (later than initial)
        extended_timeout = manager._adaptive_triggers[CONF_BOOST_MODE_TRIGGER][
            "timeout"
        ]
        assert extended_timeout is not None
        assert extended_timeout > initial_timeout, "Timeout should be extended"

        # Event should still exist
        assert len(manager.events) == 1
