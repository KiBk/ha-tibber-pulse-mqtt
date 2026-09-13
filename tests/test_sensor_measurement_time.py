"""Sensor/dispatcher checks against actual HA classes (run in HA runtime CI)."""
import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    import homeassistant
except ModuleNotFoundError:
    raise unittest.SkipTest('Run this module with Home Assistant installed')

import test_dlms_cosem  # Set package paths without bootstrapping the integration.
from custom_components.tibber_pulse_mqtt.sensor import SensorManager, TibberSensor
from custom_components.tibber_pulse_mqtt.dispatcher import TibberDispatcher


class SensorMeasurementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.writes = []
        self.entities = []
        self.hass = SimpleNamespace(loop=asyncio.get_running_loop())
        self.manager = SensorManager(self.hass, SimpleNamespace(), self.add_entities)
        self.registry = SimpleNamespace(async_get_entity_id=lambda *args:'sensor.example_power')
        self.stamp = {'measurement_timestamp':'2025-07-08T10:30:00+00:00',
                      'measurement_timestamp_source':'home_assistant_time_zone'}

    def add_entities(self, entities):
        for entity in entities:
            entity._added_to_hass = True
            entity._schedule_state_write = lambda ent=entity:self.writes.append(
                (ent.native_value, copy.deepcopy(ent.extra_state_attributes)))
            self.entities.append(entity)

    async def update(self, value, stamp, code='1-0:1.7.0'):
        with patch('custom_components.tibber_pulse_mqtt.sensor.er.async_get', return_value=self.registry):
            await self.manager.add_or_update('synthetic', code, value, {'rssi':-50}, stamp)

    async def test_value_and_timestamp_are_written_atomically(self):
        await self.update(100,self.stamp)
        next_stamp = dict(self.stamp, measurement_timestamp='2025-07-08T10:30:02+00:00')
        await self.update(200,next_stamp)
        self.assertEqual([(v,a['measurement_timestamp']) for v,a in self.writes],
                         [(100,self.stamp['measurement_timestamp']),(200,next_stamp['measurement_timestamp'])])

    async def test_equal_power_has_distinct_recordable_attributes(self):
        await self.update(100,self.stamp)
        next_stamp = dict(self.stamp, measurement_timestamp='2025-07-08T10:30:02+00:00')
        await self.update(100,next_stamp)
        self.assertEqual([v for v,a in self.writes], [100,100])
        self.assertNotEqual(self.writes[0][1],self.writes[1][1])

    async def test_status_refresh_keeps_time_and_untimed_reading_clears_it(self):
        await self.update(100,self.stamp)
        self.manager.update_status_for_device('synthetic',{'rssi':-60})
        self.assertEqual(self.writes[-1][1]['measurement_timestamp'],self.stamp['measurement_timestamp'])
        await self.update(101,None)
        self.assertNotIn('measurement_timestamp',self.writes[-1][1])

    async def test_cumulative_energy_does_not_inherit_telegram_time(self):
        await self.update(12345,self.stamp,code='1-0:1.8.0')
        self.assertNotIn('measurement_timestamp',self.writes[-1][1])

    async def test_dispatcher_does_not_create_timestamp_sensors(self):
        calls=[]
        manager=SimpleNamespace(set_obis_units=lambda units:None,
                               add_or_update=lambda *args:calls.append(args))
        dispatcher=object.__new__(TibberDispatcher)
        dispatcher._devices={}
        dispatcher.hass=SimpleNamespace(config=SimpleNamespace(time_zone='UTC'))
        dispatcher._get_sensor_manager=lambda:manager
        dispatcher._sensor_manager_ready=lambda:True
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        with patch('custom_components.tibber_pulse_mqtt.dispatcher.call_sm_on_loop',
                   side_effect=lambda hass,func,*args:func(*args)):
            dispatcher._apply_obis_with_pulse_id('synthetic',{
                '1-0:1.7.0':100, '_units':{'1-0:1.7.0':'W'},
                '_measurement_time':{'local_time':now.isoformat(),'deviation_minutes':0}})
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1],'1-0:1.7.0')
        self.assertIn('measurement_timestamp',calls[0][4])
