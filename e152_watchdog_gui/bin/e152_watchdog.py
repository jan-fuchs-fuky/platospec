#! /usr/bin/env python3
# -*- coding: utf-8 -*-

#
# Author: Jan Fuchs <fuky@asu.cas.cz>
#
# Copyright (C) 2022 Astronomical Institute, Academy Sciences of the Czech Republic, v.v.i.
#
#
# $ ssh pi@192.168.224.116 systemctl is-active pucheros_indiserver.service
# active
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

from pexpect import split_command_line
from subprocess import call, Popen, PIPE, TimeoutExpired
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

E152_WATCHDOG_UI = "%s/../share/e152_watchdog.ui" % SCRIPT_PATH
E152_WATCHDOG_CFG = "%s/../etc/e152_watchdog.cfg" % SCRIPT_PATH
E152_WATCHDOG_LOG = "%s/../log/e152_watchdog_%%s.log" % SCRIPT_PATH
E152_WATCHDOG_SOUNDS = "%s/../sounds" % SCRIPT_PATH

def init_logger(logger, filename):
    formatter = logging.Formatter("%(asctime)s - %(name)s[%(process)d] - %(levelname)s - %(message)s")

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

class GuiderCameraThread:

    def __init__(self, gui):
        self.gui = gui
        self.is_stop = gui.is_stop

    def call_cmd(self, cmd):
        self.logger.info("command = %s" % cmd)

        # WARNING: pokud je shell=True tak se odesle SIGTERM/SIGKILL shellu,
        # ale ne potomku, ktery provadi vlastni stahovani
        proc = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)

        try:
            outs, errs = proc.communicate(timeout=5)
        except TimeoutExpired:
            proc.kill()
            outs, errs = proc.communicate()
            self.logger.exception("Call command TimeoutExpired")

        outs = outs.decode("ascii").strip()
        errs = errs.decode("ascii").strip()

        self.logger.info("Call command stdout = %s" % outs)
        self.logger.info("Call command stderr = %s" % errs)

        retcode = proc.poll()

        if (retcode != 0):
            self.logger.error("Call command failed: %i" % retcode)
        else:
            self.logger.info("Call command was successful")

        return [outs, errs, retcode]

    def run_command(self, command):
        outs, errs, retcode = self.call_cmd(command)

        data = {
            "command": command,
            "result": outs,
        }

        self.progress_callback.emit(self.name, data)

    def run_read(self):
        variable2data = {
            "QHY CCD QHY5LII-M-60b7e.CONNECTION.CONNECT": "connection",
            "QHY CCD QHY5LII-M-60b7e.CCD_VIDEO_STREAM.STREAM_ON": "video_stream",
            "QHY CCD QHY5LII-M-60b7e.RECORD_STREAM.RECORD_ON": "record_stream",
            "QHY CCD QHY5LII-M-60b7e.CCD_GAIN.GAIN": "gain",
            "QHY CCD QHY5LII-M-60b7e.CCD_EXPOSURE.CCD_EXPOSURE_VALUE": "exposure",
        }

        while not self.gui.exit.is_set():

            data = {
                "indi_server": "unknown",
                "connection": "unknown",
                "video_stream": "unknown",
                "record_stream": "unknown",
                "gain": "unknown",
                "exposure": "unknown",
            }

            outs, errs, retcode = self.call_cmd(["ssh", self.gui.guiding_camera_ssh, "systemctl", "is-active", "pucheros_indiserver.service"])
            data["indi_server"] = outs

            outs, errs, retcode = self.call_cmd(["indi_getprop", "-h", self.gui.guiding_camera_ip, "-p", self.gui.guiding_camera_port])
            if retcode == 0:
                for line in outs.split("\n"):
                    try:
                        variable, value = line.split("=")
                    except:
                        self.logger.error("indi_getprop unknown line '%s'" % line)
                        continue

                    if variable in variable2data:
                        data[variable2data[variable]] = value

            self.progress_callback.emit(self.name, data)
            time.sleep(1)

    def run(self, progress_callback, name, command):
        self.progress_callback = progress_callback
        self.name = name

        self.logger = self.gui.thread_logger[name]
        self.logger.info("Starting process '%s'" % name)

        if name == "guiding_camera_read":
            self.run_read()
        else:
            self.run_command(command)

        return "Done."

class E152WatchdogUI(QMainWindow):

    COLORS = {
        "info": 0x000000,
        "highlight": 0x0000FF,
        "warning": 0xFF9966,
        "error": 0xFF0000,
    }

    def __init__(self):
        super(E152WatchdogUI, self).__init__()

        self.guiding_camera_ssh = "pi@192.168.224.116"
        self.guiding_camera_ip = "192.168.224.116"
        self.guiding_camera_port = "7624"

        self.sounds = {}
        self.sounds["error"] = QSound(os.path.join(E152_WATCHDOG_SOUNDS, "error.wav"))

        self.sounds_enabled = {}
        self.sounds_enabled["error"] = True

        self.status_color = {
            "IDLE": "#CCCCCC",
            "RUNNING": "#CCFFCC",
            "SUCCESS": "#FFFFFF",
            "FAILED": "#FFCCCC",
        }

        process_name = "gui"
        self.logger = logging.getLogger("e152_watchdog_%s" % process_name)
        init_logger(self.logger, E152_WATCHDOG_LOG % process_name)
        self.logger.info("Starting process '%s'" % process_name)

        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(10)

        self.exit = threading.Event()
        self.stop_event = threading.Event()
        self.rsync_event = threading.Event()
        self.status = ClientStatus.IDLE

        self.thread_logger = {}
        self.thread_exit = {}
        for key in ["guiding_camera_read", "guiding_camera_command"]:
            self.thread_exit[key] = threading.Event()
            self.thread_exit[key].set()

            self.thread_logger[key] = logging.getLogger(key)
            init_logger(self.thread_logger[key], E152_WATCHDOG_LOG % key)

        uic.loadUi(E152_WATCHDOG_UI, self)

        self.progress_callback_dict = {
            "guiding_camera_read": self.progress_guider_camera_read_fn,
            "guiding_camera_command": self.progress_guider_camera_command_fn,
        }

        self.start_indi_server_BT.clicked.connect(lambda: self.run_guider_camera_action("systemctl start pucheros_indiserver.service"))
        self.stop_indi_server_BT.clicked.connect(lambda: self.run_guider_camera_action("systemctl stop pucheros_indiserver.service"))
        self.guiding_camera_connect_BT.clicked.connect(lambda: self.run_guider_camera_action("CONNECTION.CONNECT=On"))
        self.guiding_camera_disconnect_BT.clicked.connect(lambda: self.run_guider_camera_action("CONNECTION.DISCONNECT=On"))
        self.guiding_camera_video_stream_off_BT.clicked.connect(lambda: self.run_guider_camera_action("CCD_VIDEO_STREAM.STREAM_OFF=On"))
        self.guiding_camera_record_stream_off_BT.clicked.connect(lambda: self.run_guider_camera_action("RECORD_STREAM.RECORD_OFF=On"))
        self.guiding_camera_exposure_abort_BT.clicked.connect(lambda: self.run_guider_camera_action("CCD_ABORT_EXPOSURE.ABORT=On"))

        #self.resize(640, 1024)

        self.start_guiding_camera_read_thread()

        self.show()

    def start_guiding_camera_read_thread(self):
        if not self.thread_exit["guiding_camera_read"].is_set():
            return

        self.thread_exit["guiding_camera_read"].clear()

        kwargs = {
            "name": "guiding_camera_read",
            "gui": self,
            "command": None,
            "thread_exit": self.thread_exit["guiding_camera_read"],
        }

        self.guiding_camera_read_thread = GuiderCameraThread(self)
        guiding_camera_read_worker = Worker(self.guiding_camera_read_thread.run, **kwargs)

        self.threadpool.start(guiding_camera_read_worker)

    def start_guiding_camera_command_thread(self, command):
        self.thread_exit["guiding_camera_command"].clear()

        kwargs = {
            "name": "guiding_camera_command",
            "gui": self,
            "command": command,
            "thread_exit": self.thread_exit["guiding_camera_command"],
        }

        self.guiding_camera_command_thread = GuiderCameraThread(self)
        guiding_camera_command_worker = Worker(self.guiding_camera_command_thread.run, **kwargs)

        self.threadpool.start(guiding_camera_command_worker)

    def run_guider_camera_action(self, action):
        if not self.thread_exit["guiding_camera_command"].is_set():
            self.log("Action already run", level="warning")
            return

        if action.startswith("systemctl"):
            command = ["ssh", self.guiding_camera_ssh, "sudo"] + split_command_line(action)
        else:
            command = ["indi_setprop", "-h", self.guiding_camera_ip, "-p", self.guiding_camera_port, "QHY CCD QHY5LII-M-60b7e.%s" % action]

        self.start_guiding_camera_command_thread(command)
        self.log("run %s" % command)

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

    def set_label_text(self, label, text, color="#CCFFCC"):
        if text in ["CALIBRATION", "ON"]:
            color = "#FFFF33"
        elif text in ["unknown"]:
            color = "#FFCCCC"

        label.setText(text)
        label.setStyleSheet("background-color: %s;" % color)

    def set_label_text_running(self, label):
        dt_str = datetime.now().strftime("%H:%M:%S")

        self.set_label_text(label, "RUNNING %s" % dt_str)

    def progress_guider_camera_read_fn(self, data):
        indi_server_color = "#CCFFCC"
        connection_color = "#CCFFCC"
        video_stream_color = "#CCFFCC"
        record_stream_color = "#CCFFCC"
        exposure_color = "#CCFFCC"

        if data["indi_server"] != "active":
            indi_server_color = "#FFCCCC"
        if data["connection"] != "On":
            connection_color = "#FFCCCC"
        if data["video_stream"] != "Off":
            video_stream_color = "#FFCCCC"
        if data["record_stream"] != "Off":
            record_stream_color = "#FFCCCC"
        if data["exposure"] != "0":
            exposure_color = "#FFFF33"

        self.set_label_text(self.guiding_camera_indi_server_LB, data["indi_server"], indi_server_color)
        self.set_label_text(self.guiding_camera_connection_LB, data["connection"], connection_color)
        self.set_label_text(self.guiding_camera_video_stream_LB, data["video_stream"], video_stream_color)
        self.set_label_text(self.guiding_camera_record_stream_LB, data["record_stream"], record_stream_color)
        self.set_label_text(self.guiding_camera_gain_LB, data["gain"])
        self.set_label_text(self.guiding_camera_exposure_LB, data["exposure"], exposure_color)

        self.set_label_text_running(self.guiding_camera_status_LB)

    def progress_guider_camera_command_fn(self, data):
        self.log("command result = %s" % data["result"])

    def thread_progress(self, category, data):
        if self.exit.is_set():
            return

        if category == "msg":
            self.refresh_statusbar(ClientStatus.RUNNING, data["msg"])
        elif category in self.progress_callback_dict:
            self.logger.debug("thread_progress(category = %s, data = %s)" % (category, data))
            self.progress_callback_dict[category](data)

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

        #if name == "rsync":
        #    self.set_label_text(self.rsync_LB, "STOPPED", "#FFCCCC")
        #    self.start_rsync_thread()

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

def main():
    app = QApplication([])
    e152_watchdog_ui = E152WatchdogUI()

    return app.exec()

if __name__ == '__main__':
    main()
