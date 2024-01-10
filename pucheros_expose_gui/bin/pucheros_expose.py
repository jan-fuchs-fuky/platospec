#! /usr/bin/env python3
# -*- coding: utf-8 -*-

#
# Author: Jan Fuchs <fuky@asu.cas.cz>
#
# Copyright (C) 2022 Astronomical Institute, Academy Sciences of the Czech Republic, v.v.i.
#
# https://python-socketio.readthedocs.io/en/latest/client.html
#
# Science:
#
#     POST http://192.168.224.115:5000/set_observation
#     Content-Type: application/json
#
#     {"observation_type":"science","sufix_name":"test","exposure_time":10,"comment1":"a","comment2":"b","obj_name":"c"}
#
#     Response: {"result":{"state":1}}
#
#     OPTIONS http://192.168.224.115:5000/set_observation
#
# Bias:
#
#     POST http://192.168.224.115:5000/set_observation
#
#     {"observation_type":"bias","sufix_name":"Bias","exposure_time":1e-7,"comment1":"a","comment2":"b","obj_name":"c"}
#
# Calib Flat:
#
#     {"observation_type":"calibration_flat","sufix_name":"Flat","exposure_time":2,"comment1":"a","comment2":"b","obj_name":"c"}
#
# Flat OFF:
#
#     POST http://192.168.224.115:5000/turn
#
#     {"turn":false,"lamp":"Led"}
#
# Calib Lamp ThAr:
#
#     {"observation_type":"calibration_thar","sufix_name":"Comp","exposure_time":25,"comment1":"a","comment2":"b","obj_name":"c"}
#
# Comp OFF:
#
#     POST http://192.168.224.115:5000/turn
#
#     {"turn":false,"lamp":"ThAr"}
#
# Mirror calibration (7.3 seconds):
#
#     POST http://192.168.224.115:5000/mirror_calibration
#
#     {"state":"calibration"}
#     {"state":"rest"}
#
# Start:
#
#     POST http://192.168.224.115:5000/start_observation
#
#     {"observation_type":"science","number_exposures":1}
#
#     Response:
#
#         {"result":
#             {"images":[
#                 "/opt/PucherosPlus-Data/images/2022-10-31/2022-10-30T21:33:58.945154-test.fits",
#                 "/opt/PucherosPlus-Data/images/2022-10-29/2022-10-29T07:17:00.777133-Flat.fits",
#                 "/opt/PucherosPlus-Data/images/2022-10-29/2022-10-29T07:16:56.638003-Flat.fits",
#                 ...
#
# 192.168.224.115:5000:
#
#     Received packet MESSAGE data 2["CCD_Temperature_Setpoint",-80]
#     Received packet MESSAGE data 2["Integration_time",0.0]
#     Received packet MESSAGE data 2["Led","OFF"]
#     Received packet MESSAGE data 2["Mirror","REST"]
#     Received packet MESSAGE data 2["ThAr","OFF"]
#     Received packet MESSAGE data 2["CCooler","DRV_TEMP_STABILIZED"]
#     Received packet MESSAGE data 2["Asc",142.27]
#     Received packet MESSAGE data 2["Dec",32.18]
#     Received packet MESSAGE data 2["Bin_width",1]
#     Received packet MESSAGE data 2["Bin_height",1]
#     Received packet MESSAGE data 2["Speed",1.0]
#     Received packet MESSAGE data 2["CCD_Temperature",-79.9]
#

import os
import re
import sys
import requests
import time
import logging
import threading
import traceback
import subprocess
import multiprocessing
import socketio

from subprocess import call, Popen, PIPE
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler
from enum import Enum

from PyQt5 import (
    uic,
    QtCore,
)

from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtMultimedia import QSound

from PyQt5.QtWidgets import (
    QMessageBox,
    QMainWindow,
    QPushButton,
    QApplication,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QLineEdit,
    QDialog,
    QDialogButtonBox,
    QVBoxLayout,
    QLabel,
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QSizePolicy,
)

from PyQt5.QtCore import (
    QRunnable,
    QThreadPool,
    QObject,
    pyqtSlot,
    pyqtSignal,
    Qt,
    QDir,
)

SCRIPT_PATH = os.path.dirname(os.path.realpath(os.path.abspath(__file__)))
sys.path.append(SCRIPT_PATH)

PUCHEROS_EXPOSE_UI = "%s/../share/pucheros_expose.ui" % SCRIPT_PATH
PUCHEROS_EXPOSE_CFG = "%s/../etc/pucheros_expose.cfg" % SCRIPT_PATH
PUCHEROS_EXPOSE_LOG = "%s/../log/pucheros_expose_%%s.log" % SCRIPT_PATH
PUCHEROS_EXPOSE_SOUNDS = "%s/../sounds" % SCRIPT_PATH

def init_logger(logger, filename):
    formatter = logging.Formatter("%(asctime)s - %(name)s[%(process)d][%(thread)d] - %(levelname)s - %(message)s")

    # DBG
    #formatter = logging.Formatter(
    #    ("%(asctime)s - %(name)s[%(process)d][%(thread)d] - %(levelname)s - "
    #     "%(filename)s:%(lineno)s - %(funcName)s() - %(message)s - "))

    fh = RotatingFileHandler(filename, maxBytes=10485760, backupCount=10)
    #fh.setLevel(logging.INFO)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)

    #logger.setLevel(logging.INFO)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(fh)

class ClientStatus(Enum):

    IDLE = 0
    RUNNING = 1
    SUCCESS = 2
    FAILED = 3

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

class RsyncThread:

    def __init__(self, gui):
        self.gui = gui
        self.is_stop = gui.is_stop

    def rsync_progress(self, msg, color):
        dt_str = datetime.now().strftime("%H:%M:%S")

        data = {
            "msg": "%s - %s" % (dt_str, msg),
            "color": color,
        }

        self.progress_callback.emit(self.name, data)

    # /usr/bin/ds9 -title pucheros
    def ds9_xpaset(self, filename):
        cmd = [self.xpaset_bin, "-p", self.ds9_title, "file", filename]
        self.logger.info(cmd)

        try:
            output = subprocess.check_output(cmd)
        except:
            self.logger.exception("xpaset failed")

    def call_cmd(self, cmd):
        self.logger.info("command = %s" % cmd)

        # WARNING: pokud je shell=True tak se odesle SIGTERM/SIGKILL shellu,
        # ale ne potomku, ktery provadi vlastni stahovani
        pipe = Popen(cmd)
        retcode = None
        while retcode is None:
            retcode = pipe.poll()
            self.rsync_progress("RUNNING", "#CCFFCC")
            time.sleep(1)

        if (retcode != 0):
            self.logger.error("Call command failed: %i" % retcode)
            self.rsync_progress("FAILED %i" % retcode, "#FFCCCC")
            return

        self.logger.info("Call command was successful")
        self.rsync_progress("SUCCESS", "#CCFFCC")

    def get_last_fits(self, data_dir):

        for filename in reversed(sorted(os.listdir(data_dir))):
            if not filename.endswith(".fits"):
                continue

            return os.path.join(data_dir, filename)

    def run_rsync(self):
        local_data_dir = "/data/pucheros_sci/"

        while not self.gui.exit.is_set():
            night_dt = datetime.utcnow()

            if night_dt.hour > 18:
                night_dt = night_dt + timedelta(days=1)

            yyyy_mm_dd = night_dt.strftime("%Y-%m-%d")

            cmd = [
                "rsync",
                "-a",
                "pucherosmgr@192.168.224.115:/opt/PucherosPlus-Data/images/%s" % yyyy_mm_dd,
                local_data_dir,
            ]

            if self.rsync_event.is_set():
                self.rsync_event.clear()
                self.call_cmd(cmd)

                filename = self.get_last_fits(os.path.join(local_data_dir, yyyy_mm_dd))
                if filename:
                    self.ds9_xpaset(filename)
            else:
                self.rsync_progress("WAITING", "#CCCCCC")

            time.sleep(1)

    def run(self, progress_callback, name, rsync_event, xpaset_bin, ds9_title):
        time.sleep(5)
        self.progress_callback = progress_callback
        self.name = name
        self.rsync_event = rsync_event
        self.xpaset_bin = xpaset_bin
        self.ds9_title = ds9_title

        self.logger = logging.getLogger(name)
        init_logger(self.logger, PUCHEROS_EXPOSE_LOG % name)
        self.logger.info("Starting process '%s'" % name)

        while not self.gui.exit.is_set():
            try:
                self.run_rsync()
            except:
                self.logger.exception("rsync failed")
                self.rsync_progress("ERROR: %s" % traceback.format_exc(), "#FFCCCC")
                self.rsync_event.set()
                time.sleep(5)

        return "Done."

class ExposeThread:
    sio = socketio.Client()
    pucheros_connect = False
    CCD_Temperature = 0
    Integration_time = 0
    Mirror = ""
    Led = ""
    ThAr = ""

    def __init__(self, gui):
        self.gui = gui
        self.is_stop = gui.is_stop

    def callbacks(self):
        @self.sio.event
        def connect():
            self.pucheros_connect = True

        @self.sio.event
        def connect_error(data):
            self.pucheros_connect = False

        @self.sio.event
        def disconnect():
            self.pucheros_connect = False

        @self.sio.event
        def CCD_Temperature(message):
            self.CCD_Temperature = message

        @self.sio.event
        def Integration_time(message):
            self.Integration_time = message

        @self.sio.event
        def Led(message):
            self.Led = message

        @self.sio.event
        def Mirror(message):
            self.Mirror = message

        @self.sio.event
        def ThAr(message):
            self.ThAr = message

    def run_command(self, command):
        pucheros_expose = PucherosExpose(self.logger)

        callbacks = {
            "mirror_target": pucheros_expose.set_mirror_rest,
            "mirror_calibration": pucheros_expose.set_mirror_calibration,
            "comp_lamp_on": pucheros_expose.comp_on,
            "comp_lamp_off": pucheros_expose.comp_off,
            "flat_lamp_on": pucheros_expose.flat_on,
            "flat_lamp_off": pucheros_expose.flat_off,
        }

        if "action" in command:
            action = command["action"]
            if action in callbacks:
                callbacks[action]()
            return

        for counter in range(1, command["count_repeat"]+1):
            if self.is_stop():
                break

            data = {
                "expose_number": counter,
                "exposure_time": command["exposure_time"],
            }
            self.progress_callback.emit(self.name, data)

            if command["object"] == "target":
                pucheros_expose.run_science(command["exposure_time"], command["target"])
                self.rsync_event.set()
                if command["comp_after_every_exposure"]:
                    data = {
                        "expose_number": counter,
                        "exposure_time": 25,
                    }
                    self.progress_callback.emit(self.name, data)
                    pucheros_expose.run_comp(25)
            elif command["object"] == "comp":
                pucheros_expose.run_comp(25)
            elif command["object"] == "flat":
                pucheros_expose.run_flat(2)
            elif command["object"] == "zero":
                pucheros_expose.run_bias()

            self.rsync_event.set()
            time.sleep(1)

    def run_read(self):
        self.sio.connect('http://192.168.224.115:5000')

        while not self.gui.exit.is_set():
            self.sio.sleep(1)

            data = {
                "CCD_Temperature": self.CCD_Temperature,
                "Integration_time": self.Integration_time,
                "Mirror": self.Mirror,
                "Flat": self.Led,
                "Comp": self.ThAr,
            }

            self.progress_callback.emit(self.name, data)

            status = "idle"
            if self.Integration_time > 0.1:
                status = "exposing"

            if not self.pucheros_connect:
                status = "no connection"

            self.progress_callback.emit("msg", {"msg": status})

    def run(self, progress_callback, name, command, rsync_event):
        self.progress_callback = progress_callback
        self.name = name
        self.rsync_event = rsync_event

        self.logger = logging.getLogger(name)
        init_logger(self.logger, PUCHEROS_EXPOSE_LOG % name)
        self.logger.info("Starting process '%s'" % name)

        if name == "expose_read":
            self.callbacks()
            self.run_read()
        else:
            self.run_command(command)

        return "Done."

class PucherosExpose:

    def __init__(self, logger):
        self.logger = logger
        self.server = "http://192.168.224.115:5000"

    def run_action(self, action, params):
        url = "%s/%s" % (self.server, action)
        response = requests.post(url, json=params)

        self.logger.info("params = %s" % params)
        self.logger.info("action %s => %i" % (action, response.status_code))

        if response.status_code != 200:
            raise Exception("%s %s failed" % (action, params))

    def run_expose(self, exposure_time, observation_type, suffix_name):
        params = {
            "observation_type": observation_type,
            "sufix_name": suffix_name,
            "exposure_time": exposure_time,
            "comment1": "a",
            "comment2": "b",
            "obj_name": "c",
        }

        self.run_action("set_observation", params)

        params = {
            "observation_type": observation_type,
            "number_exposures": 1,
        }

        self.run_action("start_observation", params)

    def calibration_off(self):
        self.set_mirror_rest()
        self.flat_off()
        self.comp_off()

    def run_bias(self):
        self.calibration_off()
        time.sleep(1)
        self.run_expose(1e-7, "bias", "Bias")

    def run_flat(self, exposure_time):
        self.comp_off()
        time.sleep(1)
        self.run_expose(exposure_time, "calibration_flat", "Flat")
        self.flat_off()

    def run_comp(self, exposure_time):
        self.flat_off()
        time.sleep(1)
        self.run_expose(exposure_time, "calibration_thar", "Comp")
        self.comp_off()

    def run_science(self, exposure_time, suffix_name):
        self.calibration_off()
        self.run_expose(exposure_time, "science", suffix_name)

    def flat_on(self):
        self.run_turn("Led", True)

    def comp_on(self):
        self.run_turn("ThAr", True)

    def flat_off(self):
        self.run_turn("Led", False)

    def comp_off(self):
        self.run_turn("ThAr", False)

    def run_turn(self, lamp, turn):
        params = {
            "turn": turn,
            "lamp": lamp,
        }

        self.run_action("turn", params)

    def set_mirror_calibration(self):
        self.set_mirror("calibration")

    def set_mirror_rest(self):
        self.set_mirror("rest")

    def set_mirror(self, state):
        params = {
            "state": state,
        }

        self.run_action("mirror_calibration", params)

class PucherosExposeUI(QMainWindow):

    COLORS = {
        "info": 0x000000,
        "highlight": 0x0000FF,
        "warning": 0xFF9966,
        "error": 0xFF0000,
    }

    def __init__(self):
        super(PucherosExposeUI, self).__init__()

        self.xpaset_bin = "/usr/bin/xpaset"
        self.ds9_bin = "/usr/bin/ds9"
        self.ds9_title = "pucheros"
        self.ds9_processes = []

        self.run_ds9()
        time.sleep(1)

        self.sounds = {}
        self.sounds["error"] = QSound(os.path.join(PUCHEROS_EXPOSE_SOUNDS, "error.wav"))
        self.sounds["set"] = QSound(os.path.join(PUCHEROS_EXPOSE_SOUNDS, "set.wav"))
        self.sounds["new_image"] = QSound(os.path.join(PUCHEROS_EXPOSE_SOUNDS, "new_image.wav"))

        self.sounds_enabled = {}
        self.sounds_enabled["error"] = True
        self.sounds_enabled["set"] = True
        self.sounds_enabled["new_image"] = True

        self.status_color = {
            "IDLE": "#CCCCCC",
            "RUNNING": "#CCFFCC",
            "SUCCESS": "#FFFFFF",
            "FAILED": "#FFCCCC",
        }

        self.expose_number = 0
        self.exposure_time = 0

        # FITs header: Note that the header unit may only contain ASCII text
        # characters ranging from hexadecimal 20 to 7E); non-printing ASCII
        # characters such as tabs, carriage-returns, or line-feeds are not allowed
        # anywhere within the header unit.
        #
        # http://fits.gsfc.nasa.gov/fits_primer.html
        self.fits_header_pattern = re.compile('^[\x20-\x7E]{1,68}$')

        process_name = "gui"
        self.logger = logging.getLogger("pucheros_expose_%s" % process_name)
        init_logger(self.logger, PUCHEROS_EXPOSE_LOG % process_name)
        self.logger.info("Starting process '%s'" % process_name)

        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(10)

        self.exit = threading.Event()
        self.stop_event = threading.Event()
        self.rsync_event = threading.Event()
        self.status = ClientStatus.IDLE

        self.thread_exit = {}
        for key in ["expose_read", "expose_command", "rsync"]:
            self.thread_exit[key] = threading.Event()
            self.thread_exit[key].set()

        uic.loadUi(PUCHEROS_EXPOSE_UI, self)

        self.progress_callback_dict = {
            "expose_command": self.progress_expose_command_fn,
            "expose_read": self.progress_expose_read_fn,
            "rsync": self.progress_rsync_fn,
        }

        self.start_BT.clicked.connect(self.start_clicked)
        self.stop_BT.clicked.connect(self.stop_clicked)

        self.mirror_calibration_BT.clicked.connect(lambda: self.run_pucheros_action("mirror_calibration"))
        self.mirror_target_BT.clicked.connect(lambda: self.run_pucheros_action("mirror_target"))
        self.comp_lamp_on_BT.clicked.connect(lambda: self.run_pucheros_action("comp_lamp_on"))
        self.comp_lamp_off_BT.clicked.connect(lambda: self.run_pucheros_action("comp_lamp_off"))
        self.flat_lamp_on_BT.clicked.connect(lambda: self.run_pucheros_action("flat_lamp_on"))
        self.flat_lamp_off_BT.clicked.connect(lambda: self.run_pucheros_action("flat_lamp_off"))

        self.object_CB.currentIndexChanged.connect(self.object_changed)
        self.object_changed(-1)

        self.progressBar.setValue(0)
        self.resize(640, 1024)

        self.start_expose_read_thread()
        self.start_rsync_thread()

        self.play("set")
        self.show()

    def set_enabled_widgets(self, widgets, value):
        for widget in widgets:
            widget.setEnabled(value)

    def object_changed(self, idx):
        target_widgets_enabled = [
            self.target_LE,
            self.exposure_time_SB,
        ]

        exposure_time = {
            "zero": 0,
            "flat": 2,
            "comp": 25,
            "target": 600,
        }

        current_object = self.object_CB.currentText()

        if current_object == "target":
            self.set_enabled_widgets(target_widgets_enabled, True)
            self.target_LE.setText("")
        else:
            self.set_enabled_widgets(target_widgets_enabled, False)
            self.target_LE.setText(current_object)

        if current_object in exposure_time:
            self.exposure_time_SB.setValue(exposure_time[current_object])

    def start_rsync_thread(self):
        if not self.thread_exit["rsync"].is_set():
            return

        self.rsync_event.set()
        self.thread_exit["rsync"].clear()

        kwargs = {
            "name": "rsync",
            "gui": self,
            "rsync_event": self.rsync_event,
            "xpaset_bin": self.xpaset_bin,
            "ds9_title": self.ds9_title,
            "thread_exit": self.thread_exit["rsync"],
        }

        self.rsync_thread = RsyncThread(self)
        rsync_worker = Worker(self.rsync_thread.run, **kwargs)

        self.threadpool.start(rsync_worker)

    def start_expose_read_thread(self):
        self.exit.clear()
        self.stop_event.clear()
        self.thread_exit["expose_read"].clear()

        kwargs = {
            "name": "expose_read",
            "gui": self,
            "command": None,
            "rsync_event": self.rsync_event,
            "thread_exit": self.thread_exit["expose_read"],
        }

        self.expose_thread = ExposeThread(self)
        expose_worker = Worker(self.expose_thread.run, **kwargs)

        self.threadpool.start(expose_worker)

    def start_expose_command_thread(self, command):
        self.exit.clear()
        self.stop_event.clear()
        self.thread_exit["expose_command"].clear()

        kwargs = {
            "name": "expose_command",
            "gui": self,
            "command": command,
            "rsync_event": self.rsync_event,
            "thread_exit": self.thread_exit["expose_command"],
        }

        self.expose_thread = ExposeThread(self)
        expose_worker = Worker(self.expose_thread.run, **kwargs)

        self.threadpool.start(expose_worker)

    def run_pucheros_action(self, action):
        if not self.thread_exit["expose_command"].is_set():
            self.log("Action already run", level="warning")
            return

        command = {
            "action": action,
        }

        self.start_expose_command_thread(command)

        self.log("run %s" % action)

    def show_msg(self, msg, category="info"):
        category2icon = {
            "question": QMessageBox.Question,
            "info": QMessageBox.Information,
            "warning": QMessageBox.Warning,
            "error": QMessageBox.Critical,
        }

        icon = QMessageBox.NoIcon
        if category in category2icon:
            icon = category2icon[category]

        msg_box = QMessageBox()
        msg_box.setIcon(icon)
        msg_box.setText(msg)
        msg_box.setWindowTitle("Expose: %s" % category)
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec()

    def start_clicked(self):
        if not self.thread_exit["expose_command"].is_set():
            self.log("Action already run", level="warning")
            return

        self.target_LE.setText(self.target_LE.text().replace(' ', '_'))

        match = self.fits_header_pattern.search(self.target_LE.text())
        if not match:
            msg = ("Target format must be:\n\n"
                   "- ASCII text characters ranging from hexadecimal 20 to 7E\n"
                   "- max length is 68 characters\n"
                   "- min length is 1 character")

            self.show_msg(msg, "error")
            return

        command = {
            "object": self.object_CB.currentText(),
            "target": self.target_LE.text(),
            "exposure_time": self.exposure_time_SB.value(),
            "count_repeat": self.count_repeat_SB.value(),
            "comp_after_every_exposure": self.comp_after_every_exposure_CHECKBOX.isChecked(),
        }

        self.start_expose_command_thread(command)

        self.log("expose: %s" % command)

    def stop_clicked(self):
        self.stop_event.set()
        self.log("expose stop")

    # "OFF", "REST", "CALIBRATION", "ON"
    def set_label_text(self, label, text, color="#CCFFCC"):
        if text in ["CALIBRATION", "ON"]:
            color = "#FFFF33"

        label.setText(text)
        label.setStyleSheet("background-color: %s;" % color)

    def progress_rsync_fn(self, data):
        msg = data["msg"]
        self.set_label_text(self.rsync_LB, msg, data["color"])

        if msg.find("SUCCESS") != -1 or msg.find("FAILED") != -1:
            self.play("new_image")

    def progress_expose_command_fn(self, data):
        self.expose_number = data["expose_number"]
        self.exposure_time = data["exposure_time"]

    def progress_expose_read_fn(self, data):
        self.set_label_text(self.mirror_LB, data["Mirror"])
        self.set_label_text(self.comp_lamp_LB, data["Comp"])
        self.set_label_text(self.flat_lamp_LB, data["Flat"])
        self.set_label_text(self.ccd_temperature_LB, "%.1f °C" % data["CCD_Temperature"])

        data["expose_number"] = self.expose_number
        data["expose_count"] = self.count_repeat_SB.value()
        data["full_time"] = self.exposure_time

        data["elapsed_time"] = data["full_time"] - data["Integration_time"]

        if data["elapsed_time"] > data["full_time"]:
            data["elapsed_time"] = data["full_time"]

        if data["full_time"] <= 0.1:
            percent = 100
        else:
            percent = round((data["elapsed_time"] / data["full_time"]) * 100)

        remained_time = data["full_time"] - data["elapsed_time"]
        data["remained_time_str"] = str(timedelta(seconds=remained_time))

        self.progressBar.setValue(percent)
        self.progressBar.setFormat("%(remained_time_str)s (%(expose_number)i/%(expose_count)i)" % data)

    def thread_progress(self, category, data):
        if self.exit.is_set():
            return

        if category == "msg":
            self.refresh_statusbar(ClientStatus.RUNNING, data["msg"])
        elif category in self.progress_callback_dict:
            self.logger.debug("thread_progress(category = %s, data = %s)" % (category, data))
            self.progress_callback_dict[category](data)
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

        self.log(value)

    def thread_finished(self, name):
        if self.exit.is_set():
            self.logger.info("%s COMPLETE! Exiting..." % name)
            return

        if self.status != ClientStatus.FAILED:
            self.refresh_statusbar(ClientStatus.SUCCESS)

        self.logger.info("%s COMPLETE!" % name)

        # WARNING: je treba odladit korektni postup vytvoreni nove instance tridy kde se inicializuje sio
        #if name == "expose_read":
        #    self.start_expose_read_thread()

        if name == "rsync":
            self.set_label_text(self.rsync_LB, "STOPPED", "#FFCCCC")
            self.start_rsync_thread()

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

    def refresh_statusbar(self, value, msg=""):
        dt_str = datetime.now().strftime("%H:%M:%S")
        name = value.name
        self.status = value

        self.statusbar.showMessage("Status: %s %s %s" % (name, dt_str, msg))
        self.statusbar.setStyleSheet("background-color: %s;" % self.status_color[name])

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

    def play(self, name):
        if self.sounds_enabled[name]:
            self.sounds[name].play()

    def fce_ds9_process(self, ds9_bin, title):
        cmd = [ds9_bin, "-title", title]

        subprocess.call(cmd)

    def run_ds9(self):
        try:
            if self.ds9_bin:
                process = multiprocessing.Process(target=self.fce_ds9_process, args=(self.ds9_bin, self.ds9_title))
                process.start()

                self.ds9_processes.append(process)
        except:
            self.logger.exception("ds9 failed")

def main():
    app = QApplication([])
    pucheros_expose_ui = PucherosExposeUI()

    return app.exec()

if __name__ == '__main__':
    main()
