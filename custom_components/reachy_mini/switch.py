"""Head/body coupling preference for HA manual controls only."""
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .entity import ReachyMiniEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ReachyMiniHeadFollowsBody(hass.data[DOMAIN][entry.entry_id], entry)])


class ReachyMiniHeadFollowsBody(ReachyMiniEntity, SwitchEntity):
    entity_description = SwitchEntityDescription(
        key="head_follows_body", name="Head follows body",
        translation_key="head_follows_body", icon="mdi:link-variant",
    )

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "head_follows_body")

    @property
    def is_on(self):
        return self.coordinator.manual_control.follows

    async def _set(self, follows):
        if self.coordinator.manual_control.busy:
            raise HomeAssistantError("Wait for the current movement to finish")
        self.coordinator.manual_control.follows = follows
        self.coordinator.async_update_listeners()

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)
