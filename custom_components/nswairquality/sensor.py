"""
Air quality readings are updated hourly and a daily air quality forecast
is made for the Greater Sydney Metropolitan Region at 4pm each day.

For more details about this platform, please refer to the documentation at
https://github.com/troykelly/ha-nswairquality
"""
import datetime
import io
import logging
import nswairquality

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_MONITORED_CONDITIONS, TEMP_CELSIUS, CONF_NAME, ATTR_ATTRIBUTION,
    ATTR_FRIENDLY_NAME, CONF_LATITUDE, CONF_LONGITUDE, CONF_ICON)
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

ATTR_ICON = 'icon'
ATTR_ISSUE_TIME_LOCAL = 'issue_time_local'
ATTR_PRODUCT_ID = 'product_id'
ATTR_PRODUCT_LOCATION = 'product_location'
ATTR_PRODUCT_NAME = 'product_name'
ATTR_SENSOR_ID = 'sensor_id'
ATTR_START_TIME_LOCAL = 'start_time_local'

CONF_ATTRIBUTION = '© State Government of NSW and Department of Planning, Industry and Environment 1994'
CONF_DAYS = 'forecast_days'
CONF_PRODUCT_ID = 'product_id'
CONF_REST_OF_TODAY = 'rest_of_today'
CONF_FRIENDLY = 'friendly'
CONF_FRIENDLY_STATE_FORMAT = 'friendly_state_format'

MIN_TIME_BETWEEN_UPDATES = datetime.timedelta(minutes=5)

SENSOR_TYPES = {
    'max': ['air_temperature_maximum', 'Max Temp C', TEMP_CELSIUS, 'mdi:thermometer'],
    'min': ['air_temperature_minimum', 'Min Temp C', TEMP_CELSIUS, 'mdi:thermometer'],
    'chance_of_rain': ['probability_of_precipitation', 'Chance of Rain', '%',
                       'mdi:water-percent'],
    'possible_rainfall': ['precipitation_range', 'Possible Rainfall', 'mm',
                          'mdi:water'],
    'summary': ['precis', 'Summary', None, 'mdi:text'],
    'detailed_summary': ['forecast', 'Detailed Summary', None, 'mdi:text'],
    'uv_alert': ['uv_alert', 'UV Alert', None, 'mdi:weather-sunny'],
    'fire_danger': ['fire_danger', 'Fire Danger', None, 'mdi:fire'],
    'icon': ['forecast_icon_code', 'Icon', None, None]
}

def validate_days(days):
    """Check that days is within bounds."""
    if days not in range(1, 7):
        raise vol.error.Invalid("Forecast Days is out of Range")
    return days


def validate_product_id(product_id):
    """Check that the Product ID is well-formed."""
    if product_id is None or not product_id:
        return product_id
    if not re.fullmatch(r'ID[A-Z]\d\d\d\d\d', product_id):
        raise vol.error.Invalid("Malformed Product ID")
    return product_id


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_MONITORED_CONDITIONS, default=[]):
        vol.All(cv.ensure_list, [vol.In(SENSOR_TYPES)]),
    vol.Optional(CONF_DAYS, default=6): validate_days,
    vol.Optional(CONF_FRIENDLY, default=False): cv.boolean,
    vol.Optional(CONF_FRIENDLY_STATE_FORMAT, default='{summary}'): cv.string,
    vol.Optional(CONF_NAME, default=''): cv.string,
    vol.Optional(CONF_PRODUCT_ID, default=''): validate_product_id,
    vol.Optional(CONF_REST_OF_TODAY, default=True): cv.boolean,
})


def setup_platform(hass, config, add_entities, discovery_info=None):
    days = config.get(CONF_DAYS)
    friendly = config.get(CONF_FRIENDLY)
    friendly_state_format = config.get(CONF_FRIENDLY_STATE_FORMAT)
    monitored_conditions = config.get(CONF_MONITORED_CONDITIONS)
    name = config.get(CONF_NAME)
    product_id = config.get(CONF_PRODUCT_ID)
    rest_of_today = config.get(CONF_REST_OF_TODAY)

    if not product_id:
        product_id = closest_product_id(
            hass.config.latitude, hass.config.longitude)
        if product_id is None:
            _LOGGER.error("Could not get BOM Product ID from lat/lon")
            return

    bom_forecast_data = BOMForecastData(product_id)

    bom_forecast_data.update()

    if rest_of_today:
        start = 0
    else:
        start = 1

    if friendly:
        for index in range(start, config.get(CONF_DAYS) + 1):
            add_entities(
                [BOMForecastSensorFriendly(bom_forecast_data, monitored_conditions,
                                           index, name, product_id,
                                           friendly_state_format)])
    else:
        for index in range(start, config.get(CONF_DAYS) + 1):
            for condition in monitored_conditions:
                add_entities([BOMForecastSensor(bom_forecast_data, condition,
                                                index, name, product_id)])


class BOMForecastSensor(Entity):
    """Implementation of a BOM forecast sensor."""

    def __init__(self, bom_forecast_data, condition, index, name, product_id):
        """Initialize the sensor."""
        self._bom_forecast_data = bom_forecast_data
        self._condition = condition
        self._index = index
        self._name = name
        self._product_id = product_id
        self.update()

    @property
    def name(self):
        """Return the name of the sensor."""
        if not self._name:
            return 'BOM {} {}'.format(
                SENSOR_TYPES[self._condition][1], self._index)
        return 'BOM {} {} {}'.format(self._name,
                                     SENSOR_TYPES[self._condition][1], self._index)

    @property
    def state(self):
        """Return the state of the sensor."""
        reading = self._bom_forecast_data.get_reading(
            self._condition, self._index)

        if self._condition == 'chance_of_rain':
            return reading.replace('%', '')
        if self._condition == 'possible_rainfall':
            return reading.replace(' mm', '')
        return reading

    @property
    def device_state_attributes(self):
        """Return the state attributes of the sensor."""
        attr = {
            ATTR_ATTRIBUTION: CONF_ATTRIBUTION,
            ATTR_SENSOR_ID: self._condition,
            ATTR_ISSUE_TIME_LOCAL: self._bom_forecast_data.get_issue_time_local(),
            ATTR_PRODUCT_ID: self._product_id,
            ATTR_PRODUCT_LOCATION: PRODUCT_ID_LAT_LON_LOCATION[self._product_id][2],
            ATTR_START_TIME_LOCAL: self._bom_forecast_data.get_start_time_local(
                self._index),
            ATTR_ICON: SENSOR_TYPES[self._condition][3]
        }
        if self._name:
            attr[ATTR_PRODUCT_NAME] = self._name

        return attr

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return SENSOR_TYPES[self._condition][2]

    def update(self):
        """Fetch new state data for the sensor."""
        self._bom_forecast_data.update()


class BOMForecastSensorFriendly(Entity):
    """Implementation of a user friendly BOM forecast sensor."""

    def __init__(self, bom_forecast_data, conditions, index, name, product_id,
                 friendly_state_format):
        """Initialize the sensor."""
        self._bom_forecast_data = bom_forecast_data
        self._conditions = conditions
        self._friendly_state_format = friendly_state_format
        self._index = index
        self._name = name
        self._product_id = product_id
        self.update()

    @property
    def unique_id(self):
        """Return the entity id of the sensor."""
        if not self._name:
            return '{}'.format(self._index)
        return '{}_{}'.format(self._name, self._index)

    @property
    def state(self):
        """Return the state of the sensor."""
        friendly_state = self._friendly_state_format
        for condition in self._conditions:
            friendly_state = friendly_state.replace('{{{}}}'.format(condition),
                                                    self._bom_forecast_data.get_reading(
                                                        condition, self._index))
        return friendly_state

    @property
    def device_state_attributes(self):
        """Return the state attributes of the sensor."""
        attr = {
            ATTR_ICON: self._bom_forecast_data.get_reading('icon', self._index),
            ATTR_ATTRIBUTION: CONF_ATTRIBUTION,
        }
        for condition in self._conditions:
            attribute = self._bom_forecast_data.get_reading(condition, self._index)
            if attribute != 'n/a':
                attr[SENSOR_TYPES[condition][1]] = attribute
        if self._name:
            attr['Name'] = self._name

        weather_forecast_date_string = self._bom_forecast_data.get_start_time_local(
            self._index).replace(":", "")
        weather_forecast_datetime = datetime.datetime.strptime(
            weather_forecast_date_string, "%Y-%m-%dT%H%M%S%z")
        attr[ATTR_FRIENDLY_NAME] = weather_forecast_datetime.strftime("%a, %e %b")

        attr["Product ID"] = self._product_id
        attr["Product Location"] = PRODUCT_ID_LAT_LON_LOCATION[self._product_id][2]

        return attr

    def update(self):
        """Fetch new state data for the sensor."""
        self._bom_forecast_data.update()


class BOMForecastData:
    """Get data from BOM."""

    def __init__(self, product_id):
        """Initialize the data object."""
        self._product_id = product_id

    def get_reading(self, condition, index):
        """Return the value for the given condition."""
        _LOGGER.debug("get_reading for %s and %s", condition, index)
        if condition == 'detailed_summary':
            if PRODUCT_ID_LAT_LON_LOCATION[self._product_id][3] == 'City':
                detailed_summary = self._data.find(_FIND_QUERY_2.format(index)).text
            else:
                detailed_summary = self._data.find(
                    _FIND_QUERY.format(index, 'forecast')).text
            return (detailed_summary[:251] + '...') if len(
                detailed_summary) > 251 else detailed_summary

        if condition == 'uv_alert':
            if PRODUCT_ID_LAT_LON_LOCATION[self._product_id][3] == 'City':
                _LOGGER.debug("City")
                uv_alert_data = self._data.find(_FIND_QUERY_3.format(index))
                _LOGGER.debug("uv_alert_data = %s", uv_alert_data)
                if uv_alert_data is not None:
                    uv_alert = uv_alert_data.text
                    _LOGGER.debug("uv_alert = %s", uv_alert)
                    return uv_alert
            else:
                _LOGGER.debug("not City")
                uv_alert_data = self._data.find(
                    _FIND_QUERY.format(index, 'uv_alert')).text
                _LOGGER.debug("uv_alert_data = %s", uv_alert_data)
                if uv_alert_data is not None:
                    uv_alert = self._data.find(
                        _FIND_QUERY.format(index, 'uv_alert')).text
                    _LOGGER.debug("uv_alert = %s", uv_alert)
                    return uv_alert

        if condition == 'fire_danger':
            if PRODUCT_ID_LAT_LON_LOCATION[self._product_id][3] == 'City':
                _LOGGER.debug("City")
                fire_danger_data = self._data.find(_FIND_QUERY_4.format(index))
                _LOGGER.debug("fire_danger_data = %s", fire_danger_data)
                if fire_danger_data is not None:
                    fire_danger = fire_danger_data.text.strip()
                    if fire_danger == '':
                        # Check if there are sub-tags.
                        fire_danger_data_paragraphs = fire_danger_data.findall("./p")
                        if fire_danger_data_paragraphs is not None:
                            paragraphs = [paragraph.text for paragraph in fire_danger_data_paragraphs]
                            return ", ".join(paragraphs)
                    return fire_danger
            else:
                _LOGGER.debug("not City")
                fire_danger_data = self._data.find(
                    _FIND_QUERY.format(index, 'fire_danger')).text
                _LOGGER.debug("fire_danger_data = %s", fire_danger_data)
                if fire_danger_data is not None:
                    fire_danger = self._data.find(
                        _FIND_QUERY.format(index, 'fire_danger')).text
                    _LOGGER.debug("fire_danger = %s", fire_danger)
                    return fire_danger

        find_query = (_FIND_QUERY.format(index, SENSOR_TYPES[condition][0]))
        state = self._data.find(find_query)

        if condition == 'icon':
            return ICON_MAPPING[state.text]
        if state is None:
            if condition == 'possible_rainfall':
                return '0 mm'
            return 'n/a'
        s = state.text
        return (s[:251] + '...') if len(s) > 251 else s

    def get_issue_time_local(self):
        """Return the issue time of forecast."""
        issue_time = self._data.find("./amoc/next-routine-issue-time-local")
        if issue_time is None:
            return 'n/a'
        else:
            return issue_time.text

    def get_start_time_local(self, index):
        """Return the start time of forecast."""
        return self._data.find("./forecast/area[@type='location']/"
                               "forecast-period[@index='{}']".format(
            index)).get("start-time-local")

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Get the latest data from BOM."""
        file_obj = io.BytesIO()
        ftp = ftplib.FTP('ftp.bom.gov.au')
        ftp.login()
        ftp.cwd('anon/gen/fwo/')
        ftp.retrbinary('RETR ' + self._product_id + '.xml', file_obj.write)
        file_obj.seek(0)
        ftp.quit()
        tree = xml.etree.ElementTree.parse(file_obj)
        self._data = tree.getroot()


def closest_product_id(lat, lon):
    """Return the closest product ID to our lat/lon."""

    def comparable_dist(product_id):
        """Create a psudeo-distance from latitude/longitude."""
        product_id_lat = PRODUCT_ID_LAT_LON_LOCATION[product_id][0]
        product_id_lon = PRODUCT_ID_LAT_LON_LOCATION[product_id][1]
        return (lat - product_id_lat) ** 2 + (lon - product_id_lon) ** 2

    return min(PRODUCT_ID_LAT_LON_LOCATION, key=comparable_dist)
