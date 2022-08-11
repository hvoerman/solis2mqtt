#!/usr/bin/python3

import argparse
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from threading import Lock

import minimalmodbus
import yaml
from pysolar.radiation import get_radiation_direct
from pysolar.solar import get_altitude
from pysolar.util import get_sunrise_sunset_transit

from config import Config
from inverter import Inverter
from mqtt import Mqtt
from mqtt_discovery import DiscoverMsgNumber, DiscoverMsgSensor, DiscoverMsgSwitch

VERSION = "0.8.4"
CONFIG_FILE = "config.yaml"
SOLIS_MODBUS_CONFIG = "solis_modbus.yaml"


class Solis2Mqtt:

    def __init__(self):
        self.cfg = Config("config.yaml")
        self.register_cfg = ...
        self.load_register_cfg()
        self.inverter = Inverter(self.cfg["device"], self.cfg["slave_address"])
        self.inverter_lock = Lock()
        self.inverter_offline = False
        self.mqtt = Mqtt(self.cfg["inverter"]["name"], self.cfg["mqtt"])

    def load_register_cfg(self, register_data_file="solis_modbus.yaml") -> None:
        with open(register_data_file) as smfile:
            self.register_cfg = yaml.load(smfile, yaml.Loader)

    def generate_ha_discovery_topics(self) -> None:
        for entry in self.register_cfg:
            if entry["active"] and "homeassistant" in entry:
                topic = str(
                    f"homeassistant/{entry['homeassistant']['device']}"
                    + f"/{self.cfg['inverter']['name']}"
                    + f"/{entry['name']}/config"
                )

                # logging.info("HA topic: %s", topic)

                if entry["homeassistant"]["device"] == "sensor":
                    logging.info("Generating discovery topic for sensor: %s", entry["name"])
                    self.mqtt.publish(
                        topic=topic,
                        # f"homeassistant/sensor/{self.cfg['inverter']['name']}"
                        # + f"/{entry['name']}/config",
                        payload=str(
                            DiscoverMsgSensor(
                                entry["description"],
                                entry["name"],
                                entry["unit"],
                                entry["homeassistant"]["device_class"],
                                entry["homeassistant"]["state_class"],
                                self.cfg["inverter"]["name"],
                                self.cfg["inverter"]["model"],
                                self.cfg["inverter"]["manufacturer"],
                                VERSION,
                            )
                        ),
                        retain=True,
                    )
                elif entry["homeassistant"]["device"] == "number":
                    logging.info("Generating discovery topic for number: " + entry["name"])
                    self.mqtt.publish(
                        topic=topic,
                        # f"homeassistant/number/{self.cfg['inverter']['name']}"
                        # + f"/{entry['name']}/config",
                        payload=str(
                            DiscoverMsgNumber(
                                entry["description"],
                                entry["name"],
                                entry["homeassistant"]["min"],
                                entry["homeassistant"]["max"],
                                entry["homeassistant"]["step"],
                                self.cfg["inverter"]["name"],
                                self.cfg["inverter"]["model"],
                                self.cfg["inverter"]["manufacturer"],
                                VERSION,
                            )
                        ),
                        retain=True,
                    )
                elif entry["homeassistant"]["device"] == "switch":
                    logging.info("Generating discovery topic for switch: %s", entry["name"])
                    self.mqtt.publish(
                        topic=topic,
                        # f"homeassistant/switch/{self.cfg['inverter']['name']}"
                        # + f"/{entry['name']}/config",
                        payload=str(
                            DiscoverMsgSwitch(
                                entry["description"],
                                entry["name"],
                                entry["homeassistant"]["payload_on"],
                                entry["homeassistant"]["payload_off"],
                                self.cfg["inverter"]["name"],
                                self.cfg["inverter"]["model"],
                                self.cfg["inverter"]["manufacturer"],
                                VERSION,
                            )
                        ),
                        retain=True,
                    )
                else:
                    logging.error(
                        "Unknown homeassistant device type: %s",
                        entry["homeassistant"]["device"],
                    )

    def subscribe(self) -> None:
        for entry in self.register_cfg:
            if "write_function_code" in entry["modbus"]:
                if not self.mqtt.on_message:
                    self.mqtt.on_message = self.on_mqtt_message
                # logging.info("Subscribing to: " + self.cfg['inverter']['name'] + "/"
                #  + entry['name'] + "/set")
                # topic = self.cfg["inverter"]["name"] + "/" + entry["name"] + "/set"
                topic = f"{self.cfg['inverter']['name']}/{entry['name']}/set"
                logging.info("Subscribing to topic: %s", topic)
                # self.cfg["inverter"]["name"] + "/" + entry["name"] + "/set"
                self.mqtt.persistent_subscribe(topic)

    def read_composed_date(self, register: int, functioncode: int) -> str:
        year = self.inverter.read_register(register[0], functioncode=functioncode)
        month = self.inverter.read_register(register[1], functioncode=functioncode)
        day = self.inverter.read_register(register[2], functioncode=functioncode)
        hour = self.inverter.read_register(register[3], functioncode=functioncode)
        minute = self.inverter.read_register(register[4], functioncode=functioncode)
        second = self.inverter.read_register(register[5], functioncode=functioncode)
        return f"20{year:02d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"

    def on_mqtt_message(self, client, userdata, msg) -> None:
        for el in self.register_cfg:
            if el["name"] == msg.topic.split("/")[-2]:
                register_cfg = el["modbus"]
                break

        str_value = msg.payload.decode("utf-8")
        if "number_of_decimals" in register_cfg and register_cfg["number_of_decimals"] > 0:
            value = float(str_value)
        else:
            value = int(str_value)
        with self.inverter_lock:
            try:
                self.inverter.write_register(
                    register_cfg["register"],
                    value,
                    register_cfg["number_of_decimals"],
                    register_cfg["write_function_code"],
                    register_cfg["signed"],
                )
            except (minimalmodbus.NoResponseError, minimalmodbus.InvalidResponseError):
                if not self.inverter_offline:
                    logging.exception(
                        f"Error while writing message to inverter. Topic: '{msg.topic}, "
                        f"Value: '{str_value}', Register: '{register_cfg['register']}'."
                    )

    def main(self) -> int:

        date = datetime.now(timezone.utc)
        logging.info("Latitude: %s, longitude: %s", self.cfg["latitude"], self.cfg["longitude"])
        solar_altitude = get_altitude(self.cfg["latitude"], self.cfg["longitude"], date)
        sunrise, sunset, sunhigh = get_sunrise_sunset_transit(
            latitude_deg=self.cfg["latitude"], longitude_deg=self.cfg["longitude"], when=date
        )
        solar_radiation_direct = get_radiation_direct(date, solar_altitude)

        logging.info(
            "Solar position %s, radiation direct: %s",
            solar_altitude,
            solar_radiation_direct,
        )
        logging.info("Sunrise: %s", sunrise.isoformat())
        logging.info("Sunhigh: %s", sunhigh.isoformat())
        logging.info("Sunset : %s", sunset.isoformat())

        if solar_altitude < -1:
            return 2

        self.generate_ha_discovery_topics()
        self.subscribe()

        logging.debug("Inverter scan start at %s", datetime.now().isoformat())
        for entry in self.register_cfg:
            if not entry["active"] or "function_code" not in entry["modbus"]:
                continue

            try:
                if entry["modbus"]["read_type"] == "register":
                    with self.inverter_lock:
                        value = self.inverter.read_register(
                            registeraddress=entry["modbus"]["register"],
                            number_of_decimals=entry["modbus"]["number_of_decimals"],
                            functioncode=entry["modbus"]["function_code"],
                            signed=entry["modbus"]["signed"],
                        )

                elif entry["modbus"]["read_type"] == "long":
                    with self.inverter_lock:
                        value = self.inverter.read_long(
                            registeraddress=entry["modbus"]["register"],
                            functioncode=entry["modbus"]["function_code"],
                            signed=entry["modbus"]["signed"],
                        )

                elif entry["modbus"]["read_type"] == "composed_datetime":
                    with self.inverter_lock:
                        value = self.read_composed_date(
                            register=entry["modbus"]["register"],
                            functioncode=entry["modbus"]["function_code"],
                        )
            # NoResponseError occurs if inverter is off,
            # InvalidResponseError might happen when inverter is starting up or
            # shutting down during a request
            except (minimalmodbus.NoResponseError, minimalmodbus.InvalidResponseError):

                # in case we didn't have a exception before
                logging.info("Inverter not reachable for %s", entry["name"])
                self.inverter_offline = True

                if (
                    "homeassistant" in entry
                    and entry["homeassistant"]["state_class"] == "measurement"
                ):

                    value = 0
                else:
                    continue
            else:
                self.inverter_offline = False
                logging.info(
                    "Read %s - %s %s",
                    entry["description"],
                    value,
                    entry["unit"] if entry["unit"] else "",
                )

            self.mqtt.publish(f"{self.cfg['inverter']['name']}/{entry['name']}", value, retain=True)

        return 3 if self.inverter_offline and solar_altitude > 0 else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Solis inverter to mqtt bridge.")
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose logging")
    parser.add_argument("-s", "--service", action="store_true", help="run as service")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    rotating_handler = RotatingFileHandler(
        filename=os.path.splitext(os.path.basename(__file__))[0] + ".log",
        maxBytes=1024 * 1024 * 10,
        backupCount=5,
    )
    log_handlers = [rotating_handler]

    if args.service:
        # add loggging to: journalctl -u solis2mqtt.service
        log_handlers.append(logging.StreamHandler())
        log_format = (
            "%(levelname)s (%(filename)s, %(funcName)s(), line %(lineno)d) "
            + "- %(name)s - %(message)s"
        )
    else:
        log_format = (
            "%(asctime)s %(levelname)s (%(filename)s, %(funcName)s(), line %(lineno)d) "
            + "- %(name)s - %(message)s"
        )

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=log_handlers,
    )
    logging.info(
        "Starting up, version: %s, service: %s, debug: %s",
        VERSION,
        args.service,
        args.verbose,
    )

    try:
        exit_value = Solis2Mqtt().main()
    except Exception:
        logging.error("Main exception", exc_info=True)
        exit(1)

    if exit_value == 3:
        logging.info("Inverter unreachable, but sun almost up, exit(%s)", exit_value)
    elif exit_value == 2:
        logging.info("Sun is down more than -1 degree, so wait, exit(%s)", exit_value)
    else:
        logging.info("Normal operation, exit(%s)", exit_value)

    exit(exit_value)
