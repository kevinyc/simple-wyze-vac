import logging

from datetime import timedelta
from datetime import datetime
import time
import urllib.request
from pathlib import Path

from .const import WYZE_VAC_CLIENT, WYZE_VACUUMS, WYZE_USERNAME, WYZE_PASSWORD, \
                   DOMAIN, FILTER_LIFETIME, MAIN_BRUSH_LIFETIME, SIDE_BRUSH_LIFETIME, \
                   CONF_POLLING, WYZE_SCAN_INTERVAL

from wyze_sdk.models.devices import VacuumMode, VacuumSuctionLevel
from wyze_sdk.errors import WyzeApiError, WyzeClientNotConnectedError
from wyze_sdk import Client

from homeassistant.components.vacuum import (
    PLATFORM_SCHEMA,
    SUPPORT_BATTERY,
    # SUPPORT_CLEAN_SPOT,
    SUPPORT_FAN_SPEED,
    SUPPORT_LOCATE,
    SUPPORT_RETURN_HOME,
    SUPPORT_SEND_COMMAND,
    SUPPORT_STATUS,
    SUPPORT_STOP,
    SUPPORT_START,
    SUPPORT_MAP,
    # SUPPORT_TURN_OFF,
    # SUPPORT_TURN_ON,
    STATES,
    STATE_CLEANING,
    STATE_DOCKED,
    STATE_RETURNING,
    STATE_ERROR,
    STATE_PAUSED,
    StateVacuumEntity
)

SUPPORT_WYZE = (
    SUPPORT_BATTERY |
    # SUPPORT_CLEAN_SPOT |
    SUPPORT_MAP |
    SUPPORT_FAN_SPEED |
    SUPPORT_LOCATE |
    SUPPORT_RETURN_HOME |
    SUPPORT_SEND_COMMAND |
    SUPPORT_STATUS |
    SUPPORT_STOP |
    SUPPORT_START 
    # SUPPORT_TURN_OFF |
    # SUPPORT_TURN_ON
)

_LOGGER = logging.getLogger(__name__)

FAN_SPEEDS = [VacuumSuctionLevel.QUIET.describe(),
            VacuumSuctionLevel.STANDARD.describe(),
            VacuumSuctionLevel.STRONG.describe()]

async def async_setup_entry(hass, config_entry, async_add_entities):

    username = hass.data[WYZE_USERNAME]
    password = hass.data[WYZE_PASSWORD]
    polling = hass.data[CONF_POLLING]

    client = hass.data[DOMAIN][config_entry.entry_id]
    global SCAN_INTERVAL
    if isinstance(hass.data[WYZE_SCAN_INTERVAL], timedelta):
        SCAN_INTERVAL = hass.data[WYZE_SCAN_INTERVAL]
    elif isinstance(hass.data[WYZE_SCAN_INTERVAL], str):
        t = datetime.strptime(hass.data[WYZE_SCAN_INTERVAL],"%H:%M:%S")
        SCAN_INTERVAL = timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
    else:
        SCAN_INTERVAL = timedelta(hours=2)

    vacs = []
    for pl in hass.data[WYZE_VACUUMS]:
        vacs.append(WyzeVac(client, pl, username, password, polling))

    async_add_entities(vacs)


class WyzeVac(StateVacuumEntity):

    def __init__(self, client, pl, username, password, polling):
        self._client = client
        self._vac_mac = pl["mac"]
        self._model = pl["model"]
        self._last_mode = STATE_DOCKED
        self._name = pl["name"]
        self._fan_speed = pl["suction"]
        self._battery_level = pl["battery"]

        self._filter = pl["filter"]
        self._main_brush = pl["main_brush"]
        self._side_brush = pl["side_brush"]

        self._username = username
        self._password = password

        self._polling = polling

        self._room_manager = pl["room_manager"]
        self._rooms = []
        for name, stat in self._room_manager.rooms.items():
            self._rooms.append(name)

        global SCAN_INTERVAL
        if self._polling:
            _LOGGER.warn(f"Simple Wyze Vac Polling every {SCAN_INTERVAL}. Careful of hitting Wyze servers rate limits.")

    @property
    def device_info(self):
        """Return device registry information for this entity."""
        return {
            "identifiers": {(DOMAIN, self._name)},
            "name": self._name,
            "manufacturer": "Wyze Inc.",
            "model": self._model,
        }

    @property
    def unique_id(self) -> str:
        """Return an unique ID."""
        return self._name

    @property
    def supported_features(self):
        """Flag vacuum cleaner features that are supported."""
        return SUPPORT_WYZE

    @property
    def is_on(self):
        """Return true if vacuum is currently cleaning."""
        return self._last_mode != STATE_DOCKED

    @property
    def status(self):
        """Return the status of the vacuum cleaner."""
        return self._last_mode

    @property
    def state(self):
        """Return the state of the vacuum cleaner."""
        return self._last_mode

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def fan_speed(self):
        """Return the status of the vacuum."""
        return self._fan_speed

    @property
    def fan_speed_list(self):
        """Return the status of the vacuum."""
        return FAN_SPEEDS

    @property
    def should_poll(self) -> bool:
        """Return True if entity has to be polled for state."""
        return self._polling
    
    @property
    def battery_level(self):
        """Return the battery level of the vacuum cleaner."""
        return self._battery_level

    @property
    def extra_state_attributes(self):
        """Return the state attributes of the vacuum cleaner."""
        data = {}

        if self._filter is not None:
            data["filter"] = FILTER_LIFETIME - int(self._filter)
        if self._main_brush is not None:
            data["main_brush"] = MAIN_BRUSH_LIFETIME - int(self._main_brush)
        if self._side_brush is not None:
            data["side_brush"] = SIDE_BRUSH_LIFETIME - int(self._side_brush)
        if self._rooms is not None:
            data["rooms"] = self._rooms

        return data

    async def get_new_client(self):
        _LOGGER.warn("Refreshing Wyze Client. Do this sparingly to be prevent lockout.")
        self._client = await self.hass.async_add_executor_job(lambda: Client(email=self._username, password=self._password))

    async def async_start(self, **kwargs):
        try:
            vacuum = await self.hass.async_add_executor_job(lambda: self._client.vacuums.info(device_mac=self._vac_mac))
        except (WyzeApiError, WyzeClientNotConnectedError) as e:
            _LOGGER.warn("Received WyzeApiError")
            await self.get_new_client()
        finally:
            await self.hass.async_add_executor_job(lambda: self._client.vacuums.clean(device_mac=self._vac_mac, device_model=self._model))
        
        time.sleep(1)
        self.async_schedule_update_ha_state()

    async def async_pause(self, **kwargs):
        """Stop the vacuum cleaner."""
        try:
            vacuum = await self.hass.async_add_executor_job(lambda: self._client.vacuums.info(device_mac=self._vac_mac))
        except (WyzeApiError, WyzeClientNotConnectedError) as e:
            _LOGGER.warn("Received WyzeApiError")
            await self.get_new_client()
        finally:
            await self.hass.async_add_executor_job(lambda: self._client.vacuums.pause(device_mac=self._vac_mac, device_model=self._model))
        self._last_mode = STATE_PAUSED
        self.async_schedule_update_ha_state()

    async def async_stop(self, **kwargs):
        """Stop the vacuum cleaner."""
        try:
            vacuum = await self.hass.async_add_executor_job(lambda: self._client.vacuums.info(device_mac=self._vac_mac))
        except (WyzeApiError, WyzeClientNotConnectedError) as e:
            _LOGGER.warn("Received WyzeApiError")
            await self.get_new_client()
        finally:
            await self.hass.async_add_executor_job(lambda: self._client.vacuums.pause(device_mac=self._vac_mac, device_model=self._model))
        self._last_mode = STATE_PAUSED
        self.async_schedule_update_ha_state()

    async def async_return_to_base(self, **kwargs):
        """Set the vacuum cleaner to return to the dock."""
        try:
           vacuum = await self.hass.async_add_executor_job(lambda: self._client.vacuums.info(device_mac=self._vac_mac))
        except (WyzeApiError, WyzeClientNotConnectedError) as e:
            _LOGGER.warn("Received WyzeApiError")
            await self.get_new_client()
        finally:
            await self.hass.async_add_executor_job(lambda: self._client.vacuums.dock(device_mac=self._vac_mac, device_model=self._model))
        self._last_mode = STATE_RETURNING
        self.async_schedule_update_ha_state()

    async def async_locate(self, **kwargs):
        """Locate the vacuum cleaner."""
        _LOGGER.warn("Locate called. Not Implemented.")
        pass

    async def async_start_pause(self, **kwargs):
        """Start, pause or resume the cleaning task."""
        if self._last_mode in [ STATE_CLEANING, STATE_RETURNING]:
            await self.pause()
        else:
            await self.start()
        
        self.async_schedule_update_ha_state()

    async def async_send_command(self, command, params=None, **kwargs):
        try:
            vacuum = await self.hass.async_add_executor_job(lambda: self._client.vacuums.info(device_mac=self._vac_mac))
        except (WyzeApiError, WyzeClientNotConnectedError) as e:
            _LOGGER.warn("Received WyzeApiError")
            await self.get_new_client()
        finally:
            vacuum = await self.hass.async_add_executor_job(lambda: self._client.vacuums.info(device_mac=self._vac_mac))
        _LOGGER.info("Command: %s, params: %s", command, params)
        if command in "sweep_rooms":
            """Perform a spot clean-up."""
            if "rooms" in params:
                desired_rooms = params["rooms"]
                rooms = vacuum.current_map.rooms
                if rooms is None:
                    _LOGGER.warn("No rooms from Wyze servers. You may have the unsupported multi-floor firmware. Sweep rooms currently does not work on this firmware.")
                    return
                await self.hass.async_add_executor_job(lambda: self._client.vacuums.sweep_rooms(device_mac=self._vac_mac, room_ids=[room.id for room in rooms if room.name in desired_rooms]))
                self.async_schedule_update_ha_state()
            else:
                _LOGGER.warn("No rooms specified for vacuum. Cannot do spot clean")
        
        elif command in "sweep_auto":
            rooms = vacuum.current_map.rooms
            if rooms is None:
                    _LOGGER.warn("No rooms from Wyze servers. You may have the unsupported multi-floor firmware. Sweep rooms currently does not work on this firmware.")
                    return
            filtered_rooms = [name for name, val in self._room_manager.rooms.items() if val]
            await self.hass.async_add_executor_job(lambda: self._client.vacuums.sweep_rooms(device_mac=self._vac_mac, room_ids=[room.id for room in rooms if room.name in filtered_rooms]))

            time.sleep(1)
            self.async_schedule_update_ha_state(force_refresh=True)
        elif command in "update":
            self.async_schedule_update_ha_state(force_refresh=True)
            # self.async_update()
            
        elif command in ["refresh_token", "get_new_client"]:
            await self.get_new_client()
        
        elif command in ["get_map", "get_last_map"]:
            await self.get_last_map()
        
        else:
            _LOGGER.warn(f"Unknown wyze vac command: {command}")

    async def async_update(self):
        _LOGGER.warn("calling update")
        # Get vacuum states
        try:
            vacuum = await self.hass.async_add_executor_job(lambda: self._client.vacuums.info(device_mac=self._vac_mac))
        except (WyzeApiError, WyzeClientNotConnectedError) as e:
            _LOGGER.warn("Received WyzeApiError")
            await self.get_new_client()
        finally:
            vacuum = await self.hass.async_add_executor_job(lambda: self._client.vacuums.info(device_mac=self._vac_mac))

        # Get vacuum mode
        if vacuum.mode in [VacuumMode.SWEEPING]:
            self._last_mode = STATE_CLEANING
        elif vacuum.mode in [VacuumMode.IDLE, VacuumMode.BREAK_POINT]:
            self._last_mode = STATE_DOCKED
        elif vacuum.mode in [VacuumMode.ON_WAY_CHARGE, VacuumMode.FULL_FINISH_SWEEPING_ON_WAY_CHARGE]:
            self._last_mode = STATE_RETURNING
        elif vacuum.mode in [VacuumMode.PAUSE]:
            self._last_mode = STATE_PAUSED
        else:
            self._last_mode = STATE_ERROR

        # Update battery
        self._battery_level = vacuum.voltage

        # Update suction level
        self._fan_speed = vacuum.clean_level.describe()

        # Update filter information
        self._filter = vacuum.filter
        self._main_brush = vacuum.main_brush
        self._side_brush = vacuum.side_brush

        await self.get_last_map()

    async def async_set_fan_speed(self, fan_speed, **kwargs):
        """Set the vacuum's fan speed."""
        if self.supported_features & SUPPORT_FAN_SPEED == 0:
            return

        if fan_speed in self.fan_speed_list:
            self._fan_speed = fan_speed
            wyze_suction = VacuumSuctionLevel.QUIET
            if self._fan_speed == FAN_SPEEDS[1]:
                wyze_suction = VacuumSuctionLevel.STANDARD
            elif self._fan_speed == FAN_SPEEDS[2]:
                wyze_suction = VacuumSuctionLevel.STRONG
                
            try:
                vacuum = await self.hass.async_add_executor_job(lambda: self._client.vacuums.info(device_mac=self._vac_mac))
            except (WyzeApiError, WyzeClientNotConnectedError) as e:
                _LOGGER.warn("Received WyzeApiError")
                await self.get_new_client()
            finally:
                await self.hass.async_add_executor_job(lambda: self._client.vacuums.set_suction_level(device_mac=self._vac_mac, device_model=self._model, suction_level=wyze_suction))
            time.sleep(1) # It takes awhile for the suction level to update Wyze servers
            self.async_schedule_update_ha_state()
    
    async def get_last_map(self):
        try:
            vacuum = await self.hass.async_add_executor_job(lambda: self._client.vacuums.info(device_mac=self._vac_mac))
        except (WyzeApiError, WyzeClientNotConnectedError) as e:
            _LOGGER.warn("Received WyzeApiError")
            await self.get_new_client()
        finally:
            url = await self.hass.async_add_executor_job(lambda: self._client.vacuums.get_sweep_records(device_mac=self._vac_mac, since=datetime.now())[0].map_img_big_url)

        Path(f"www/{DOMAIN}").mkdir(parents=True, exist_ok=True)
        try:
            await self.hass.async_add_executor_job(lambda: urllib.request.urlretrieve(url, f"www/{DOMAIN}/vacuum_last_map.jpg"))
        except:
            _LOGGER.warn("Failed to grab latest map image. Try again later.")
