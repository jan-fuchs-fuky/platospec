#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# Author: Jan Fuchs <fuky@asu.cas.cz>
#
# Copyright (C) 2022 Astronomical Institute, Academy Sciences of the Czech Republic, v.v.i.
#
# This file is part of PLATOSpec (ground based support of space missions PLATO
# and TESS - new Czech spectrograph in collaboration with European Southern
# Observatory).
#
# PLATOSpec is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PLATOSpec is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with PLATOSpec.  If not, see <http://www.gnu.org/licenses/>.
#
# $ ICE_CONFIG=/home/fuky/git/github/platospec/telescope/etc/ice_server.cfg ./ascol_server.py
#

import os
import sys
import time
import argparse
import logging
import traceback
import sdnotify
import configparser
import ctypes
import multiprocessing
import math
import uuid
import queue
import socket
import Ice

from telnetlib import Telnet
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from subprocess import check_output
from astropy.time import Time

SCRIPT_PATH = os.path.dirname(os.path.realpath(os.path.abspath(__file__)))
sys.path.append(SCRIPT_PATH)
sys.path.append("%s/../python" % SCRIPT_PATH)

import PlatoSpec

ASCOL_SERVER_CFG = "%s/../etc/ascol_server.cfg" % SCRIPT_PATH
ASCOL_SERVER_LOG = "%s/../log/ascol_server_%%s.log" % SCRIPT_PATH

def create_argument_parser():

    parser = argparse.ArgumentParser(
        description="ASCOL server.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="")

    parser.add_argument("-c", "--config", default=ASCOL_SERVER_CFG, type=str, metavar="FILENAME_CFG",
                        help="Load configuration from FILENAME_CFG.")

    return parser

def init_logger(logger, filename):
    formatter = logging.Formatter("%(asctime)s - %(name)s[%(process)d] - %(levelname)s - %(message)s")

    # DBG
    #formatter = logging.Formatter(
    #    ("%(asctime)s - %(name)s[%(process)d] - %(levelname)s - "
    #     "%(filename)s:%(lineno)s - %(funcName)s() - %(message)s - "))

    fh = RotatingFileHandler(filename, maxBytes=1048576, backupCount=10)
    #fh.setLevel(logging.INFO)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)

    #logger.setLevel(logging.INFO)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(fh)

class ASCOLServerProcess(multiprocessing.Process):

    dt_format = "%d-%m-%Y %H:%M:%S"
    date_format = "%d-%m-%Y"

    def __init__(self, name, cfg, events_mp, manager_mp):
        self.name = name
        self.cfg = cfg
        self.events_mp = events_mp
        self.manager_mp = manager_mp
        super(ASCOLServerProcess, self).__init__(name=name)

        self.logger = logging.getLogger("ascol_server_%s" % name)
        init_logger(self.logger, ASCOL_SERVER_LOG % name)
        self.logger.info("Starting process '%s'" % name)

        self.sd_notifier = sdnotify.SystemdNotifier()

    # socket
    #def ascol_read_until(self, expected, timeout):
    #    data = self.client.recv()
    #    return data

    def ascol_send(self, cmd, frequent=False):
        if frequent:
            logger_fce = self.logger.debug
        else:
            logger_fce = self.logger.info

        data = "%s\r\n" % cmd

        # socket
        #self.client.send(data.encode("ascii"))
        self.client.write(data.encode("ascii"))

        if cmd.startswith("GLLG "):
            cmd = "%s ****" % cmd.split()[0]

        answer = self.client.read_until(b"\r\n", self.cfg["ascol"]["timeout"]).decode("ascii").strip()
        if answer != "ERR":
            logger_fce("ASCOL '%s' => '%s'" % (cmd, answer))
        else:
            self.logger.error("ASCOL '%s' => '%s'" % (cmd, answer))

        return answer

    def loop(self):
        user_cmds = []
        try:
            for counter in range(10):
                item = self.manager_mp["cmd_queue"].get_nowait()
                user_cmds.append(item)
        except queue.Empty:
            pass

        for item in user_cmds:
            cmd_uuid, cmd = item
            begin = time.perf_counter()
            dt = datetime.now(tz=timezone.utc)
            result = self.ascol_send(cmd)
            duration = time.perf_counter() - begin
            self.logger.info("'%s' => '%s' (duration = %f, uuid = %s)" % (cmd, result, duration, cmd_uuid))

            with self.manager_mp["lock"]:
                self.manager_mp["cmd_results"][cmd_uuid] = [dt, result]

        results = {}
        for cmd in self.telescope_status_keys:
            begin = time.perf_counter()
            result = self.ascol_send(cmd, frequent=True)
            duration = time.perf_counter() - begin
            self.logger.info("'%s' => '%s' (duration = %f)" % (cmd, result, duration))
            results[cmd] = result

        with self.manager_mp["lock"]:
            for key in self.telescope_status_keys:
                self.manager_mp["telescope_status"][key] = results[key]

        # remove deprecated results
        dt = datetime.now(tz=timezone.utc)
        with self.manager_mp["lock"]:
            for cmd_uuid in self.manager_mp["cmd_results"].keys():
                cmd_dt, result = self.manager_mp["cmd_results"][cmd_uuid]
                diff = dt - cmd_dt
                if diff > timedelta(seconds=30):
                    tmp = self.manager_mp["cmd_results"].pop(cmd_uuid)

        self.sd_notifier.notify("WATCHDOG=1")

    def run(self):
        self.client = None

        with self.manager_mp["lock"]:
            self.telescope_status_keys = self.manager_mp["telescope_status"].keys()

        while (not self.events_mp["exit"].is_set()):
            try:
                if self.client is None:
                    # socket
                    #self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    #self.client.settimeout(self.cfg["ascol"]["timeout"])
                    #self.client.connect((self.cfg["ascol"]["host"], self.cfg["ascol"]["port"]))
                    self.client = Telnet(self.cfg["ascol"]["host"], self.cfg["ascol"]["port"], self.cfg["ascol"]["timeout"])
                    if self.ascol_send("GLLG %s" % self.cfg["ascol"]["password"]) != "1":
                        raise Exception("ASCOL: wrong password")

                begin = time.perf_counter()
                self.loop()
                rest = 1 - (time.perf_counter() - begin)
                if rest > 0:
                    time.sleep(rest)
            except:
                if self.client is not None:
                    self.client.close()

                self.logger.exception("loop() exception")
                time.sleep(60)

class TelescopeInterface(PlatoSpec.Telescope):

    def __init__(self, manager_mp):
        self.manager_mp = manager_mp
        self.ascol_parser = ASCOLParser()

        name = "telescope_interface"
        self.logger = logging.getLogger("ascol_server_%s" % name)
        init_logger(self.logger, ASCOL_SERVER_LOG % name)
        self.logger.info("Starting process '%s'" % name)

    def run_ascol(self, cmd, current=None):
        result = "OK"

        cmd_uuid = uuid.uuid4()

        try:
            self.manager_mp["cmd_queue"].put_nowait([cmd_uuid, cmd])
        except:
            result = "ERR" # TODO: vkladat popis vyjimky
            self.logger.exception("manager_mp.put('%s', '%s') exception" % (cmd_uuid, cmd))
            return result

        # search result
        time.sleep(0.3)
        for counter in range(3):
            with self.manager_mp["lock"]:
                if cmd_uuid in self.manager_mp["cmd_results"]:
                    cmd_dt, result = self.manager_mp["cmd_results"].pop(cmd_uuid)
                    break

            time.sleep(1)
        else:
            result = "ERR" # TODO: odlisit od jinych chyb

        return result

    def get_status(self, current=None):
        telescope_status = PlatoSpec.TelescopeStatus()

        with self.manager_mp["lock"]:
            status = dict(self.manager_mp["telescope_status"])

        for key in status:
            self.logger.debug("%s = '%s'" % (key, status[key]))

            try:
                result = self.ascol_parser.parse(key, status[key], telescope_status)
            except:
                self.logger.exception("ascol_parser.parse('%s', '%s') exception" % (key, status[key]))

        return telescope_status

class ASCOLParser:

    def __init__(self):
        pass

    def parse(self, name, data, telescope_status=None):
        parser = "parse_%s" % name.lower()
        if not hasattr(self, parser):
            raise Exception("parser '%s' not found" % parser)

        parser_callback = getattr(self, parser)
        result = parser_callback(data, telescope_status)

        return result

    # 'GLST' => '0 0 4 4 0 3134 256'
    def parse_glst(self, data, telescope_status):
        result = {}
        items = data.split(" ")
        keys = ["telescope", "dome", "slit", "mirror_cover", "focus", "status_bits", "error_bits"]

        idx = 0
        for key in keys:
            value = items[idx]
            result[key] = int(value)
            idx += 1

        if telescope_status is not None:
            telescope_status.global_state.telescope = result["telescope"]
            telescope_status.global_state.dome = result["dome"]
            telescope_status.global_state.slit = result["slit"]
            telescope_status.global_state.mirror_cover = result["mirror_cover"]
            telescope_status.global_state.focus = result["focus"]
            telescope_status.global_state.status_bits = result["status_bits"]
            telescope_status.global_state.error_bits = result["error_bits"]

        return result

    # 'TRRD' => '1432747.510 -300001.09 1'
    def parse_trrd(self, data, telescope_status):
        result = {}
        ra, dec, position = data.split(" ")

        result["ra"] = ra
        result["dec"] = dec
        result["position"] = position

        if telescope_status is not None:
            telescope_status.coordinates.ra = ra
            telescope_status.coordinates.dec = dec
            telescope_status.coordinates.position = int(position)

        return result

    # 'TRSD' => '-10056422.54'
    def parse_trsd(self, data, telescope_status):
        result = {}
        result["dec_screw_distance"] = float(data)

        if telescope_status is not None:
            telescope_status.dec_screw_limit = float(data)

        return result

    # 'TRHD' => '179.9999 -149.9997'
    def parse_trhd(self, data, telescope_status):
        result = {}
        ha, da = data.split(" ")

        result["ha"] = ha
        result["da"] = da

        if telescope_status is not None:
            telescope_status.axes.ha = ha
            telescope_status.axes.da = da

        return result

    # 'GLUT' => '59674 212213.200'
    def parse_glut(self, data, telescope_status):
        result = {}
        mjd_date, mjd_time = data.split(" ")

        dt = Time(mjd_date, format="mjd", scale="utc").to_datetime(timezone.utc)
        dt = datetime.strptime("%04i-%02i-%02i %s +0000" % (dt.year, dt.month, dt.day, mjd_time), "%Y-%m-%d %H%M%S.%f %z")

        if telescope_status is not None:
            telescope_status.utc = dt.timestamp()

        return dt

    # 'TRUO' => '-25.0 20.0'
    def parse_truo(self, data, telescope_status):
        result = {}
        ra_offset, dec_offset = data.split(" ")

        if telescope_status is not None:
            telescope_status.user_offsets.ra = float(ra_offset)
            telescope_status.user_offsets.dec = float(dec_offset)

        return result

    # 'TRGO' => '0.0 0.0'
    def parse_trgo(self, data, telescope_status):
        result = {}
        ra_offset, dec_offset = data.split(" ")

        if telescope_status is not None:
            telescope_status.autoguider_offsets.ra = float(ra_offset)
            telescope_status.autoguider_offsets.dec = float(dec_offset)

        return result

    # 'TRUS' => '0000.00000 0000.00000 0'
    def parse_trus(self, data, telescope_status):
        result = {}
        ra_speed, dec_speed, active = data.split(" ")

        if telescope_status is not None:
            telescope_status.user_speeds.ra = float(ra_speed)
            telescope_status.user_speeds.dec = float(dec_speed)
            telescope_status.user_speeds.active = int(active)

        return result

    # 'TRS1' => '3600.00'
    def parse_trs1(self, data, telescope_status):
        result = {}

        if telescope_status is not None:
            telescope_status.speed1 = float(data)

        return result

    # 'TRS2' => '200.00'
    def parse_trs2(self, data, telescope_status):
        result = {}

        if telescope_status is not None:
            telescope_status.speed2 = float(data)

        return result

    # 'TRS3' => '35.00'
    def parse_trs3(self, data, telescope_status):
        result = {}

        if telescope_status is not None:
            telescope_status.speed3 = float(data)

        return result

    # 'TRSP' => '1262829.400 -494758.80 1'
    def parse_trsp(self, data, telescope_status):
        result = {}
        ra, dec, position = data.split(" ")

        if telescope_status is not None:
            telescope_status.setpoint.ra = ra
            telescope_status.setpoint.dec = dec
            telescope_status.setpoint.position = int(position)

        return result

    # 'FOPO' => '38.812'
    def parse_fopo(self, data, telescope_status):
        result = {}

        if telescope_status is not None:
            telescope_status.focus_position = float(data)

        return result

    # 'DOPO' => '179.80'
    def parse_dopo(self, data, telescope_status):
        result = {}

        if telescope_status is not None:
            telescope_status.dome_position = float(data)

        return result

    # 'TRCM' => '2'
    def parse_trcm(self, data, telescope_status):
        result = {}

        if telescope_status is not None:
            telescope_status.correction_model = int(data)

        return result

    # 'MEST' => '0000.0 0000.0 0000.0 0000.0 0000.0 016 011.3 008.3 025 0 0768.60 -0122.30 4095 0'
    def parse_mest(self, data, telescope_status):
        #  0: Brightness East (%05.1f) [kLux]
        #  1: Brightness North (%05.1f) [kLux]
        #  2: Brightness West (%05.1f) [kLux]
        #  3: Brightness South (%05.1f) [kLux]
        #  4: Brightness Max (%05.1f) [kLux]
        #  5: Humidity (%03d) [%]
        #  6: Temperature (%04.1f) [°C]
        #  7: Wind Speed (%04.1f) [m/s]
        #  8: Wind Direction (%03d) [°]
        #  9: Precipitation (1 – yes, 0 – no) [-]
        # 10: Atmospheric Pressure (%06.2f) [mbar]
        # 11: Pyrgeometer value (%06.2) [W/m2]
        # 12: Status Word [-]
        # 13: Meteo alarms
        result = {}
        items = data.split(" ")

        result["brightness_east"] = float(items[0])
        result["brightness_north"] = float(items[1])
        result["brightness_west"] = float(items[2])
        result["brightness_south"] = float(items[3])
        result["brightness_max"] = float(items[4])
        result["humidity"] = int(items[5])
        result["temperature"] = float(items[6])
        result["wind_speed"] = float(items[7])
        result["wind_direction"] = int(items[8])
        result["precipitation"] = int(items[9])
        result["atmospheric_pressure"] = float(items[10])
        result["pyrgeometer"] = float(items[11])
        result["status_word"] = int(items[12])
        result["meteo_alarms"] = int(items[13])

        if telescope_status is not None:
            telescope_status.meteo_status.humidity = result["humidity"]
            telescope_status.meteo_status.precipitation = result["precipitation"]
            telescope_status.meteo_status.status_word = result["status_word"]
            telescope_status.meteo_status.meteo_alarms = result["meteo_alarms"]
            telescope_status.meteo_status.wind_direction = result["wind_direction"]
            telescope_status.meteo_status.wind_speed = result["wind_speed"]
            telescope_status.meteo_status.brightness_east = result["brightness_east"]
            telescope_status.meteo_status.brightness_north = result["brightness_north"]
            telescope_status.meteo_status.brightness_west = result["brightness_west"]
            telescope_status.meteo_status.brightness_south = result["brightness_south"]
            telescope_status.meteo_status.brightness_max = result["brightness_max"]
            telescope_status.meteo_status.temperature = result["temperature"]
            telescope_status.meteo_status.atmospheric_pressure = result["atmospheric_pressure"]
            telescope_status.meteo_status.pyrgeometer = result["pyrgeometer"]

        return result

class ASCOLServer:

    def __init__(self, args):
        self.args = args

        process_name = "server"
        self.logger = logging.getLogger("ascol_server_%s" % process_name)
        init_logger(self.logger, ASCOL_SERVER_LOG % process_name)
        self.logger.info("Starting process '%s'" % process_name)
        self.logger.info("args = %s" % args)

        self.load_cfg()

        self.events_mp = {
            "exit": multiprocessing.Event(),
        }

        with multiprocessing.Manager() as m:
            manager_mp = {
                "telescope_status": m.dict(),
                "cmd_results": m.dict(),
                "cmd_queue": m.Queue(maxsize=10),
                "lock": m.Lock(),
            }

            keys = [ "GLUT", "TRS1", "TRS2", "TRS3", "TRSD", "DOPO", "FOPO", "GLST",
                     "TRUO", "TRGO", "TRUS", "TRRD", "TRSP", "TRHD", "MEST", "TRCM" ]

            for key in keys:
                manager_mp["telescope_status"][key] = ""

            ascol_server_process = ASCOLServerProcess("main", self.cfg, self.events_mp, manager_mp)
            ascol_server_process.daemon = True
            ascol_server_process.start()

            sd_notifier = sdnotify.SystemdNotifier()
            sd_notifier.notify("READY=1")

            with Ice.initialize(sys.argv) as communicator:
                adapter = communicator.createObjectAdapterWithEndpoints("TelescopeAdapter", "default -h %(host)s -p %(port)i" % self.cfg["server"])
                telescope = TelescopeInterface(manager_mp)
                adapter.add(telescope, communicator.stringToIdentity("Telescope"))
                adapter.activate()
                communicator.waitForShutdown()

        self.events_mp["exit"].set()

    def load_cfg(self):
        rcp = configparser.ConfigParser()
        rcp.read(self.args.config)

        self.cfg = {
            "server": {},
            "ascol": {},
        }

        server_callbacks = {
            "host": rcp.get,
            "port": rcp.getint,
        }
        self.run_cfg_callbacks("server", server_callbacks)

        ascol_callbacks = {
            "host": rcp.get,
            "port": rcp.getint,
            "password": rcp.get,
            "timeout": rcp.getint,
        }
        self.run_cfg_callbacks("ascol", ascol_callbacks)

        for section in self.cfg:
            for key in self.cfg[section]:
                if key == "password":
                    self.logger.info("cfg.%s.%s = ****" % (section, key))
                else:
                    self.logger.info("cfg.%s.%s = %s" % (section, key, self.cfg[section][key]))

    def run_cfg_callbacks(self, section, callbacks):
        for key in callbacks:
            self.cfg[section][key] = callbacks[key](section, key)

def main():
    parser = create_argument_parser()
    args = parser.parse_args()

    ascol_server = ASCOLServer(args)

if __name__ == '__main__':
    main()
