#! /usr/bin/env python3
# -*- coding: utf-8 -*-

#
# Author: Jan Fuchs <fuky@asu.cas.cz>
#
# Copyright (C) 2019-2022 Astronomical Institute, Academy Sciences of the Czech Republic, v.v.i.
#
# This file is part of Observe (Observing System for Ondrejov).
#
# Observe is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Observe is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Observe.  If not, see <http://www.gnu.org/licenses/>.
#
# https://www.riverbankcomputing.com/static/Docs/PyQt5/
#
# https://doc.qt.io/qtforpython/search.html
# https://doc.qt.io/qt-5/qimage.html
# https://doc.qt.io/qt-5/qgraphicsitem.html#itemChange
# https://docs.astropy.org/en/stable/io/fits/
# https://scikit-image.org/docs/stable/api/skimage.util.html#skimage.util.img_as_ubyte
# https://docs.astropy.org/en/stable/visualization/normalization.html
# https://docs.astropy.org/en/stable/api/astropy.visualization.ZScaleInterval.html
#
# help(matplotlib.colors.Colormap)
#
# https://matplotlib.org/examples/user_interfaces/embedding_in_qt5.html
#
# FITS:
#
#    CROTA2, CDELT1, CDELT2, PC001001
#    http://tdc-www.harvard.edu/software/wcstools/cphead.wcs.html
#    https://danmoser.github.io/notes/gai_fits-imgs.html
#    http://hosting.astro.cornell.edu/~vassilis/isocont/node17.html
#
#    https://docs.astropy.org/en/stable/visualization/wcsaxes/
#
#        plt.imshow(hdu.data, vmin=-2.e-5, vmax=2.e-4, origin='lower')
#
#    https://docs.astropy.org/en/stable/wcs/index.html#wcslint
#
# https://docs.astropy.org/en/stable/wcs/
#
#     astropy.wcs contains utilities for managing World Coordinate System (WCS)
#     transformations in FITS files. These transformations map the pixel locations in
#     an image to their real-world units, such as their position on the sky sphere.
#     These transformations can work both forward (from pixel to sky) and backward
#     (from sky to pixel).
#
# FITS World Coordinate System (WCS)
# https://fits.gsfc.nasa.gov/fits_wcs.html
#
# https://docs.python.org/3/library/operator.html#operator.methodcaller
#
# $ ssh -L 7624:192.168.224.116:7624 platospec-workstation.stel
#

import os
import sys
sys.path.append("%s/lib/python3/dist-packages" % os.path.expanduser("~"))

import matplotlib
matplotlib.use("Qt5Agg")
import io
import cv2
import time
import math
import subprocess
import multiprocessing
import threading
import traceback
import collections
import configparser
import logging
import humanize
import xmlrpc.client
import numpy as np
import matplotlib.pyplot as plt
import PyIndi
import Ice

from operator import methodcaller
from enum import Enum
from datetime import datetime, timezone, timedelta

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg

from PyQt5 import uic
from PyQt5.QtGui import QPixmap, QPen, QImage, QBrush, QColor
from PyQt5.QtMultimedia import QSound

from PyQt5.QtCore import QRunnable, QThreadPool, QObject, pyqtSlot, pyqtSignal, \
    Qt, QRectF, QTimer

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QWidget,
    QSizePolicy,
    QMessageBox,
    QVBoxLayout,
    QGridLayout,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QPushButton,
    QLabel,
)

from logging.handlers import RotatingFileHandler

from astropy.io import fits

from astropy.visualization import MinMaxInterval, ZScaleInterval, ImageNormalize, \
    LinearStretch, LogStretch, PowerStretch, SqrtStretch, SquaredStretch, AsinhStretch, \
    SinhStretch, HistEqStretch

from astropy.stats import gaussian_sigma_to_fwhm
from astropy.coordinates import Angle
from astropy import units

from skimage.util import img_as_ubyte
from skimage.transform import rotate

from photutils import centroid_com, centroid_1dg, centroid_2dg, fit_2dgaussian

from numpy.random import default_rng

SCRIPT_PATH = os.path.dirname(os.path.realpath(os.path.abspath(__file__)))
sys.path.append(SCRIPT_PATH)
sys.path.append("%s/../python" % SCRIPT_PATH)

import PlatoSpec

FIBER_POINTING_CLIENT_FIT = "%s/../share/indi_autoguider.fit" % SCRIPT_PATH
FIBER_POINTING_CLIENT_UI = "%s/../share/indi_autoguider.ui" % SCRIPT_PATH
FIBER_POINTING_CLIENT_CFG = "%s/../etc/indi_autoguider.cfg" % SCRIPT_PATH
TELESCOPE_ICE_CLIENT_CFG = "%s/../etc/IceTelescopeASCOL.config" % SCRIPT_PATH
FIBER_POINTING_CLIENT_LOG = "%s/../log/indi_autoguider_%%s.log" % SCRIPT_PATH
FIBER_POINTING_CLIENT_SPLASH_SCREEN = "%s/../share/splash_screen.jpg" % SCRIPT_PATH
FIBER_POINTING_CLIENT_SOUNDS = "%s/../sounds" % SCRIPT_PATH

# TODO: sdilet kod s fiber_gxccd_server.py
FIBER_GXCCD_STATUS = {
    "starting": 0,
    "ready": 1,
    "exposing": 2,
    "reading": 3,
    "failed": 255,
}

def init_logger(logger, filename):
    formatter = logging.Formatter("%(asctime)s - %(name)s[%(process)d] - %(levelname)s - %(message)s")

    # DBG
    #formatter = logging.Formatter(
    #    ("%(asctime)s - %(name)s[%(process)d] - %(levelname)s - "
    #     "%(filename)s:%(lineno)s - %(funcName)s() - %(message)s - "))

    #fh = TimedRotatingFileHandler(filename, when='D', interval=1, backupCount=365)
    fh = RotatingFileHandler(filename, maxBytes=100*1024**2, backupCount=10)
    #fh.setLevel(logging.DEBUG)
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)

    logger.setLevel(logging.INFO)
    #logger.setLevel(logging.DEBUG)
    logger.addHandler(fh)

class ClientStatus(Enum):

    IDLE = 0
    RUNNING = 1
    SUCCESS = 2
    FAILED = 3

class TelescopeClient():

    def __init__(self):
        # Initialize client attributes
        self.communicator = None
        self.telescope_proxy = None

    def connect(self, config_file):
        '''
        Connect to Telescope ICE server object.
        '''
        msg = 'Connecting to server...'
        print(msg)
        try:
            # Read client configuration
            msg = 'Config path: %s' % config_file
            print(msg)

            init_data = Ice.InitializationData()
            init_data.properties = Ice.createProperties()
            init_data.properties.load(config_file)
            self.communicator = Ice.initialize(sys.argv, init_data)

            # Read proxy values configuration.
            properties = self.communicator.getProperties()
            proxy_property = 'TelescopeDevice.Proxy'
            proxy = properties.getProperty(proxy_property)
            msg = 'Proxy=%s' % proxy
            print(msg)

            # Create proxy object
            obj = self.communicator.stringToProxy(proxy)
            self.telescope_proxy = PlatoSpec.TelescopePrx.checkedCast(obj)
            msg = 'Connected to Telescope server'
            print(msg)

            if not self.telescope_proxy:
                raise RuntimeError("Invalid proxy")
        except:
            print('Unknown execption...')
            traceback.print_exc()

    def run_ascol(self, cmd, msg):
        result = self.telescope_proxy.run_ascol(cmd)
        print("Execute %s, cmd: %s, result: %s" % (msg, cmd, result))
        if 'ERR' == result:
            raise Exception("Fail during %s" % msg)

    def disconnect(self):
        '''
        Disconnect from Telescope ICE server object.
        '''
        msg = 'Disconnecting from Telescope server...'
        print(msg)
        if self.communicator:
            try:
                self.communicator.destroy()
            except:
                print('Unknown execption...')
                traceback.print_exc()

    def wait(self, key, value, negate=False):
        not_str = ""

        for i in range(300):
            result = self.get_telescope_status()

            if negate:
                not_str = " NOT"
                if result[key] != value:
                    break
            else:
                if result[key] == value:
                    break

                if value == "AUTO_" and result[key].startswith("AUTO_"):
                    break

            print("%s: Waiting on%s %s => %s" % (datetime.now(), not_str, key, value))
            time.sleep(1)
        else:
            raise Exception("Telescope timeout: %s %s" % (key, value))

    def set_guider_absolute_offsets(self, ra, dec):
        self.run_ascol('TSGA %.1f %.1f' % (ra, dec), 'Set guider absolute offsets')

    def set_guider_relative_offsets(self, ra, dec):
        self.run_ascol('TSGR %.2f %.2f' % (ra, dec), 'Set guider relative offsets')

    def get_guider_offsets(self):
        telescope_status = self.telescope_proxy.get_status()

        result = [
            telescope_status.autoguider_offsets.ra,
            telescope_status.autoguider_offsets.dec,
        ]

        return result

    def set_guiding_mode(self, enable):
        value = 0
        if enable:
            value = 1

        self.run_ascol('TSGM %i' % value, 'Telescope set Guiding Mode On')

    def start_tracking_source(self, ra, dec):
        '''
        Send telescope to right ascension and declination coordinates and 
        enable the tracking using ASCOL software.
        '''
        msg = 'Starting TCS tracking to RA: %s DEC: %s' % (ra, dec)
        print(msg)

        try:
            self.run_ascol('DOCO 0', 'Dome camera OFF')
            self.run_ascol('DOLO 0', 'Dome lamp OFF')
            cmd = 'TSRA %s %s 1' % (ra, dec)
            self.run_ascol(cmd, 'Telescope set RA/DEC West')
            self.run_ascol('TGRA', 'Telescope go RA/DEC')

            time.sleep(3)
            result = self.get_telescope_status()
            if result['global_state.telescope'] == 'STOP':
                raise Exception("Bad coordinates %s" % cmd)

            self.run_ascol('TSGM 1', 'Telescope set Guiding Mode On')

            required_state = [
                ['global_state.telescope', 'TRACK'],
                ['global_state.slit', 'OPENED'],
                ['global_state.mirror_cover', 'OPENED'],
                ['global_state.dome', 'AUTO_STOP'],
                ['correction_model', '4'],
                ['correction_refraction_state', 'ON'],
                ['correction_model_state', 'ON'],
                ['dome_calibration', 'CALIBRATED'],
                ['dome_lamp', 'OFF'],
                ['dome_camera_power', 'OFF'],
            ]

            for key, value in required_state:
                self.wait(key, value)

            msg = 'TCS start tracking source procedure is ready'
            print(msg)

            return True

        except:
            print('Unknown execption...')
            traceback.print_exc()

    def stop_tracking_source(self):
        '''
        Stop source tracking using ASCOL software.
        '''
        msg = 'Starting TCS stop tracking source procedure'
        print(msg)

        try:
            self.run_ascol('TSGM 0', 'Telescope set Guiding Mode Off')
            self.run_ascol('TEST', 'Telescope Stop')

            self.wait('global_state.telescope', 'STOP')

            msg = 'TCS stop tracking source procedure is ready'
            print(msg)

            return True
        except:
            print('Unknown execption...')
            traceback.print_exc()

    def get_telescope_status(self):
        '''
        Return Telescope status.
        '''
        telescope_status = self.telescope_proxy.get_status()
        result = {}

        status_keys = [
            "utc",
            "speed1",
            "speed2",
            "speed3",
            "dec_screw_limit",
            "dome_position",
            "focus_position",
            "correction_model",
            "global_state.telescope",
            "global_state.dome",
            "global_state.slit",
            "global_state.mirror_cover",
            "global_state.focus",
            "global_state.status_bits",
            "global_state.error_bits",
            "user_offsets.ra",
            "user_offsets.dec",
            "autoguider_offsets.ra",
            "autoguider_offsets.dec",
            "user_speeds.ra",
            "user_speeds.dec",
            "user_speeds.active",
            "coordinates.ra",
            "coordinates.dec",
            "coordinates.position",
            "setpoint.ra",
            "setpoint.dec",
            "setpoint.position",
            "axes.ha",
            "axes.da",
            "meteo_status.humidity",
            "meteo_status.precipitation",
            "meteo_status.status_word",
            "meteo_status.meteo_alarms",
            "meteo_status.wind_direction",
            "meteo_status.wind_speed",
            "meteo_status.brightness_east",
            "meteo_status.brightness_north",
            "meteo_status.brightness_west",
            "meteo_status.brightness_south",
            "meteo_status.brightness_max",
            "meteo_status.temperature",
            "meteo_status.atmospheric_pressure",
            "meteo_status.pyrgeometer",
        ]

        global_state2str = {
            "global_state.telescope": ["OFF", "STOP", "TRACK", "SLEW", "SLEWHADA", "SYNC", "PARK"],
            "global_state.slit": ["UNKNOWN", "OPENING", "CLOSING", "OPENED", "CLOSED"],
            "global_state.mirror_cover": ["UNKNOWN", "OPENING", "CLOSING", "OPENED", "CLOSED"],
            "global_state.dome": ["STOP", "PLUS", "MINUS", "AUTO_STOP", "AUTO_PLUS", "AUTO_MINUS", "SYNC", "SLEW_MINUS", "SLEW_PLUS", "SLIT"],
            "global_state.focus": ["STOPPED", "MANUAL-", "MANUAL+", "POSITIONING"],
        }

        meteo_units = {
            "meteo_status.humidity": "%",
            #"meteo_status.precipitation": "",
            "meteo_status.wind_direction": "°",
            "meteo_status.wind_speed": "m/s",
            "meteo_status.brightness_east": "kLux",
            "meteo_status.brightness_north": "kLux",
            "meteo_status.brightness_west": "kLux",
            "meteo_status.brightness_south": "kLux",
            "meteo_status.brightness_max": "kLux",
            "meteo_status.temperature": "°C",
            "meteo_status.atmospheric_pressure": "mbar",
            "meteo_status.pyrgeometer": "W/㎡",
        }

        for key in status_keys:
            value = telescope_status
            for name in key.split("."):
                if not hasattr(value, name):
                    raise Exception("ICE value '%s' not found (name = %s)" % (key, name))
                value = getattr(value, name)

            if key == "utc":
                value = str(datetime.fromtimestamp(value, tz=timezone.utc))

            suffix = ""
            if key in meteo_units:
                suffix = " %s" % meteo_units[key]

            if key in global_state2str:
                try:
                    value = global_state2str[key][value]
                except:
                    value = "UNKNOWN"

            result[key] = "%s%s" % (value, suffix)

        status_bits2str = {
              0: ["OFF", "ON", "remote_mode"],                       #  0 System is in REMOTE mode
              1: ["OFF", "ON", "control_voltage"],                   #  1 Control voltage is turned on
              2: ["UNCALIBRATED", "CALIBRATED", "ha_calibration"],   #  2 HA axis is calibrated
              3: ["UNCALIBRATED", "CALIBRATED", "da_calibration"],   #  3 DEC axis is calibrated
              4: ["UNCALIBRATED", "CALIBRATED", "dome_calibration"], #  4 Dome is calibrated
              5: ["OFF", "ON", "correction_refraction_state"],       #  5 Correction of refraction is turned on
              6: ["OFF", "ON", "correction_model_state"],            #  6 Correction model function is turned on
              7: ["OFF", "ON", "tracking"],                          #  7 Guide mode is turned on
              8: ["", "MOVE", None],                                 #  8 Focusing is in move
              9: ["OFF", "ON", "dome_lamp"],                         #  9 Dome light is on
              10: ["OFF", "ON", "vent_tube_state"],                  # 10 Vent on tube is on
              11: ["LOCKED", "UNLOCKED", "ha_lock"],                 # 11 HA axis unlocked
              12: ["LOCKED", "UNLOCKED", "da_lock"],                 # 12 DEC axis unlocked
              13: ["OFF", "ON", "dome_camera_power"],                # 13 Dome camera is on
        }

        for shift in range(14):
            value = (telescope_status.global_state.status_bits >> shift) & 1
            label = status_bits2str[shift][2]
            if label is not None:
                result[label] = status_bits2str[shift][value]

        error_bits2str = {
            0: "Error of motor or regulation of HA",
            1: "Error of motor or regulation of DA",
            2: "Negative restriction of HA",
            3: "Positive restriction of HA",
            4: "Negative restriction of DA",
            5: "Positive restriction of DA",
            6: "general error",
            7: "telescope error",
            8: "dome or slit error",
            9: "focus error",
            10: "meteo error",
        }

        errors = []
        error_flag = False
        for shift in range(11):
            value = (telescope_status.global_state.error_bits >> shift) & 1
            if value:
                error_flag = True
                error_msg = error_bits2str[shift]
                errors.append(error_msg)
                print("Telescope error: %s" % error_msg)

        if error_flag:
            #raise Exception("Telescope errors: %s" % ", ".join(errors))
            result["error_flag"] = "ON"
        else:
            print("Telescope Alright")
            result["error_flag"] = "OFF"

        return result

    def get_weather_status(self):
        '''
        Return weather information.
        '''
        telescope_status = self.telescope_proxy.get_status()
        weather = telescope_status.meteo_status

        result = {}
        result['humidity'] = weather.humidity
        result['wind_direction'] = weather.wind_direction
        result['wind_speed'] = weather.wind_speed
        result['temperature'] = weather.temperature
        result['atmospheric_pressure'] = weather.atmospheric_pressure

        return result

class IndiClient(PyIndi.BaseClient):
    def __init__(self, blob_event):
        super(IndiClient, self).__init__()

        self.blob_event = blob_event

    def newDevice(self, d):
        print("New device %s" % d.getDeviceName())

    def newProperty(self, p):
        #print("New property %s for device %s (getSwitch() => %s)" % (p.getName(), p.getDeviceName(), p.getSwitch()))
        pass

    def removeProperty(self, p):
        pass

    def newBLOB(self, bp):
        print("new BLOB ", bp.name)
        self.blob_event.set()

    def newSwitch(self, svp):
        pass

    def newNumber(self, nvp):
        for item in nvp:
            print("%s = %s" % (item.name, item.value))

    def newText(self, tvp):
        #for item in tvp:
        #    print("%s = %s" % (item.name, item.text))
        pass

    def newLight(self, lvp):
        pass

    def newMessage(self, d, m):
        print(d, m)

    def serverConnected(self):
        print("Server connected")

    def serverDisconnected(self, code):
        print("Server disconnected")

class WorkerSignals(QObject):
    '''
    Defines the signals available from a running worker thread.

    Supported signals are:

    finished
        No data

    error
        `tuple` (exctype, value, traceback.format_exc())

    result
        `object` data returned from processing, anything

    progress
        `int` indicating % progress

    '''
    finished = pyqtSignal(str)
    error = pyqtSignal(str, tuple)
    result = pyqtSignal(str, object)
    progress = pyqtSignal(str, object)

class Worker(QRunnable):
    '''
    Worker thread

    Inherits from QRunnable to handler worker thread setup, signals and wrap-up.

    :param callback: The function callback to run on this worker thread. Supplied args and
                     kwargs will be passed through to the runner.
    :type callback: function
    :param args: Arguments to pass to the callback function
    :param kwargs: Keywords to pass to the callback function

    '''

    def __init__(self, fn, *args, **kwargs):
        super(Worker, self).__init__()

        # Store constructor arguments (re-used for processing)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.thread_exit = kwargs.pop("thread_exit")

        # Add the callback to our kwargs
        self.kwargs['progress_callback'] = self.signals.progress

        gui = kwargs.pop("gui")
        self.signals.result.connect(gui.thread_result)
        self.signals.finished.connect(gui.thread_finished)
        self.signals.progress.connect(gui.thread_progress)
        self.signals.error.connect(gui.thread_error)

    @pyqtSlot()
    def run(self):
        '''
        Initialise the runner function with passed args, kwargs.
        '''

        # Retrieve args/kwargs here; and fire processing using them
        try:
            result = self.fn(*self.args, **self.kwargs)
        except:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit(self.kwargs["name"], (exctype, value, traceback.format_exc()))
        else:
            self.signals.result.emit(self.kwargs["name"], result) # Return the result of the processing
        finally:
            self.thread_exit.set()
            self.signals.finished.emit(self.kwargs["name"]) # Done

class TelescopeThread:

    def __init__(self, gui):
        self.gui = gui
        self.cfg = gui.cfg
        self.is_stop = gui.is_stop

        self.telescope_client = TelescopeClient()
        self.telescope_client.connect(TELESCOPE_ICE_CLIENT_CFG)

    def run_read(self):
        self.telescope_client.set_guiding_mode(True)

        while not self.is_stop():
            guider_offset_ra, guider_offset_dec = self.telescope_client.get_guider_offsets()

            data = {
                "guider_offset_ra": guider_offset_ra,
                "guider_offset_dec": guider_offset_dec,
            }

            self.progress_callback.emit(self.name, data)
            time.sleep(1)

        self.telescope_client.set_guiding_mode(False)

    def run_command(self, command):
        for item in command:
            result = True

            if item[0] == "set_guider_relative_offsets":
                self.telescope_client.set_guider_relative_offsets(item[1], item[2])
            elif item[0] == "set_guider_absolute_offsets":
                self.telescope_client.set_guider_absolute_offsets(item[1], item[2])

            data = {
                "command": item,
                "result": result,
            }

            self.progress_callback.emit(self.name, data)
            time.sleep(0.1)

    def run(self, progress_callback, name, command):
        self.progress_callback = progress_callback
        self.name = name

        self.logger = self.gui.thread_logger[name]
        self.logger.info("Starting process '%s'" % name)

        if name == "telescope_read":
            self.run_read()
        else:
            self.run_command(command)

        self.telescope_client.disconnect()

        return "Done."

class GuiderThread:

    def __init__(self, gui):
        self.gui = gui
        self.cfg = gui.cfg
        self.is_stop = gui.is_stop

    def run_read(self):

        while not self.gui.exit.is_set():
            fits = None

            # TODO: osetrit pripadnou vyjimku
            ccd_exposure = self.device_ccd.getNumber("CCD_EXPOSURE")
            print("ccd_exposure %f" % ccd_exposure[0].value)

            if self.blob_event.is_set():
                print("data are ready")
                for blob in self.ccd_ccd1:
                    fits = blob.getblobdata()
                    self.blob_event.clear()

            status = {
                "ccd_exposure": ccd_exposure[0].value,
                "fits": fits,
            }

            self.progress_callback.emit(self.name, status)
            time.sleep(1)

    # TODO
    def run_command(self, command):
        ccd_exposure = self.device_ccd.getNumber("CCD_EXPOSURE")

        for item in command:
            cmd = item[0]
            if cmd == "gain":
                new_value = item[1]
                gain = self.device_ccd.getNumber("CCD_GAIN")
                old_value = gain[0].value
                gain[0].value = new_value
                self.indiclient.sendNewNumber(gain)

                data = {
                    "command": "gain",
                    "old_gain": old_value,
                    "new_gain": new_value,
                }

                self.progress_callback.emit(self.name, data)
                continue

            cmd, expose_time, count_repeat, delay_after_exposure = item
            print(item)

            for idx in range(1, count_repeat+1):
                ccd_exposure[0].value = expose_time
                self.indiclient.sendNewNumber(ccd_exposure)
                result = None

                while not self.is_stop():
                    time.sleep(1)
                    ccd_exposure = self.device_ccd.getNumber("CCD_EXPOSURE")
                    print("guider_command_thread: ccd_exposure %f" % ccd_exposure[0].value)

                    if math.isclose(ccd_exposure[0].value, 0.0):
                        print("guider_command_thread: expose success")
                        break

                if self.is_stop():
                    return

                data = {
                    "command": item,
                    "result": result,
                }

                #self.progress_callback.emit(self.name, data)
                time.sleep(delay_after_exposure)

    def run(self, progress_callback, name, command):
        self.progress_callback = progress_callback
        self.name = name

        self.logger = self.gui.thread_logger[name]
        self.logger.info("Starting process '%s'" % name)

        self.blob_event = threading.Event()
        self.blob_event.clear()

        self.indiclient = IndiClient(self.blob_event)
        #self.indiclient.setServer("localhost", 7624)
        self.indiclient.setServer("192.168.224.116", 7624)

        if not self.indiclient.connectServer():
            raise Exception("No indiserver running on %s:%i" % (self.indiclient.getHost(), self.indiclient.getPort()))

        ccd = "QHY CCD QHY5LII-M-60b7e"
        #ccd = "CCD Simulator"
        self.device_ccd = self.indiclient.getDevice(ccd)
        for i in range(5):
            if self.device_ccd:
                break
            time.sleep(1)
            self.device_ccd = self.indiclient.getDevice(ccd)
        else:
            raise Exception("%s not found" % ccd)

        ccd_connect = self.device_ccd.getSwitch("CONNECTION")
        for i in range(10):
            if ccd_connect:
                break
            time.sleep(0.5)
            ccd_connect = self.device_ccd.getSwitch("CONNECTION")
        else:
            raise Exception("CONNECTION failed")

        if not self.device_ccd.isConnected():
            ccd_connect[0].s = PyIndi.ISS_ON  # the "CONNECT" switch
            ccd_connect[1].s = PyIndi.ISS_OFF # the "DISCONNECT" switch
            self.indiclient.sendNewSwitch(ccd_connect)

        ccd_exposure = self.device_ccd.getNumber("CCD_EXPOSURE")
        for i in range(10):
            if ccd_exposure:
                break
            time.sleep(0.5)
            ccd_exposure = self.device_ccd.getNumber("CCD_EXPOSURE")
        else:
            raise Exception("CCD_EXPOSURE failed")

        # we should inform the indi server that we want to receive the "CCD1" blob from this device
        self.indiclient.setBLOBMode(PyIndi.B_ALSO, ccd, "CCD1")

        self.ccd_ccd1 = self.device_ccd.getBLOB("CCD1")
        for i in range(10):
            if self.ccd_ccd1:
                break
            time.sleep(0.5)
            self.ccd_ccd1 = self.device_ccd.getBLOB("CCD1")
        else:
            raise Exception("CCD1 failed")

        if name == "guider_read":
            self.run_read()
        else:
            self.run_command(command)

        return "Done."

class MatplotlibCanvas(FigureCanvasQTAgg):
    """Ultimately, this is a QWidget (as well as a FigureCanvasAgg, etc.)."""

    def __init__(self, parent=None, width=4, height=4, dpi=100):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = fig.add_subplot(111)

        FigureCanvasQTAgg.__init__(self, fig)
        self.setParent(parent)

        FigureCanvasQTAgg.setSizePolicy(self,
                                   QSizePolicy.Expanding,
                                   QSizePolicy.Expanding)
        FigureCanvasQTAgg.updateGeometry(self)

class StarMatplotlibCanvas(MatplotlibCanvas):

    def plot_star(self, image, x, y):
        self.axes.cla()
        self.axes.imshow(image)
        self.axes.plot(x, y, color="#FF0000", marker='+', ms=50, mew=1)
        self.axes.set_ylim(0, 100)
        self.draw()

class SightGraphicsItem(QGraphicsItem):

    def __init__(self, width, height, color, x_SB=None, y_SB=None, rectangle=True):
        self.width = width
        self.height = height
        self.color = color
        self.x_SB = x_SB
        self.y_SB = y_SB
        self.rectangle = rectangle

        super(SightGraphicsItem, self).__init__()

        self.setFlag(QGraphicsItem.ItemSendsScenePositionChanges, True)

    def set_width_height(self, width, height):

        if (self.width != width) or (self.height != height):
            self.prepareGeometryChange()
            self.width = width
            self.height = height

    def paint(self, painter, option, widget):
        pen = QPen(self.color, 1, Qt.SolidLine)
        painter.setPen(pen)

        size = 25
        x_center = self.width / 2
        y_center = self.height / 2

        painter.drawLine(x_center-size, y_center, x_center+size, y_center)
        painter.drawLine(x_center, y_center-size, x_center, y_center+size)

        if self.rectangle:
            painter.drawRect(0, 0, self.width, self.height)

    def boundingRect(self):
        border_size = 10

        bleft = -border_size
        btop = -border_size
        bwidth = self.width + (border_size * 2)
        bheight = self.height + (border_size * 2)

        return QRectF(bleft, btop, bwidth, bheight)

    def mouseReleaseEvent(self, event):
        pos = event.pos()
        scene_pos = event.scenePos()

        x = scene_pos.x() - pos.x()
        y = scene_pos.y() - pos.y()

        print("mouseReleaseEvent", x, y, scene_pos.x(), scene_pos.y(), pos.x(), pos.y())

        if self.x_SB and self.y_SB:
            self.x_SB.setValue(x)
            self.y_SB.setValue(y)

        super(SightGraphicsItem, self).mouseReleaseEvent(event)

    def itemChange(self, change, value):

        if (change == QGraphicsItem.ItemPositionChange) and self.scene():
            rect = self.scene().sceneRect()

            # value is the new position.
            if not rect.contains(value):
                # Keep the item inside the scene rect.
                value.setX(min(rect.right(), max(value.x(), rect.left())))
                value.setY(min(rect.bottom(), max(value.y(), rect.top())))

        return super(SightGraphicsItem, self).itemChange(change, value)

class FiberPointingScene(QGraphicsScene):

    def __init__(self, parent=None):
        super(FiberPointingScene, self).__init__(parent)

#    def mousePressEvent(self, event):
#        point = event.scenePos()
#        print(point.x(), point.y())
#        super(FiberPointingScene, self).mousePressEvent(event)

class ClickableLabel(QLabel):

    def __init__(self, data, callback_clicked, parent=None):
        QLabel.__init__(self, parent)
        self.callback_clicked = callback_clicked
        self.ra_offset, self.dec_offset = data

    def mouseReleaseEvent(self, event):
        self.callback_clicked(event, self.ra_offset, self.dec_offset)

    def load_image(self, image_orig):
        height, width = image_orig.shape
        bytes_per_line = width

        #scale_interval = MinMaxInterval()
        scale_interval = ZScaleInterval()

        scale_stretch = LinearStretch()

        image_normalize = ImageNormalize(image_orig, interval=scale_interval, stretch=scale_stretch, clip=True)
        image = img_as_ubyte(image_normalize(image_orig))

        qimage = QImage(image, width, height, bytes_per_line, QImage.Format_Grayscale8)
        qimage = qimage.scaled(320, 240, aspectRatioMode=Qt.KeepAspectRatio, transformMode=Qt.SmoothTransformation)

        self.setPixmap(QPixmap.fromImage(qimage))

    def get_offsets(self):
        return [self.ra_offset, self.dec_offset]

class ScanDialog(QDialog):

    def __init__(self, positions, expose_time, expose_delay_after_exposure, parent=None):
        super().__init__(parent=parent)

        self.expose_time = expose_time
        self.expose_delay_after_exposure = expose_delay_after_exposure
        self.gui = parent

        self.setWindowTitle("Autoguider Scan")

        buttons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel

        self.button_box = QDialogButtonBox(buttons)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.labels = []
        self.grid_layout = QGridLayout()
        row = 0
        idx = 0
        for items in positions:
            col = 0
            for item in items:
                #button = QPushButton("%s %i %i" % (item, row, col))

                self.labels.append(ClickableLabel(item, self.image_clicked))
                image = QImage("/opt/indi_autoguider/share/splash_screen.jpg")
                image = image.scaled(320, 240, aspectRatioMode=Qt.KeepAspectRatio, transformMode=Qt.SmoothTransformation)
                self.labels[idx].setPixmap(QPixmap.fromImage(image))
                self.labels[idx].setToolTip("offsets = %s" % (item))

                self.grid_layout.addWidget(self.labels[idx], row, col)
                col += 1
                idx += 1
            row += 1

        self.actual_label_idx = 0
        self.max_label_idx = idx - 1

        self.layout = QVBoxLayout()
        self.layout.addLayout(self.grid_layout)
        self.layout.addWidget(self.button_box)
        self.setLayout(self.layout)

        self.resize(640, 480)

        self.next_position()

    def next_position(self):
        ra_offset, dec_offset = self.labels[self.actual_label_idx].get_offsets()

        self.gui.log("set guider absolute ra_offset = %.2f, dec_offset = %.2f" % (ra_offset, dec_offset))
        self.gui.run_set_guider_absolute_offsets(ra_offset, dec_offset)

        QTimer.singleShot(self.expose_delay_after_exposure * 1000, self.next_exposure)

    def next_exposure(self):
        self.gui.log("start expose %f" % self.expose_time)
        self.gui.create_guider_command_thread([["start", self.expose_time, 1, 0]])

    def image_clicked(self, event, ra_offset, dec_offset):
        button = event.button()
        modifiers = event.modifiers()

        if modifiers == Qt.NoModifier and button == Qt.LeftButton:
            self.gui.run_set_guider_absolute_offsets(ra_offset, dec_offset)

    def load_image(self, image):
        self.labels[self.actual_label_idx].load_image(image)
        self.actual_label_idx += 1

        if self.actual_label_idx > self.max_label_idx:
            self.actual_label_idx = 0
            return

        self.next_position()

class FiberPointingUI(QMainWindow):

    COLORS = {
        "info": 0x000000,
        "highlight": 0x0000FF,
        "warning": 0xFF9966,
        "error": 0xFF0000,
    }

    def __init__(self):
        super(FiberPointingUI, self).__init__()

        self.init_success = False

        self.status_color = {
            "IDLE": "#CCCCCC",
            "RUNNING": "#CCFFCC",
            "SUCCESS": "#FFFFFF",
            "FAILED": "#FFCCCC",
        }

        self.load_cfg()

        self.image_orig = self.load_fits(FIBER_POINTING_CLIENT_FIT)

        self.ds9_processes = []
        self.run_ds9(self.cfg["pointing_storage"])
        #self.run_ds9(self.cfg["photometric_storage"])

        if self.ds9_processes:
            time.sleep(1)

        self.sounds = {}
        self.sounds["error"] = QSound(os.path.join(FIBER_POINTING_CLIENT_SOUNDS, "error.wav"))
        self.sounds["set"] = QSound(os.path.join(FIBER_POINTING_CLIENT_SOUNDS, "set.wav"))
        self.sounds["new_image"] = QSound(os.path.join(FIBER_POINTING_CLIENT_SOUNDS, "new_image.wav"))

        self.sounds_enabled = {}
        self.sounds_enabled["error"] = True
        self.sounds_enabled["set"] = True
        self.sounds_enabled["new_image"] = True

        self.scan_dialog = None

        uic.loadUi(FIBER_POINTING_CLIENT_UI, self)

        self.logger = logging.getLogger("fiber_pointing_client")
        init_logger(self.logger, FIBER_POINTING_CLIENT_LOG % "gui")
        self.logger.info("Starting process 'fiber_pointing_client'")

        self.exit = threading.Event()
        self.stop_event = threading.Event()

        self.thread_logger = {}
        self.thread_exit = {}
        for key in ["telescope_read", "telescope_command", "guider_read", "guider_command"]:
            self.thread_exit[key] = threading.Event()
            self.thread_exit[key].set()

            self.thread_logger[key] = logging.getLogger(key)
            init_logger(self.thread_logger[key], FIBER_POINTING_CLIENT_LOG % key)

        self.expose_filter_layout = QVBoxLayout()
        self.expose_filter_GB.setLayout(self.expose_filter_layout)

        counter = 0
        self.expose_filter_checkboxes = {}
        for item in self.cfg["photometric_camera"]["filters"]:
            name = "%i %s" % (counter, item)
            self.expose_filter_checkboxes[name] = QCheckBox(name, self)
            counter += 1

        for key in self.expose_filter_checkboxes:
            self.expose_filter_layout.addWidget(self.expose_filter_checkboxes[key])

        # TODO: implementovat
        self.autoguider_min_star_brightness_LB.hide()
        self.autoguider_min_star_brightness_SB.hide()
        self.autoguider_max_star_brightness_LB.hide()
        self.autoguider_max_star_brightness_SB.hide()

        self.target_GI = SightGraphicsItem(100, 100, Qt.red, self.target_x_SB, self.target_y_SB)
        self.target_GI.setFlag(QGraphicsItem.ItemIsMovable, True)

        self.target_x_SB.valueChanged.connect(lambda: self.graphics_item_set(
            self.target_GI, self.target_x_SB.value, self.target_GI.setX))

        self.target_y_SB.valueChanged.connect(lambda: self.graphics_item_set(
            self.target_GI, self.target_y_SB.value, self.target_GI.setY))

        self.target_size_SB.valueChanged.connect(self.target_size_SB_valueChanged)

        self.source_GI = SightGraphicsItem(100, 100, Qt.green, self.source_x_SB, self.source_y_SB)
        self.source_GI.setFlag(QGraphicsItem.ItemIsMovable, True)

        self.source_x_SB.valueChanged.connect(lambda: self.graphics_item_set(
            self.source_GI, self.source_x_SB.value, self.source_GI.setX))

        self.source_y_SB.valueChanged.connect(lambda: self.graphics_item_set(
            self.source_GI, self.source_y_SB.value, self.source_GI.setY))

        self.source_autodetect_CB.toggled.connect(self.source_autodetect_toggled)

        self.inter_image_guiding_CHB.stateChanged.connect(self.inter_image_guiding_CHB_changed)
        self.expose_enable_preflash_CHB.stateChanged.connect(self.expose_enable_preflash_CHB_changed)

        self.actionAutoguider.triggered.connect(self.actionAutoguider_triggered)

        self.actionMain_window.triggered.connect(lambda: self.view_show_window(self.actionMain_window, self.main_dockWidget))
        self.actionExpose_window.triggered.connect(lambda: self.view_show_window(self.actionExpose_window, self.expose_dockWidget))
        self.actionState_window.triggered.connect(lambda: self.view_show_window(self.actionState_window, self.state_dockWidget))
        self.actionLog_window.triggered.connect(lambda: self.view_show_window(self.actionLog_window, self.log_dockWidget))

        self.action_sounds_set.triggered.connect(lambda: self.set_sounds(self.action_sounds_set, "set"))
        self.action_sounds_new_image.triggered.connect(lambda: self.set_sounds(self.action_sounds_new_image, "new_image"))
        self.action_sounds_error.triggered.connect(lambda: self.set_sounds(self.action_sounds_error, "error"))

        self.scan_start_BT.clicked.connect(self.scan_start_clicked)

        self.telescope_up_BT.clicked.connect(lambda: self.telescope_move("up"))
        self.telescope_down_BT.clicked.connect(lambda: self.telescope_move("down"))
        self.telescope_right_BT.clicked.connect(lambda: self.telescope_move("right"))
        self.telescope_left_BT.clicked.connect(lambda: self.telescope_move("left"))

        self.expose_camera_CB.currentIndexChanged.connect(self.expose_camera_changed)
        self.expose_camera_CB.setCurrentIndex(1)
        self.expose_camera_CB.setCurrentIndex(0)

        self.expose_binning_CB.currentIndexChanged.connect(self.expose_binning_changed)

        # editingFinished, valueChanged
        self.expose_ccd_temp_SB.valueChanged.connect(self.expose_ccd_temp_changed)
        self.expose_preflash_DSB.valueChanged.connect(self.expose_preflash_changed)
        self.expose_preflash_num_clear_SB.valueChanged.connect(self.expose_preflash_changed)
        self.gain_SB.valueChanged.connect(self.gain_changed)

        self.autodetect_GI = SightGraphicsItem(100, 100, Qt.blue, rectangle=False)

        self.scale_init()

        #filename = "/home/fuky/stel/fotometrie/2019-10-12/2019-10-12_19-36-44_001.fit"
        #filename = "/home/fuky/stel/fotometrie/2019-09-21/2019-09-21_21-06-50_001.fit"
        #self.image_orig = self.load_fits(filename)

        #zscale_interval = ZScaleInterval()
        #vmin, vmax = zscale_interval.get_limits(image)
        #norm = ImageNormalize(vmin=vmin, vmax=vmax)
        #plt.imshow(image, norm=norm)
        #plt.show()
        #zscale_image = zscale_interval(image)
        #image = img_as_ubyte(zscale_image)

        #if (image.dtype.name != "uint16"):
        #    raise Exception("Unknown image.dtype")

        pixmap = QPixmap(FIBER_POINTING_CLIENT_SPLASH_SCREEN)
        self.graphics_pixmap_item = QGraphicsPixmapItem(pixmap)

        self.scene = FiberPointingScene()
        self.scene.setSceneRect(0, 0, 1920, 1080)
        self.scene.addItem(self.graphics_pixmap_item)
        self.scene.addItem(self.target_GI)
        self.scene.addItem(self.source_GI)
        self.scene.addItem(self.autodetect_GI)

        self.graphicsView.setScene(self.scene)
        self.graphicsView.scale(1, -1)

        self.scale_previous = 1
        self.scale_DSB.valueChanged.connect(self.scale_change)

        self.star_matplotlib_canvas = StarMatplotlibCanvas(self.star_matplotlib_widget, width=5, height=4, dpi=100)
        self.star_matplotlib_layout.addWidget(self.star_matplotlib_canvas)

        self.move_source_to_target_BT.clicked.connect(self.move_source_to_target_clicked)
        self.expose_start_BT.clicked.connect(self.expose_start_clicked)
        self.expose_stop_BT.clicked.connect(self.expose_stop_clicked)

        self.autoguider_on = False
        self.actionAutoguider_triggered(False)

        self.last_fits = ""
        self.last_fits_filename = None
        self.last_fits_imagetype = None
        self.camera_name = "pointing"

        # DEPRECATED
        #self.timer = QTimer()
        #self.timer.timeout.connect(self.loopLoadFits)
        #self.timer.start(100)

        #self.expose_PB.setValue(30.5)
        #self.expose_PB.setFormat("remaining 00:10:00 (elapsed 00:00:10)")
        self.expose_PB.setFormat("ready")

        self.expose_remaining_LB.setText("00:10:00")
        self.expose_elapsed_LB.setText("00:00:40")

        self.proxy = {}

        # TODO: do separatniho procesu
        for item in ["pointing_camera", "photometric_camera"]:
            self.proxy[item] = xmlrpc.client.ServerProxy("http://%(host)s:%(port)s" % self.cfg[item])

        # TODO: do separatniho procesu
        for item in ["pointing_storage", "photometric_storage"]:
            self.proxy[item] = xmlrpc.client.ServerProxy("http://%(host)s:%(port)s" % self.cfg[item])

        self.resize(self.cfg["window"]["width"], self.cfg["window"]["height"])

        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(10)

        self.stop_event.clear()
        #self.thread_exit["telescope_read"].clear()
        self.thread_exit["guider_read"].clear()

        self.progress_callback_dict = {
            "telescope_read": self.progress_telescope_read_fn,
            "telescope_command": self.progress_telescope_command_fn,
            "guider_read": self.progress_guider_read_fn,
            "guider_command": self.progress_guider_command_fn,
        }

        kwargs = {
            "name": "telescope_read",
            "gui": self,
            "command": None,
            "thread_exit": self.thread_exit["telescope_read"],
        }

        self.telescope_read_thread = TelescopeThread(self)
        telescope_worker = Worker(self.telescope_read_thread.run, **kwargs)

        kwargs = {
            "name": "guider_read",
            "gui": self,
            "command": None,
            "thread_exit": self.thread_exit["guider_read"],
        }

        self.guider_read_thread = GuiderThread(self)
        guider_worker = Worker(self.guider_read_thread.run, **kwargs)

        self.threadpool.start(telescope_worker)
        self.threadpool.start(guider_worker)

        self.reaload_pixmap()
        self.init_success = True

        self.graphics_item_set(self.target_GI, self.target_x_SB.value, self.target_GI.setX)
        self.graphics_item_set(self.target_GI, self.target_y_SB.value, self.target_GI.setY)

        self.play("set")
        self.show()

    def __del__(self):
        for process in self.ds9_processes:
            process.terminate()

    def load_cfg(self):
        rcp = configparser.ConfigParser()
        rcp.read(FIBER_POINTING_CLIENT_CFG)

        servers = [
            "pointing_camera",
            "pointing_storage",
            "photometric_camera",
            "photometric_storage",
        ]

        self.cfg = {
            "window": {},
        }

        for server in servers:
            self.cfg[server] = {}

            callbacks = {
                "host": rcp.get,
                "port": rcp.getint,
            }

            if server.endswith("_camera"):
                callbacks["read_modes"] = rcp.get
                callbacks["field_rotation_angle"] = rcp.getfloat
                callbacks["field_parity"] = rcp.getint
                callbacks["pix2arcsec"] = rcp.getfloat

            if server == "photometric_camera":
                callbacks["filters"] = rcp.get

            if server.endswith("_storage"):
                callbacks["data_dir"] = rcp.get
                callbacks["save"] = rcp.getboolean
                callbacks["ds9_dir"] = rcp.get
                callbacks["ds9_bin"] = rcp.get
                callbacks["ds9_title"] = rcp.get
                callbacks["xpaset_bin"] = rcp.get

            self.run_cfg_callbacks(server, callbacks)

            if server.endswith("_camera"):
                self.cfg[server]["read_modes"] = self.cfg[server]["read_modes"].split(",")

            if server == "photometric_camera":
                self.cfg[server]["filters"] = self.cfg[server]["filters"].split(",")

        window_callbacks = {
            "width": rcp.getint,
            "height": rcp.getint,
        }
        self.run_cfg_callbacks("window", window_callbacks)

        print(self.cfg)

    def run_cfg_callbacks(self, section, callbacks):
        for key in callbacks:
            self.cfg[section][key] = callbacks[key](section, key)

    def fce_ds9_process(self, ds9_bin, title):
        cmd = [ds9_bin, "-title", title]

        subprocess.call(cmd)

    def run_ds9(self, storage_cfg):
        try:
            if storage_cfg["ds9_bin"]:
                process = multiprocessing.Process(target=self.fce_ds9_process, args=(storage_cfg["ds9_bin"], storage_cfg["ds9_title"]))
                process.start()

                self.ds9_processes.append(process)
        except:
            traceback.print_exc()

    def scale_init(self):
        self.scale_interval = MinMaxInterval()
        self.scale_stretch = LinearStretch()

        self.scale_interval_from_text = {
            "zscale": ZScaleInterval(),
            "min max": MinMaxInterval(),
        }

        self.scale_stretch_from_text = {
            "linear": LinearStretch(),
            "log": LogStretch(),
            #"power": PowerStretch(),
            "sqrt": SqrtStretch(),
            "squared": SquaredStretch(),
            "asinh": AsinhStretch(),
            "sinh": SinhStretch(),
            #"histogram": HistEqStretch(),
        }

        self.scale_interval_CB.currentIndexChanged.connect(self.scale_interval_set)
        self.scale_stretch_CB.currentIndexChanged.connect(self.scale_stretch_set)

    # /usr/bin/ds9 -title mi
    def ds9_xpaset(self, filename, storage_cfg):

        if storage_cfg["ds9_dir"]:
            filename = os.path.basename(filename)
            filename = os.path.join(storage_cfg["ds9_dir"], filename)

        cmd = [storage_cfg["xpaset_bin"], "-p", storage_cfg["ds9_title"], "file", filename]
        print(cmd)

        try:
            output = subprocess.check_output(cmd)
            print(output)
        except:
            traceback.print_exc()

    # TODO: refaktorizovat, pipnout pri hodnotach mimo rozsah
    def refresh_state(self, camera_name, status):
        status_str = self.status2human(status["status"])

        if camera_name == "photometric":
            self.g2_chip_temp_LB.setText("%.1f °C" % status["chip_temperature"])
            self.g2_supply_voltage_LB.setText("%.1f V" % status["supply_voltage"])
            self.g2_power_utilization_LB.setText("%.1f %%" % (status["power_utilization"] * 100))
            self.g2_state_LB.setText(status_str)
            self.g2_filter_LB.setText(self.filter2human(status["filter"]))
            # TODO: ostatni hodnoty ukladat pouze do logu (ne prilis casto)

            diff = self.expose_ccd_temp_SB.value() - status["chip_temperature"]
            if abs(diff) < 0.5:
                self.g2_chip_temp_LB.setStyleSheet("background-color: #CCFFCC;")
            else:
                self.g2_chip_temp_LB.setStyleSheet("background-color: #FFCCCC;")

            if status["power_utilization"] < 0.9:
                self.g2_power_utilization_LB.setStyleSheet("background-color: #CCFFCC;")
            else:
                self.g2_power_utilization_LB.setStyleSheet("background-color: #FFCCCC;")

            if 11.5 < status["supply_voltage"] < 15.5:
                self.g2_supply_voltage_LB.setStyleSheet("background-color: #CCFFCC;")
            else:
                self.g2_supply_voltage_LB.setStyleSheet("background-color: #FFCCCC;")

            if status["status"] >= 128:
                self.g2_state_LB.setStyleSheet("background-color: #FFCCCC;")
            else:
                self.g2_state_LB.setStyleSheet("background-color: #CCFFCC;")

            if status["filter"] < 0:
                self.g2_filter_LB.setStyleSheet("background-color: #FFCCCC;")
            else:
                self.g2_filter_LB.setStyleSheet("background-color: #CCFFCC;")

    def filter2human(self, value):
        filter_str = "unknown"

        if value == -2:
            filter_str = "moving"
        elif value >= 0:
            filter_str = "%i" % value

        return filter_str

    def status2human(self, status):
        status_str = "unknown"
        for key in FIBER_GXCCD_STATUS:
            if (FIBER_GXCCD_STATUS[key] == status):
                status_str = key

        return status_str

    # TODO
    def loopLoadFits(self):
        return

        storage_cfg = self.cfg["%s_storage" % self.camera_name]

        #cameras_status = {}
        #for camera in ["photometric", "pointing"]:
        #    cameras_status[camera] = self.proxy["%s_camera" % camera].get_status()

        #exposure_time = cameras_status[self.camera_name]["exposure_time"]
        #elapsed_time = cameras_status[self.camera_name]["exposure_elapsed_time"]
        #remaining_time = exposure_time - elapsed_time
        #percent = elapsed_time / (exposure_time / 100.0)

        #status = self.status2human(cameras_status[self.camera_name]["status"])

        #self.expose_PB.setFormat("%s (%i/%i)" % (status, cameras_status[self.camera_name]["exposure_number"], self.expose_count_repeat_SB.value()))

        exposure_time = 0
        elapsed_time = 0
        remaining_time = 0
        percent = 0
        status = "OK"

        if (status == "ready"):
            self.expose_remaining_LB.setText("0:00:00")
            self.expose_elapsed_LB.setText("0:00:00")
            self.expose_PB.setValue(0)
        else:
            self.expose_remaining_LB.setText(str(timedelta(seconds=round(remaining_time))))
            self.expose_elapsed_LB.setText(str(timedelta(seconds=round(elapsed_time))))
            self.expose_PB.setValue(percent)

        #self.refresh_state("photometric", cameras_status["photometric"])
        #self.refresh_state("pointing", cameras_status["pointing"])

        # DBG begin
        if not self.last_fits:
            #self.last_fits = "/home/fuky/_tmp/e152/fitswkUgDe.fits"
            #self.last_fits = "/home/fuky/_tmp/e152/fitsxOUbXm.fits"
            self.last_fits = "/home/fuky/_tmp/e152/fitsEsPvab.fits"
            #self.last_fits = "/home/fuky/_tmp/e152/fitsSuShql.fits"
            #self.last_fits = "/home/fuky/_tmp/e152/"
            self.image_orig = self.load_fits(self.last_fits)
            self.reaload_pixmap()
            self.graphics_item_set(self.target_GI)
        return
        # DBG end

        last_fits_filename = self.proxy["%s_storage" % self.camera_name].fiber_pointing_get_last_fits_filename()
        if (not last_fits_filename) or (self.last_fits_filename == last_fits_filename):
            return

        image_format = self.image_format_CB.currentText()

        if image_format.startswith("JPG"):
            quality = 95 # high
            if image_format.find("medium") != -1:
                quality = 70
            elif image_format.find("low") != -1:
                quality = 50

            jpg_binary = self.proxy["%s_storage" % self.camera_name].fiber_pointing_get_jpg(quality, "")

            if jpg_binary:
                self.last_fits_filename = last_fits_filename
                jpg_array = np.frombuffer(jpg_binary.data, np.uint8)
                self.image_orig = cv2.imdecode(jpg_array, cv2.IMREAD_GRAYSCALE)
                self.reaload_pixmap()
                self.graphics_item_set(self.target_GI)
                self.play("new_image")

                if storage_cfg["save"]:
                    filename = os.path.join(storage_cfg["data_dir"], last_fits_filename.replace(".fit", ".jpg"))
                    print(filename)
                    fo = open(filename, "wb")
                    fo.write(jpg_binary.data)
                    fo.close()

                self.image_size_LB.setText(humanize.naturalsize(jpg_array.nbytes))
        else:
            fits_binary = self.proxy["%s_storage" % self.camera_name].fiber_pointing_get_fits()

            if fits_binary:
                fits_fo = io.BytesIO(fits_binary.data)
                hdulist = fits.open(fits_fo)
                prihdr = hdulist[0].header
                self.last_fits_filename = prihdr["FILENAME"]
                self.last_fits_imagetype = prihdr["IMAGETYP"]
                filename = os.path.join(storage_cfg["data_dir"], prihdr["FILENAME"])

                self.image_orig = img_as_ubyte(hdulist[0].data)
                self.reaload_pixmap()
                self.graphics_item_set(self.target_GI)
                self.play("new_image")

                if storage_cfg["save"]:
                    print(filename)
                    fo = open(filename, "wb")
                    fo.write(fits_binary.data)
                    fo.close()

                if storage_cfg["ds9_bin"]:
                    self.ds9_xpaset(filename, storage_cfg)

                self.image_size_LB.setText("")

        # DBK
        return

        fits_dir = "/tmp/test"

        filenames = os.listdir(fits_dir)
        if (not filenames):
            return

        filenames.sort()
        last_fits = os.path.join(fits_dir, filenames[-1])

        if (last_fits != self.last_fits):
            self.last_fits = last_fits
            print("load %s" % last_fits)
            self.image_orig = self.load_fits(last_fits)
            self.reaload_pixmap()

            # TODO: vyresit poradne
            self.graphics_item_set(self.target_GI)

    def play(self, name):
        if self.sounds_enabled[name]:
            self.sounds[name].play()

    def set_sounds(self, action, name):
        if action.isChecked():
            self.sounds_enabled[name] = True
        else:
            self.sounds_enabled[name] = False

    # TODO: dodelat
    def view_show_window(self, action, dock_widget):
        if action.isChecked():
            dock_widget.show()
        else:
            dock_widget.hide()

    # TODO: dodelat
    def actionAutoguider_triggered(self, checked):
        widget = self.toolBar.widgetForAction(self.actionAutoguider)

        if checked:
            self.actionAutoguider.setIconText("Autoguider ON")
            widget.setStyleSheet("background-color: #CCFFCC;")

            # DBG
            self.last_fits = ""
            self.autoguider_on = True
        else:
            self.actionAutoguider.setIconText("Autoguider OFF")
            widget.setStyleSheet("background-color: #FFCCCC;")
            self.autoguider_on = False

    def scale_interval_set(self, idx):
        self.scale_interval = self.scale_interval_from_text[self.scale_interval_CB.itemText(idx)]
        self.reaload_pixmap()

    def scale_stretch_set(self, idx):
        self.scale_stretch = self.scale_stretch_from_text[self.scale_stretch_CB.itemText(idx)]
        self.reaload_pixmap()

    # TODO: zkontrolovat zda-li se target a source vejde do nove nacteneho FITS
    def reaload_pixmap(self):
        height, width = self.image_orig.shape
        bytes_per_line = width

        self.scene.setSceneRect(0, 0, width - self.target_GI.width, height - self.target_GI.height)

        image_normalize = ImageNormalize(self.image_orig, interval=self.scale_interval, stretch=self.scale_stretch, clip=True)
        image = img_as_ubyte(image_normalize(self.image_orig))

        # QImage.Format_Grayscale16 - The image is stored using an 16-bit grayscale format. (added in Qt 5.13)
        qimage = QImage(image, width, height, bytes_per_line, QImage.Format_Grayscale8)
        pixmap = QPixmap(qimage)

        self.graphics_pixmap_item.setPixmap(pixmap)

    def inter_image_guiding_CHB_changed(self, idx):
        value = self.inter_image_guiding_CHB.isChecked()

        self.expose_exptime_pointing_LB.setEnabled(value)
        self.expose_exptime_pointing_DSB.setEnabled(value)

    def expose_enable_preflash_CHB_changed(self, idx):
        value = self.expose_enable_preflash_CHB.isChecked()

        if value:
            self.expose_preflash_DSB.setValue(1)
        else:
            self.expose_preflash_DSB.setValue(0)

        self.expose_preflash_LB.setEnabled(value)
        self.expose_preflash_DSB.setEnabled(value)
        self.expose_preflash_num_clear_LB.setEnabled(value)
        self.expose_preflash_num_clear_SB.setEnabled(value)

    def expose_camera_changed(self, idx):
        self.target_x_SB.setValue(537)
        self.target_y_SB.setValue(380)
        self.source_x_SB.setValue(0)
        self.source_y_SB.setValue(0)

        if idx == 0:
            # G1
            self.camera_name = "pointing"
            self.set_expose_camera_pointing()
        else:
            # G2
            self.camera_name = "photometric"
            self.set_expose_camera_photometry()

    def gain_changed(self):
        self.create_guider_command_thread([["gain", self.gain_SB.value()]])

    def expose_ccd_temp_changed(self):
        result = self.proxy["%s_camera" % self.camera_name].set_temperature(self.expose_ccd_temp_SB.value())

        self.log("temp = %i => %s" % (self.expose_ccd_temp_SB.value(), result), "highlight")

        self.play("set")

    def expose_binning_changed(self, idx):
        binning = [1, 2, 4]
        value = binning[idx]

        result = self.proxy["%s_camera" % self.camera_name].set_binning(value, value)

        self.log("binning = %i => %s" % (value, result))

    # TODO: osetrit caste volani za sebou
    def expose_preflash_changed(self):
        preflash_time = self.expose_preflash_DSB.value()
        clear_num = self.expose_preflash_num_clear_SB.value()

        result = self.proxy["%s_camera" % self.camera_name].set_preflash(preflash_time, clear_num)

        self.log("set_preflash(%f, %i) => %s" % (preflash_time, clear_num, result))

    def set_hide_photometry_widgets(self, hide):
        widgets = [
            self.expose_exptime_scientific_LB,
            self.expose_exptime_scientific_DSB,
            self.expose_ccd_temp_LB,
            self.expose_ccd_temp_SB,
            self.expose_filter_GB,
            self.inter_image_guiding_CHB,
            self.expose_binning_CB,
            self.expose_binning_LB,
            self.expose_preflash_num_clear_LB,
            self.expose_preflash_num_clear_SB,
            self.expose_preflash_LB,
            self.expose_preflash_DSB,
            self.expose_enable_preflash_CHB,
        ]

        for key in self.expose_filter_checkboxes:
            widgets.append(self.expose_filter_checkboxes[key])

        fce = methodcaller("show")
        if hide:
            fce = methodcaller("hide")

        for widget in widgets:
            fce(widget)

    def set_expose_camera_pointing(self):
        # G1 - jine zrcatko
        # Field size: 7.09528 x 5.33268 arcminutes
        # Field rotation angle: up is -135.643 degrees E of N
        # Field parity: pos
        # pixel scale 0.649074 arcsec/pix

        # 2019-12-18
        # Field: 2019-12-18_19-00-57_001.fit
        # Field size: 6.98142 x 5.27808 arcminutes
        # Field rotation angle: up is -135.758 degrees E of N
        # Field parity: pos
        # pixel scale 0.639643 arcsec/pix.

        #self.field_rotation_angle = 45.903
        #self.field_parity = 1
        #self.pix2arcsec = 0.605898

        # field_rotation_angle = 180 + frd
        self.field_rotation_angle = self.cfg["pointing_camera"]["field_rotation_angle"]
        self.field_parity = self.cfg["pointing_camera"]["field_parity"]
        self.pix2arcsec = self.cfg["pointing_camera"]["pix2arcsec"]

        self.field_rotation_angle_DSB.setValue(self.field_rotation_angle)
        self.field_parity_CB.setCurrentIndex(0)
        self.pixels2arcsec_DSB.setValue(self.pix2arcsec)

        if self.field_parity == 1:
            self.field_parity_CB.setCurrentIndex(1)

        self.set_hide_photometry_widgets(True)

        self.read_mode_CB.clear()
        for item in self.cfg["pointing_camera"]["read_modes"]:
            self.read_mode_CB.addItem(item)

    def set_expose_camera_photometry(self):
        # G2 - neni pro binning 1x1
        # Field size: 7.34287 x 4.93668 arcminutes
        # Field rotation angle: up is -45.903 degrees E of N
        # Field parity: neg
        # pixel scale 0.605898 arcsec/pix

        # 2019-09-21
        # Field: 2019-09-21_18-38-00_001.fit
        # Field size: 7.33896 x 4.94626 arcminutes
        # Field rotation angle: up is -45.7991 degrees E of N
        # Field parity: neg
        # pixel scale 0.201665 arcsec/pix.

        # 2020-01-06
        # Field: f202001060162.fit
        # Field size: 7.34397 x 4.96184 arcminutes
        # Field rotation angle: up is -46.0547 degrees E of N
        # Field parity: neg
        # pixel scale 0.202102 arcsec/pix.

        #self.field_rotation_angle = -135.643
        #self.field_parity = -1
        #self.pix2arcsec = 0.18

        # field_rotation_angle = -90 + frd
        self.field_rotation_angle = self.cfg["photometric_camera"]["field_rotation_angle"]
        self.field_parity = self.cfg["photometric_camera"]["field_parity"]
        self.pix2arcsec = self.cfg["photometric_camera"]["pix2arcsec"]

        self.field_rotation_angle_DSB.setValue(self.field_rotation_angle)
        self.field_parity_CB.setCurrentIndex(1)
        self.pixels2arcsec_DSB.setValue(self.pix2arcsec)

        self.set_hide_photometry_widgets(False)

        self.read_mode_CB.clear()
        for item in self.cfg["photometric_camera"]["read_modes"]:
            self.read_mode_CB.addItem(item)

    def source_autodetect_toggled(self):

        if self.source_autodetect_CB.isChecked():
            self.source_x_SB.setEnabled(False)
            self.source_y_SB.setEnabled(False)
        else:
            self.source_x_SB.setEnabled(True)
            self.source_y_SB.setEnabled(True)

    def scan_start_clicked(self):
        max_offset = self.scan_max_offset_DSB.value()
        count_repeat = self.scan_count_repeat_SB.value()
        step = (max_offset * 2.0) / (count_repeat - 1)

        positions = [[]]
        row = 0
        for ra in np.arange(-max_offset, max_offset+0.01, step):
            col = 0
            for dec in np.arange(-max_offset, max_offset+0.01, step):
                positions[row].append([ra, dec])
                col += 1
            positions.append([])
            row += 1

        expose_time = self.expose_exptime_pointing_DSB.value()
        expose_delay_after_exposure = self.expose_delay_after_exposure_SB.value()

        self.scan_dialog = ScanDialog(positions, expose_time, expose_delay_after_exposure, parent=self)
        self.scan_dialog.exec_()
        self.scan_dialog = None

    def expose_start_clicked(self):
        print("expose_start_clicked")

        # G1 - exptime_min = 0.000125

        # G2 - exptime_min = 0.1

        count_repeat = self.expose_count_repeat_SB.value()

        if self.camera_name == "photometric":
            expose_time = self.expose_exptime_scientific_DSB.value()
            expose_time_pointing = -1
            read_mode = self.read_mode_CB.currentIndex()
            filters = []

            for key in self.expose_filter_checkboxes:
                if self.expose_filter_checkboxes[key].isChecked():
                    filters.append(int(key.split(" ")[0]))

            if self.inter_image_guiding_CHB.isChecked():
                expose_time_pointing = self.expose_exptime_pointing_DSB.value()
        else:
            expose_time = -1
            expose_time_pointing = self.expose_exptime_pointing_DSB.value()
            delay_after_exposure = self.expose_delay_after_exposure_SB.value()
            read_mode = 0
            filters = []

        self.create_guider_command_thread([["start", expose_time_pointing, count_repeat, delay_after_exposure]])

        #self.proxy["%s_camera" % self.camera_name].start_exposure(expose_time, expose_time_pointing,
        #    count_repeat, self.expose_delay_after_exposure_SB.value(),
        #    self.expose_object_CB.currentText(), self.expose_target_LE.text(), self.expose_observers_LE.text(),
        #    read_mode, filters)

    def expose_stop_clicked(self):
        print("expose_stop_clicked")

        self.stop_event.set()

        #self.proxy["%s_camera" % self.camera_name].stop_exposure()

    def move_source_to_target_clicked(self):
        print("GO to target")

        source_pos = self.source_GI.scenePos()
        target_pos = self.target_GI.scenePos()

        x = target_pos.x() - source_pos.x()
        y = target_pos.y() - source_pos.y()

        self.telescope_offset(x, y)

    def telescope_move(self, action):
        step = self.telescope_move_DSB.value()
        x = 0.0
        y = 0.0

        if action == "up":
            y = step
        elif action == "down":
            y = -step
        elif action == "left":
            x = -step
        elif action == "right":
            x = step

        xt, yt = self.field_rotation(x, y)

        self.log("telescope %s %.1f %.1f" % (action, xt, yt), "highlight")

        self.run_tsgc(xt, yt)

    def field_rotation(self, x, y):
        self.field_rotation_angle = self.field_rotation_angle_DSB.value()

        if self.field_parity_CB.currentIndex() == 0:
            self.field_parity = 1
        else:
            self.field_parity = -1

        angle_rad = math.radians(self.field_rotation_angle)

        xt = x * math.cos(angle_rad) - y * math.sin(angle_rad)
        yt = x * math.sin(angle_rad) + y * math.cos(angle_rad)

        xt *= self.field_parity

        return [xt, yt]

    def run_tsgc(self, x, y):
        kwargs = {
            "name": "telescope_command",
            "gui": self,
            "command": [["set_guider_relative_offsets", x, y]],
            "thread_exit": self.thread_exit["telescope_command"],
        }

        self.telescope_command_thread = TelescopeThread(self)
        telescope_worker = Worker(self.telescope_command_thread.run, **kwargs)

        self.threadpool.start(telescope_worker)

    def run_set_guider_absolute_offsets(self, x, y):
        kwargs = {
            "name": "telescope_command",
            "gui": self,
            "command": [["set_guider_absolute_offsets", x, y]],
            "thread_exit": self.thread_exit["telescope_command"],
        }

        self.telescope_command_thread = TelescopeThread(self)
        telescope_worker = Worker(self.telescope_command_thread.run, **kwargs)

        self.threadpool.start(telescope_worker)

    def telescope_offset(self, x, y, autoguider=False, fwhm=None):
        print("telescope_offset", x, y)

        self.pix2arcsec = self.pixels2arcsec_DSB.value()

        xt, yt = self.field_rotation(x, y)

        print("offset %i %i px" % (x, y))
        print("offset rotated %.1f %.1f px" % (xt, yt))

        xt *= self.pix2arcsec
        yt *= self.pix2arcsec

        print('offset rotated %.1f %.1f "' % (xt, yt))

        if not autoguider or self.is_telescope_move_acceptable(xt, yt, fwhm):
            self.run_tsgc(xt, yt)

    def is_telescope_move_acceptable(self, x_offset, y_offset, fwhm):
        dt_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        message = '%s - telescope move %.1f" %.1f"' % (dt_str, x_offset, y_offset)
        result = True
        message_color = "CCFFCC"

        max_star_movement = self.autoguider_max_star_movement_SB.value()
        min_star_fwhm = self.autoguider_min_star_fwhm_SB.value()
        max_star_fwhm = self.autoguider_max_star_fwhm_SB.value()

        if abs(x_offset) > max_star_movement:
            message = '%s is not acceptable because x_offset abs(%.1f") > %i"' % (message, x_offset, max_star_movement)
            result = False
        elif abs(y_offset) > max_star_movement:
            message = '%s is not acceptable because y_offset abs(%.1f") > %i"' % (message, y_offset, max_star_movement)
            result= False
        else:
            for value in fwhm:
                if abs(value) > max_star_fwhm:
                    message = '%s is not acceptable because FWHM abs(%.1f pix) > %i pix' % (message, value, max_star_fwhm)
                    result = False
                    break
                elif abs(value) < min_star_fwhm:
                    message = '%s is not acceptable because FWHM abs(%.1f pix) < %i pix' % (message, value, min_star_fwhm)
                    result = False
                    break

        self.statusbar.showMessage(message)

        if not result:
            message_color = "FFCCCC"

        self.statusbar.setStyleSheet("background-color: #%s;" % message_color)

        return result

    def scale_change(self):
        scale = self.scale_DSB.value() * (1.0 / self.scale_previous)

        print("scale_previous = %.2f, scale = %.2f" % (self.scale_previous, scale))

        self.scale_previous = self.scale_DSB.value()

        #self.graphicsView.fitInView()

        self.graphicsView.scale(scale, scale)

    def target_size_SB_valueChanged(self):
        size = self.target_size_SB.value()

        self.target_GI.set_width_height(size, size)
        #self.source_GI.set_width_height(size, size)
        self.autodetect_GI.set_width_height(size, size)

    def graphics_item_set(self, graphics_item, fce_value=None, fce_set=None):
        if not self.init_success:
            return

        is_star_detected = False
        position = graphics_item.scenePos()
        height, width = self.image_orig.shape

        # TODO: je treba predat spravne souradnice
        size = int(graphics_item.width / 2)
        x = int(position.x()) + size
        y = int(position.y()) + size

        print(x, y, size)

        try:
            subimage = self.image_orig[y-size:y+size+1, x-size:x+size+1]
            print(subimage)
            x2dg, y2dg = centroid_2dg(subimage)
            print("centroid_2dg = [%.1f; %.1f]" % (x2dg, y2dg))
            #x2dg, y2dg = centroid_com(subimage)
            #print("centroid_com = [%.1f; %.1f]" % (x2dg, y2dg))

            gfit = fit_2dgaussian(subimage)
            print(gfit)
            x_fwhm = gfit.x_stddev * gaussian_sigma_to_fwhm
            y_fwhm = gfit.y_stddev * gaussian_sigma_to_fwhm
            print("FWHM", x_fwhm, y_fwhm)

            x_fwhm_arcsec = x_fwhm * self.pixels2arcsec_DSB.value()
            y_fwhm_arcsec = y_fwhm * self.pixels2arcsec_DSB.value()

            self.fwhm_x_LB.setText('%.1f pix, %.1f"' % (x_fwhm, x_fwhm_arcsec))
            self.fwhm_y_LB.setText('%.1f pix, %.1f"' % (y_fwhm, y_fwhm_arcsec))
            self.gaussian_amplitude_LB.setText("%.1f" % gfit.amplitude.value)

            if not np.isnan(x2dg) and not np.isnan(y2dg):
                is_star_detected = True
                self.star_matplotlib_canvas.plot_star(subimage, x2dg, y2dg)

                star_x = position.x() + (int(x2dg) - size)
                star_y = position.y() + (int(y2dg) - size)

                if graphics_item is self.target_GI:
                    self.autodetect_GI.setX(star_x)
                    self.autodetect_GI.setY(star_y)

                    print(self.last_fits_imagetype)
                    if (self.autoguider_on and \
                        ((self.camera_name == "pointing") or (self.last_fits_imagetype == "autoguider"))):
                        target_pos = self.target_GI.scenePos()

                        x = target_pos.x() - star_x
                        y = target_pos.y() - star_y

                        fwhm = [x_fwhm, y_fwhm]
                        self.telescope_offset(x, y, autoguider=True, fwhm=fwhm)

                elif graphics_item is self.source_GI and self.source_autodetect_CB.isChecked():
                    graphics_item.setX(star_x)
                    graphics_item.setY(star_y)
        except:
            traceback.print_exc()
            QMessageBox.warning(self, "ERROR", traceback.format_exc())

        if (graphics_item.isUnderMouse()):
            print("isUnderMouse")
            return

        if (fce_value is None) or (fce_set is None):
            print("fce_value or fce_set is None")
            return

        value = fce_value()
        print("graphics_item_set", value, position.x(), position.y())
        fce_set(value)

    def load_fits(self, filename):
        hdulist = fits.open(filename)

        image = hdulist[0].data
        image = img_as_ubyte(image)

        #image = rotate(image, 180)

        #self.height, self.width = self.image.shape

        return image

    def log(self, message, level="info"):
        dt_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        brush = QBrush(QColor.fromRgb(self.COLORS[level]))

        char_format = self.log_PTE.currentCharFormat()
        char_format.setForeground(brush)

        self.log_PTE.setCurrentCharFormat(char_format)

        self.log_PTE.appendPlainText("%s - %s" % (dt_str, message))

        if level == "error":
            self.logger.error(message)
        elif level == "warning":
            self.logger.warning(message)
        else:
            self.logger.info(message)

    def refresh_statusbar(self, value, msg=""):
        dt_str = datetime.now().strftime("%H:%M:%S")
        name = value.name
        self.status = value

        self.statusbar.showMessage("Status: %s %s %s" % (name, dt_str, msg))
        self.statusbar.setStyleSheet("background-color: %s;" % self.status_color[name])

    def set_label_text(self, label, text, color="#CCFFCC", tooltip=""):
        if text in ["unknown", "OFF", "UNCALIBRATED", "LOCKED", "CLOSE", "OPEN LEFT", "OPEN RIGHT", "TIMEOUT", "MOVING"]:
            color = "#FFCCCC"
        elif text in ["expose"]:
            color = "#FFFF33"
        elif text in ["readout"]:
            color = "#CCCCFF"

        label.setText(text)
        label.setStyleSheet("background-color: %s;" % color)
        label.setToolTip(tooltip)

    def progress_telescope_read_fn(self, data):
        self.guider_offset_ra_LB.setText("%.2f" % data["guider_offset_ra"])
        self.guider_offset_dec_LB.setText("%.2f" % data["guider_offset_dec"])

    def progress_telescope_command_fn(self, data):
        self.log("telescope_command(%s)" % data["command"])

    # https://davidamos.dev/the-right-way-to-compare-floats-in-python/
    def progress_guider_read_fn(self, data):
        status = "expose"

        if math.isclose(data["ccd_exposure"], 0.0):
            status = "ready"

        self.set_label_text(self.g1_state_LB, status)

        remaining_time = data["ccd_exposure"]
        exposure_time = self.expose_exptime_pointing_DSB.value()
        elapsed_time = exposure_time - remaining_time
        percent = elapsed_time / (exposure_time / 100.0)

        # TODO
        #self.expose_PB.setFormat("%s (%i/%i)" % (status, cameras_status[self.camera_name]["exposure_number"], self.expose_count_repeat_SB.value()))
        self.expose_PB.setFormat(status)

        if (status == "ready"):
            self.expose_remaining_LB.setText("0:00:00")
            self.expose_elapsed_LB.setText("0:00:00")
            self.expose_PB.setValue(0)
        else:
            self.expose_remaining_LB.setText(str(timedelta(seconds=round(remaining_time))))
            self.expose_elapsed_LB.setText(str(timedelta(seconds=round(elapsed_time))))
            self.expose_PB.setValue(percent)

        storage_cfg = self.cfg["%s_storage" % self.camera_name]

        # DBG begin
        if not self.last_fits:
            pass
            #self.last_fits = "/home/fuky/_tmp/e152/fitswkUgDe.fits"
            #self.last_fits = "/home/fuky/_tmp/e152/fitsxOUbXm.fits"
            #self.last_fits = "/home/fuky/_tmp/e152/fitsEsPvab.fits"
            #self.last_fits = "/home/fuky/_tmp/e152/fitsSuShql.fits"
            #self.last_fits = "/home/fuky/_tmp/e152/"
            #self.image_orig = self.load_fits(self.last_fits)
            #self.reaload_pixmap()
            #self.graphics_item_set(self.target_GI)

        if data["fits"] is None:
            print("no data")
            return

        image_format = self.image_format_CB.currentText()

        if image_format.startswith("JPG"):
            pass
            #quality = 95 # high
            #if image_format.find("medium") != -1:
            #    quality = 70
            #elif image_format.find("low") != -1:
            #    quality = 50

            #jpg_binary = self.proxy["%s_storage" % self.camera_name].fiber_pointing_get_jpg(quality, "")

            #if jpg_binary:
            #    self.last_fits_filename = last_fits_filename
            #    jpg_array = np.frombuffer(jpg_binary.data, np.uint8)
            #    self.image_orig = cv2.imdecode(jpg_array, cv2.IMREAD_GRAYSCALE)
            #    self.reaload_pixmap()
            #    self.graphics_item_set(self.target_GI)
            #    self.play("new_image")

            #    if storage_cfg["save"]:
            #        filename = os.path.join(storage_cfg["data_dir"], last_fits_filename.replace(".fit", ".jpg"))
            #        print(filename)
            #        fo = open(filename, "wb")
            #        fo.write(jpg_binary.data)
            #        fo.close()

            #    self.image_size_LB.setText(humanize.naturalsize(jpg_array.nbytes))
        else:
            fits_fo = io.BytesIO(data["fits"])
            hdulist = fits.open(fits_fo)
            prihdr = hdulist[0].header
            # 2022-10-16T05:33:02.484
            date_obs = prihdr["DATE-OBS"].replace(":", "_").replace(".", "_")
            print(date_obs)
            self.last_fits_filename = date_obs
            filename = os.path.join(storage_cfg["data_dir"], "%s.fit" % date_obs)

            self.image_orig = img_as_ubyte(hdulist[0].data)
            self.reaload_pixmap()
            self.graphics_item_set(self.target_GI)
            self.play("new_image")

            if self.scan_dialog is not None:
                self.scan_dialog.load_image(self.image_orig)

            if storage_cfg["save"]:
                print(filename)
                fo = open(filename, "wb")
                fo.write(data["fits"])
                fo.close()

            if storage_cfg["ds9_bin"]:
                self.ds9_xpaset(filename, storage_cfg)

            self.image_size_LB.setText("")

    def progress_guider_command_fn(self, data):
        if data["command"] == "gain":
            msg = "Set gain from %(old_gain)i to %(new_gain)i" % data
            self.log(msg)

    def thread_progress(self, category, data):
        if self.exit.is_set():
            return

        if category == "msg":
            self.refresh_statusbar(ClientStatus.RUNNING, data["msg"])
        elif category in self.progress_callback_dict:
            self.logger.debug("thread_progress(category = %s, data = %s)" % (category, data))
            self.progress_callback_dict[category](data)
            #self.refresh_statusbar(ClientStatus.RUNNING, category)
            self.refresh_statusbar(ClientStatus.RUNNING)

    def thread_result(self, name, s):
        if self.exit.is_set():
            return

        self.logger.info("%s = %s" % (name, s))

    def thread_error(self, name, error):
        if self.exit.is_set():
            return

        dt_str = datetime.now().strftime("%H:%M:%S")
        exctype, value, format_exc = error

        self.refresh_statusbar(ClientStatus.FAILED, "%s %s" % (exctype, value))

        self.logger.error("exctype = %s" % exctype)
        self.logger.error("value = %s" % value)
        self.logger.error("format_exc = %s" % format_exc)

        self.log_PTE.textCursor().insertHtml("<b>%s: </b>" % dt_str)
        self.log_PTE.textCursor().insertHtml('<font color="#FF0000">%s</font><br>' % value)

    def thread_finished(self, name):
        if self.exit.is_set():
            self.logger.info("%s COMPLETE! Exiting..." % name)
            return

        if self.status != ClientStatus.FAILED:
            self.refresh_statusbar(ClientStatus.SUCCESS)

        self.logger.info("%s COMPLETE!" % name)

    def is_stop(self):

        if self.exit.is_set() or self.stop_event.is_set():
            return True

        return False

    def closeEvent(self, event):
        self.logger.info("closeEvent(event = %s)" % event)
        self.exit.set()

        all_thread_exit = False

        while not all_thread_exit:
            all_thread_exit = True

            for key in self.thread_exit:
                if self.thread_exit[key].is_set():
                    self.logger.info("Thread '%s' is exited." % key)
                else:
                    all_thread_exit = False

            if not all_thread_exit:
                self.logger.info("Waiting...")
                time.sleep(1)

        self.logger.info("GUI exiting...")

    def create_guider_command_thread(self, command):
        if not self.thread_exit["guider_command"].is_set():
            self.log("Action already run", level="warning")
            return

        self.refresh_statusbar(ClientStatus.RUNNING)

        self.exit.clear()
        self.stop_event.clear()
        self.thread_exit["guider_command"].clear()

        kwargs = {
            "name": "guider_command",
            "gui": self,
            "command": command,
            "thread_exit": self.thread_exit["guider_command"],
        }

        self.log("guider_command = %s" % command)
        self.logger.info("create_ccd_command_thread(%s)" % command)

        self.guider_command_thread = GuiderThread(self)
        guider_worker = Worker(self.guider_command_thread.run, **kwargs)

        self.threadpool.start(guider_worker)

def main():
    app = QApplication([])
    fiber_pointing_ui = FiberPointingUI()

    return app.exec()

if __name__ == '__main__':
    main()
