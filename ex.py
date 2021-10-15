#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import binascii
import logging
import time

from bleak import discover
from bleak import BleakClient

# typing
if False:
    from bleak.backends.device import BLEDevice


logger = logging.getLogger(__name__)


class Scanner:
    def __init__(self):
        self.devices_dict = {}
        self.devices_list = []
        self.receive_data = []
        self.walking_belt_candidates = []  # type: list[BLEDevice]

    async def scan(self):
        logger.info("Scanning for peripherals...")
        dev = await discover()
        for i in range(len(dev)):
            # Print the devices discovered
            info_str = ', '.join(["[%2d]" % i, str(dev[i].address), str(dev[i].name), str(dev[i].metadata["uuids"])])
            logger.info("Device: %s" % info_str)

            # Put devices information into list
            self.devices_dict[dev[i].address] = []
            self.devices_dict[dev[i].address].append(dev[i].name)
            self.devices_dict[dev[i].address].append(dev[i].metadata["uuids"])
            self.devices_list.append(dev[i].address)

            if 'walkingpad' in dev[i].name.lower():
                self.walking_belt_candidates.append(dev[i])


class WalkingPad:
    MODE_STANDBY = 2
    MODE_MANUAL = 1
    MODE_AUTOMAT = 0

    PREFS_MAX_SPEED = 3
    PREFS_START_SPEED = 4
    PREFS_START_INTEL = 5
    PREFS_SENSITIVITY = 6
    PREFS_DISPLAY = 7
    PREFS_CHILD_LOCK = 9
    PREFS_UNITS = 8
    PREFS_TARGET = 1

    TARGET_NONE = 0
    TARGET_DIST = 1
    TARGET_CAL = 2
    TARGET_TIME = 3

    BUTTON_None = 0
    BUTTON_Down = 4
    BUTTON_Stop = 3
    BUTTON_Up = 2
    BUTTON_long_mode = -6
    BUTTON_up = -4
    BUTTON_mode = -6

    PAYLOADS_255 = [
        [247, 165, 96, 74, 77, 147, 113, 41, 201, 253],
        [247, 165, 96, 74, 58, 60, 113, 41, 95, 253],
        [247, 165, 96, 74, 15, 165, 113, 41, 157, 253],
        [247, 165, 96, 74, 21, 129, 113, 41, 127, 253],
        [247, 165, 96, 74, 45, 189, 115, 171, 87, 253],
        [247, 165, 96, 74, 49, 42, 113, 41, 68, 253],
        [247, 165, 96, 74, 58, 60, 113, 41, 95, 253],
        [247, 165, 96, 74, 77, 147, 113, 41, 201, 253],
    ]

    @staticmethod
    def int2byte(val, width=3):
        return [(val >> (8 * (width - 1 - i)) & 0xff) for i in range(width)]

    @staticmethod
    def byte2int(val, width=3):
        return sum([(val[i] << (8 * (width - 1 - i))) for i in range(width)])

    @staticmethod
    def fix_crc(cmd):
        cmd[-2] = sum(cmd[1:-2]) % 256
        return cmd


class WalkingPadCurStatus:
    def __init__(self):
        self.raw = None
        self.dist = 0
        self.time = 0
        self.steps = 0
        self.speed = 0
        self.controller_button = 0
        self.app_speed = 0
        self.belt_state = 0
        self.manual_mode = 0
        self.rtime = 0

    def load_from(self, cmd):
        self.raw = bytearray(cmd)
        self.belt_state = cmd[2]
        self.speed = cmd[3]
        self.manual_mode = cmd[4]
        self.time = WalkingPad.byte2int(cmd[5:])
        self.dist = WalkingPad.byte2int(cmd[8:])
        self.steps = WalkingPad.byte2int(cmd[11:])
        self.app_speed = cmd[14]  # / 30
        self.controller_button = cmd[16]
        self.rtime = time.time()

    @staticmethod
    def check_type(cmd):
        return bytes(cmd[0:2]) == bytes([248, 162])

    @staticmethod
    def from_data(cmd):
        if not WalkingPadCurStatus.check_type(cmd):
            raise ValueError('Incorrect message type, could not parse')
        m = WalkingPadCurStatus()
        m.load_from(cmd)
        return m

    def __str__(self):
        return 'WalkingPadCurStatus(dist=%s, time=%s, steps=%s, speed=%s, state=%s, ' \
               'mode=%s, app_speed=%s, button=%s, rest=%s)' \
               % (self.dist / 100, self.time, self.steps, self.speed / 10, self.belt_state,
                  self.manual_mode, self.app_speed / 30 if self.app_speed > 0 else 0, self.manual_mode,
                  binascii.hexlify(bytearray([self.raw[15], self.raw[17]])).decode('utf8'))


class WalkingPadLastStatus:
    def __init__(self):
        self.raw = None
        self.dist = 0
        self.time = 0
        self.steps = 0
        self.rtime = 0

    def load_from(self, cmd):
        self.raw = bytearray(cmd)
        self.time = WalkingPad.byte2int(cmd[8:])
        self.dist = WalkingPad.byte2int(cmd[11:])
        self.steps = WalkingPad.byte2int(cmd[14:])
        self.rtime = time.time()

    @staticmethod
    def check_type(cmd):
        return bytes(cmd[0:2]) == bytes([248, 167])

    @staticmethod
    def from_data(cmd):
        if not WalkingPadLastStatus.check_type(cmd):
            raise ValueError('Incorrect message type, could not parse')
        m = WalkingPadLastStatus()
        m.load_from(cmd)
        return m

    def __str__(self):
        return 'WalkingPadLastStatus(dist=%s, time=%s, steps=%s, rest=%s)' \
               % (self.dist / 100, self.time, self.steps, binascii.hexlify(self.raw[2:8]).decode('utf8'))


class Controller:
    def __init__(self, address=None, do_read_chars=True):
        self.address = address
        self.do_read_chars = do_read_chars
        self.log_messages_info = True

        self.char_fe01 = None
        self.char_fe02 = None
        self.client = None
        self.last_raw_cmd = None
        self.last_cmd_time = None
        self.last_status = None
        self.last_record = None
        self.minimal_cmd_space = 0.69

        self.handler_cur_status = None
        self.handler_last_status = None
        self.handler_message = None

    async def __aenter__(self):
        await self.run()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    def notif_handler(self, sender, data):
        logger_fnc = logger.info if self.log_messages_info else logger.debug
        logger_fnc('Msg: %s' % (', '.join('{:02x}'.format(x) for x in data)))
        already_notified = False

        if WalkingPadCurStatus.check_type(data):
            m = WalkingPadCurStatus.from_data(data)
            self.last_status = m
            already_notified = True
            self.on_cur_status_received(sender, m)
            if self.handler_cur_status:
                self.handler_cur_status(sender, m)
            logger_fnc('Status: %s' % (m,))

        elif WalkingPadLastStatus.check_type(data):
            m = WalkingPadLastStatus.from_data(data)
            self.last_record = None
            already_notified = True
            self.on_last_status_received(sender, m)
            if self.handler_last_status:
                self.handler_last_status(sender, m)
            logger_fnc('Record: %s' % (m,))

        self.on_message_received(sender, data, already_notified)
        if self.handler_message:
            self.handler_message(sender, data, already_notified)

    def on_message_received(self, sender, data, already_notified=False):
        """Override to use as message callback"""

    def on_cur_status_received(self, sender, status: WalkingPadCurStatus):
        """Override to receive current status"""

    def on_last_status_received(self, sender, status: WalkingPadLastStatus):
        """Override to receive last status"""

    def fix_crc(self, cmd):
        return WalkingPad.fix_crc(cmd)

    async def disconnect(self):
        logger.info("Disconnecting")
        await self.client.disconnect()

    async def connect(self, address=None):
        address = address or self.address
        if not address:
            raise ValueError('No address given to connect to')

        self.client = BleakClient(address)
        return await self.client.connect()

    async def send_cmd(self, cmd):
        self.fix_crc(cmd)
        if self.last_cmd_time and time.time() - self.last_cmd_time < self.minimal_cmd_space:
            to_sleep = max(0, min(time.time() - self.last_cmd_time, self.minimal_cmd_space))
            await asyncio.sleep(to_sleep)

        return await self.send_cmd_raw(cmd)

    async def send_cmd_raw(self, cmd):
        self.last_raw_cmd = cmd
        self.last_cmd_time = time.time()
        r = await self.client.write_gatt_char(self.char_fe02, cmd)
        return r

    async def switch_mode(self, mode: int):
        cmd = bytearray([247, 162, 2, mode, 0xff, 253])
        return await self.send_cmd(cmd)

    async def change_speed(self, speed: int):
        cmd = bytearray([247, 162, 1, speed, 0xff, 253])
        return await self.send_cmd(cmd)

    async def stop_belt(self):
        return await self.change_speed(0)

    async def start_belt(self):
        cmd = bytearray([247, 162, 4, 1, 0xff, 253])
        return await self.send_cmd(cmd)

    async def ask_profile(self, profile_idx=0):
        cmd = bytearray(WalkingPad.PAYLOADS_255[profile_idx])
        return await self.send_cmd(cmd)

    async def ask_stats(self):
        cmd = bytearray([247, 162, 0, 0, 162, 253])
        return await self.send_cmd(cmd)

    async def ask_hist(self, mode=0):
        cmd = bytearray([247, 167, 170, 255, 80, 253] if mode == 0 else [247, 167, 170, 0, 81, 253])
        return await self.send_cmd(cmd)

    async def cmd_162_3_7(self, mode=0):
        cmd = bytearray([247, 162, 3, 7, 172, 253])
        return await self.send_cmd(cmd)

    async def set_pref_arr(self, key: int, arr):
        cmd = bytearray([247, 166, key, *arr, 172, 253])
        return await self.send_cmd(cmd)

    async def set_pref_int(self, key: int, val: int, stype: int = 0):
        arr = [stype, *WalkingPad.int2byte(val)]
        return await self.set_pref_arr(key, arr)

    async def set_pref_max_speed(self, speed):
        return await self.set_pref_int(WalkingPad.PREFS_MAX_SPEED, speed)

    async def set_pref_start_speed(self, speed):
        return await self.set_pref_int(WalkingPad.PREFS_START_SPEED, speed)

    async def set_pref_inteli(self, enabled=False):
        return await self.set_pref_int(WalkingPad.PREFS_START_INTEL, int(enabled))

    async def set_pref_sensitivity(self, sensitivity=3):  # 1 = high, 2 = medium, 3 = low
        return await self.set_pref_int(WalkingPad.PREFS_SENSITIVITY, sensitivity)

    async def set_pref_display(self, bit_mask: int):  # 7bits
        return await self.set_pref_int(WalkingPad.PREFS_DISPLAY, bit_mask)

    async def set_pref_child_lock(self, enabled=False):
        return await self.set_pref_int(WalkingPad.PREFS_CHILD_LOCK, int(enabled))

    async def set_pref_units_miles(self, enabled=False):
        return await self.set_pref_int(WalkingPad.PREFS_UNITS, int(enabled))

    async def set_pref_target(self, target_type: int = 0, value: int = 0):
        return await self.set_pref_int(WalkingPad.PREFS_TARGET, value, target_type)

    async def run(self, address=None):
        await self.connect(address)
        client = self.client

        x = await client.is_connected()
        logger.info("Connected: {0}".format(x))

        self.char_fe01 = None
        self.char_fe02 = None

        for service in client.services:
            logger.info("[Service] {0}: {1}".format(service.uuid, service.description))
            for char in service.characteristics:
                value = None
                if "read" in char.properties:
                    try:
                        if self.do_read_chars and char.uuid != '0000fe01-0000-1000-8000-00805f9b34fb':
                            value = bytes(await client.read_gatt_char(char.uuid))
                    except Exception as e:
                        logger.info('read failed for %s' % (char.uuid,))
                        value = str(e).encode()

                logger.info(
                    "\t[Characteristic] {0}: (Handle: {1}) ({2}) | Name: {3}, Value: {4} ".format(
                        char.uuid,
                        char.handle,
                        ",".join(char.properties),
                        char.description,
                        value,
                    )
                )

                if char.uuid.startswith('0000fe01'):
                    self.char_fe01 = char

                if char.uuid.startswith('0000fe02'):
                    self.char_fe02 = char

                for descriptor in char.descriptors:
                    value = await client.read_gatt_descriptor(descriptor.handle)
                    logger.info(
                        "\t\t[Descriptor] {0}: (Handle: {1}) | Value: {2} ".format(
                            descriptor.uuid, descriptor.handle, bytes(value)
                        )
                    )

        try:
            logger.info('Enabling notification for %s' % (self.char_fe01.uuid,))
            await client.start_notify(self.char_fe01.uuid, self.notif_handler)

        except Exception as e:
            logger.warning("Notify failed: %s" % (e,))

        logger.info('Service enumeration done')


