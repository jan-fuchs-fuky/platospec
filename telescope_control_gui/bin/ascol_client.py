#! /usr/bin/env python3
# -*- coding: utf-8 -*-

#
# Author: Jan Fuchs <fuky@asu.cas.cz>
#
# Copyright (C) 2022 Astronomical Institute, Academy Sciences of the Czech Republic, v.v.i.
#
# ICE_CONFIG=/home/fuky/git/utils/exo/chile/etc/ice_client.cfg ./ascol_client.py
#

import os
import sys
import re
import time
import json
import requests
import xmlrpc.client
import configparser
import traceback
import xmlrpc.client
import threading
import logging
import Ice
import numpy as np

from operator import methodcaller
from enum import Enum
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from astroplan.plots import plot_airmass, plot_sky
from astroplan import FixedTarget, Observer

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg

from astropy.coordinates import EarthLocation, SkyCoord, AltAz
from astropy.time import Time
from astropy import units as u
from astroquery.simbad import Simbad

from PyQt5 import (
    uic,
    QtCore,
)

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
sys.path.append("%s/../python" % SCRIPT_PATH)

import PlatoSpec

ASCOL_CLIENT_UI = "%s/../share/ascol_client.ui" % SCRIPT_PATH

ASCOL_CLIENT_CFG = "%s/../etc/ascol_client.cfg" % SCRIPT_PATH
TELESCOPE_RESTRICTIONS_EAST_TXT = "%s/../etc/limits_east.txt" % SCRIPT_PATH
TELESCOPE_RESTRICTIONS_WEST_TXT = "%s/../etc/limits_west.txt" % SCRIPT_PATH

ASCOL_CLIENT_LOG = "%s/../log/ascol_client_%%s.log" % SCRIPT_PATH

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
        `tuple` (exctype, value, traceback.format_exc() )

    result
        `object` data returned from processing, anything

    progress
        `int` indicating % progress

    '''
    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
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
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        else:
            self.signals.result.emit(result)  # Return the result of the processing
        finally:
            self.thread_exit.set()
            self.signals.finished.emit()  # Done

class AscolThread:
    GLST = {
        "state_of_telescope": {
            "0": "OFF",
            "1": "STOP",
            "2": "TRACK",
            "3": "SLEW",
            "4": "SLEWHADA",
            "5": "SYNC",
            "6": "PARK",
        },

        "dome": {
            "0": "STOP",
            "1": "PLUS",
            "2": "MINUS",
            "3": "AUTO_STOP",
            "4": "AUTO_PLUS",
            "5": "AUTO_MINUS",
            "6": "SYNC",
            "7": "SLEW_MINUS",
            "8": "SLEW_PLUS",
            "9": "SLIT",
        },

        "slit": {
            "0": "unknown",
            "1": "opening",
            "2": "closing",
            "3": "opened",
            "4": "closed",
        },

        "mirror_cover": {
            "0": "unknown",
            "1": "opening",
            "2": "closing",
            "3": "opened",
            "4": "closed",
        },

        "focus": {
            "0": "stopped",
            "1": "manual minus",
            "2": "manual plus",
            "3": "positioning",
        },

        "status_bits1": {},
        "status_bits2": {},
    }

    def __init__(self, gui):
        self.gui = gui
        self.cfg = gui.cfg
        self.is_stop = gui.is_stop

    def ascol_send(self, cmd, frequent=False):
        if frequent:
            logger_fce = self.logger.debug
        else:
            logger_fce = self.logger.info

        answer = self.telescope_proxy.run_ascol(cmd)

        if answer != "ERR":
            logger_fce("ASCOL '%s' => '%s'" % (cmd, answer))
        else:
            self.logger.error("ASCOL '%s' => '%s'" % (cmd, answer))

        return answer

    def run_read(self):

        while not self.is_stop():
            status = self.telescope_proxy.get_status()

            # hour_axis_LB
            # declination_axis_LB
            # ra_LB
            # dec_LB
            # position_LB
            # utc_LB
            # lst_LB
            # ha_LB
            # azimuth_LB
            # altitude_LB
            # airmass_LB

            self.progress_callback.emit("read", status)
            time.sleep(1)

    def run_command(self, command):
        for item in command:
            result = self.ascol_send(item)

            data = {
                "command": item,
                "result": result,
            }

            self.progress_callback.emit("command", data)
            time.sleep(0.1)

    def run(self, progress_callback, command):
        self.progress_callback = progress_callback # TODO: přesunout do konstruktoru

        if command is None:
            suffix = "read"
        else:
            suffix = "command"

        process_name = "ascol_%s" % suffix
        self.logger = logging.getLogger("ascol_client_%s" % process_name)
        init_logger(self.logger, ASCOL_CLIENT_LOG % process_name)
        self.logger.info("Starting process '%s'" % process_name)

        with Ice.initialize(sys.argv) as communicator:
            base = communicator.stringToProxy("Telescope:default -h %(host)s -p %(port)i" % self.cfg["ice_telescope"])
            self.telescope_proxy = PlatoSpec.TelescopePrx.checkedCast(base)
            if not self.telescope_proxy:
                raise RuntimeError("Invalid proxy")

            if command is None:
                self.run_read()
            else:
                self.run_command(command)

        return "Done."

class MatplotlibCanvas(FigureCanvasQTAgg):
    """Ultimately, this is a QWidget (as well as a FigureCanvasAgg, etc.)."""

    def __init__(self, parent=None, width=4, height=4, dpi=100, polar=False):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = fig.add_subplot(111, polar=polar)

        FigureCanvasQTAgg.__init__(self, fig)
        self.setParent(parent)

        FigureCanvasQTAgg.setSizePolicy(self,
                                   QSizePolicy.Expanding,
                                   QSizePolicy.Expanding)
        FigureCanvasQTAgg.updateGeometry(self)

class RestrictionsMatplotlibCanvas(MatplotlibCanvas):

    def __init__(self, parent=None, width=4, height=4, dpi=100):
        super(RestrictionsMatplotlibCanvas, self).__init__(parent, width, height, dpi)

    def set_restrictions(self, east_restrictions, west_restrictions):
        self.east_restrictions = east_restrictions
        self.west_restrictions = west_restrictions

    def plot_restrictions(self, target, time, observer, ha, da):
        self.axes.cla()

        self.axes.plot(self.east_restrictions[0], self.east_restrictions[1], color="red")
        self.axes.plot(self.west_restrictions[0], self.west_restrictions[1], color="red")
        self.axes.plot(ha, da, marker="o", markersize=5, markeredgecolor="red", markerfacecolor="red")

        self.draw()

class StarMatplotlibCanvas(MatplotlibCanvas):

    def __init__(self, parent=None, width=4, height=4, dpi=100):
        super(StarMatplotlibCanvas, self).__init__(parent, width, height, dpi, polar=False)

    def plot_star(self, target, time, observer):
        self.axes.cla()

        plot_airmass(target, observer, time, self.axes, brightness_shading=True, altitude_yaxis=True)
        self.draw()

class LimitsMatplotlibCanvas(MatplotlibCanvas):

    def __init__(self, parent=None, width=4, height=4, dpi=100):
        super(LimitsMatplotlibCanvas, self).__init__(parent, width, height, dpi, polar=True)

    def plot_star(self, coord, time, observer):
        self.axes.cla()

        target = FixedTarget(coord=coord, name="Sirius")
        style = {"color": "r"}

        # Every call to the function astroplan.plots.plot_sky raises an exception.
        # https://github.com/astropy/astroplan/issues/468
        # ValueError: The number of FixedLocator locations (8), usually from a call to set_ticks, does not match the number of ticklabels (7).
        # SOLUTION: https://github.com/astropy/astroplan/pull/494/commits/161be86047dbf3abdf4ade926a179f4aad05ac2b
        # # dpkg-divert --divert /usr/lib/python3/dist-packages/astroplan/plots/sky.py.orig --rename /usr/lib/python3/dist-packages/astroplan/plots/sky.py
        # $ vim /usr/lib/python3/dist-packages/astroplan/plots/sky.py
        #     216c216
        #     <     ax.set_thetagrids(range(0, 360, 45), theta_labels)
        #     ---
        #     >     ax.set_thetagrids(range(0, 315, 45), theta_labels)
        plot_sky(target, observer, time, self.axes, style_kwargs=style)
        self.draw()

class LoadTargetFromSimbadDialog(QDialog):

    def __init__(self, targets, parent=None):
        super().__init__(parent=parent)

        self.setWindowTitle("ObserveClient: Select Target")

        buttons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel

        self.button_box = QDialogButtonBox(buttons)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.columns = {
            'Object': 0,
            'V mag': 1,
            'RA': 2,
            'DEC': 3,
        }

        conv = {
            'object': 'Object',
            'v_mag': 'V mag',
            'ra': 'RA',
            'dec': 'DEC',
        }

        targets_len = len(targets)

        self.targets_TW = QTableWidget()
        self.targets_TW.setSelectionMode(QAbstractItemView.SingleSelection)
        self.targets_TW.setColumnCount(len(self.columns))
        self.targets_TW.setRowCount(targets_len)
        self.targets_TW.setHorizontalHeaderLabels(self.columns.keys())
        self.targets_TW.setSelectionBehavior(QTableWidget.SelectRows)
        self.targets_TW.setEditTriggers(QTableWidget.NoEditTriggers)

        for row, target in enumerate(targets):
            for key in target:
                column_name = conv[key]
                column = self.columns[column_name]
                value = target[key]

                if isinstance(value, bytes):
                    value = value.decode("utf-8")
                else:
                    value = str(value)

                self.targets_TW.setItem(row, column, QTableWidgetItem(value))

        if targets_len > 0:
            self.targets_TW.setCurrentCell(0, 0)

        self.layout = QVBoxLayout()
        self.layout.addWidget(self.targets_TW)
        self.layout.addWidget(self.button_box)
        self.setLayout(self.layout)

        self.resize(640, 480)

    def get_selected_target_idx(self):
        current_row = self.targets_TW.currentRow()

        return current_row

class LoadTargetFromSimbadThread:

    def __init__(self, gui):
        self.gui = gui

    def simbad_query(self, target):
        Simbad.reset_votable_fields()
        Simbad.remove_votable_fields("coordinates")
        Simbad.add_votable_fields("ra(:;A;ICRS;J2000)", "dec(:;D;ICRS;2000), flux(V)")

        result_table = Simbad.query_object(target, wildcard=False)

        targets = []
        if not result_table:
            return targets

        for item in result_table:
            ra = "{}h{}m{}s".format(*item["RA___A_ICRS_J2000"].split(":"))
            dec = "{}d{}m{}s".format(*item["DEC___D_ICRS_2000"].split(":"))
            coord = SkyCoord(ra, dec, frame="icrs", equinox="J2000")

            targets.append({
                "object": item["MAIN_ID"],
                "v_mag": item["FLUX_V"],
                "ra": coord.ra.to_string(unit=u.hourangle, sep="", precision=1, pad=True),
                "dec": coord.dec.to_string(sep="", precision=1, pad=True),
            })

        return targets

    def run(self, progress_callback, target):
        try:
            targets = self.simbad_query(target)
        except:
            traceback.print_exc()
            targets = []

        return targets

    def result(self, targets):
        print("SelectTargetThread.result")

        if self.gui.exit.is_set():
            return

        dialog = LoadTargetFromSimbadDialog(targets, parent=self.gui)

        if not dialog.exec_():
            return

        idx = dialog.get_selected_target_idx()

        if idx == -1:
            return

        target = targets[idx]

        self.gui.ra_LE.setText(target["ra"])
        self.gui.dec_LE.setText(target["dec"])

    def finished(self):
        print("LoadTargetFromSimbadThread.finished")

        if self.gui.exit.is_set():
            print("SelectTargetThread COMPLETE! Exiting...")
            return

        if self.gui.status != ClientStatus.FAILED:
            self.gui.refresh_statusbar(ClientStatus.SUCCESS)

        print("LoadTargetFromSimbadThread COMPLETE!")

    def progress(self, category, data):
        print("LoadTargetFromSimbadThread.progress")

        if self.gui.exit.is_set():
            return

    def error(self, error):
        print("LoadTargetFromSimbadThread.error")

        if self.gui.exit.is_set():
            return

        exctype, value, format_exc = error

        self.gui.refresh_statusbar(ClientStatus.FAILED, "%s %s" % (exctype, value))

class ASCOLClientUI(QMainWindow):

    def __init__(self):
        super(ASCOLClientUI, self).__init__()

        self.redraw_canvas_counter = time.perf_counter() - 3600

        process_name = "gui"
        self.logger = logging.getLogger("ascol_client_%s" % process_name)
        init_logger(self.logger, ASCOL_CLIENT_LOG % process_name)
        self.logger.info("Starting process '%s'" % process_name)

        self.exit = threading.Event()
        self.stop_event = threading.Event()
        self.star_is_ready_event = threading.Event()
        self.status = ClientStatus.IDLE

        self.thread_exit = {}
        for key in ["read", "command", "simbad"]:
            self.thread_exit[key] = threading.Event()
            self.thread_exit[key].set()

        self.status_color = {
            "IDLE": "#CCCCCC",
            "RUNNING": "#CCFFCC",
            "SUCCESS": "#FFFFFF",
            "FAILED": "#FFCCCC",
        }

        self.load_cfg()
        self.east_restrictions = self.get_restrictions(TELESCOPE_RESTRICTIONS_EAST_TXT)
        self.west_restrictions = self.get_restrictions(TELESCOPE_RESTRICTIONS_WEST_TXT)

        self.longitude = self.cfg["observer"]["longitude"] * u.deg
        self.latitude = self.cfg["observer"]["latitude"] * u.deg
        self.elevation = self.cfg["observer"]["elevation"] * u.m

        self.observer = Observer(longitude=self.longitude, latitude=self.latitude, elevation=self.elevation)
        self.earth_location = EarthLocation(lat=self.latitude, lon=self.longitude, height=self.elevation)

        self.ra_pattern = re.compile(self.cfg["pattern"]["ra"])
        self.dec_pattern = re.compile(self.cfg["pattern"]["dec"])

        uic.loadUi(ASCOL_CLIENT_UI, self)

        self.star_matplotlib_canvas = StarMatplotlibCanvas(self.star_matplotlib_widget, width=5, height=4, dpi=100)
        self.star_matplotlib_layout.addWidget(self.star_matplotlib_canvas)

        self.limits_matplotlib_canvas = LimitsMatplotlibCanvas(self.limits_matplotlib_widget, width=5, height=4, dpi=100)
        self.limits_matplotlib_layout.addWidget(self.limits_matplotlib_canvas)

        self.restrictions_matplotlib_canvas = RestrictionsMatplotlibCanvas(self.restrictions_matplotlib_widget, width=5, height=4, dpi=100)
        self.restrictions_matplotlib_canvas.set_restrictions(self.east_restrictions, self.west_restrictions)
        self.restrictions_matplotlib_layout.addWidget(self.restrictions_matplotlib_canvas)

        self.telescope_correction_model_CB.currentIndexChanged.connect(self.telescope_correction_model_changed)

        self.object_LE.returnPressed.connect(self.load_target_from_simbad_clicked)
        self.load_target_from_simbad_BT.clicked.connect(self.load_target_from_simbad_clicked)

        self.run_ascol_BT.clicked.connect(self.run_ascol_clicked)
        self.go_ha_da_BT.clicked.connect(self.go_ha_da_clicked)
        self.go_ra_dec_BT.clicked.connect(lambda: self.run_ascol_cmd("TGRA"))
        self.send_ra_dec_BT.clicked.connect(self.send_ra_dec_clicked)
        self.autoguider_ra_minus_BT.clicked.connect(lambda: self.autoguider_offset("ra-"))
        self.autoguider_ra_plus_BT.clicked.connect(lambda: self.autoguider_offset("ra+"))
        self.autoguider_dec_minus_BT.clicked.connect(lambda: self.autoguider_offset("dec-"))
        self.autoguider_dec_plus_BT.clicked.connect(lambda: self.autoguider_offset("dec+"))
        self.user_offsets_absolute_BT.clicked.connect(self.user_offsets_absolute_clicked)
        self.user_offsets_reset_BT.clicked.connect(lambda: self.run_ascol_cmd("TSUA 0.0 0.0"))
        self.autoguider_offsets_absolute_BT.clicked.connect(self.autoguider_offsets_absolute_clicked)
        self.autoguider_offsets_reset_BT.clicked.connect(lambda: self.run_ascol_cmd("TSGA 0.0 0.0"))
        self.dome_position_BT.clicked.connect(self.dome_position_clicked)
        self.focus_position_BT.clicked.connect(self.focus_position_clicked)
        self.focus_relative_position_minus_BT.clicked.connect(lambda: self.set_focus_relative_position("-"))
        self.focus_relative_position_plus_BT.clicked.connect(lambda: self.set_focus_relative_position(""))

        self.dome_auto_BT.clicked.connect(lambda: self.run_ascol_cmd("DOAM"))
        self.dome_park_BT.clicked.connect(lambda: self.run_ascol_cmd("DOPA"))
        self.dome_stop_BT.clicked.connect(lambda: self.run_ascol_cmd("DOST"))
        self.dome_calibration_BT.clicked.connect(lambda: self.run_ascol_cmd("DOCA"))
        self.slit_close_BT.clicked.connect(lambda: self.run_ascol_cmd("DOSO 0"))
        self.slit_open_BT.clicked.connect(lambda: self.run_ascol_cmd("DOSO 1"))
        self.dome_lamp_off_BT.clicked.connect(lambda: self.run_ascol_cmd("DOLO 0"))
        self.dome_lamp_on_BT.clicked.connect(lambda: self.run_ascol_cmd("DOLO 1"))
        self.focus_stop_BT.clicked.connect(lambda: self.run_ascol_cmd("FOST"))
        self.axes_lock_BT.clicked.connect(lambda: self.run_ascol_cmd("TSAL 1 1"))
        self.axes_unlock_BT.clicked.connect(lambda: self.run_ascol_cmd("TSAL 0 0"))
        self.telescope_calibration_west_BT.clicked.connect(lambda: self.run_ascol_cmd("TESY 0"))
        self.telescope_calibration_east_BT.clicked.connect(lambda: self.run_ascol_cmd("TESY 1"))
        #self.tracking_off_BT.clicked.connect(lambda: self.run_ascol_cmd("TSGM 0"))
        #self.tracking_on_BT.clicked.connect(lambda: self.run_ascol_cmd("TSGM 1"))
        self.dec_screw_start_centering_BT.clicked.connect(lambda: self.run_ascol_cmd("TSSC"))
        self.telescope_flip_BT.clicked.connect(lambda: self.run_ascol_cmd("TEFL"))
        self.telescope_park_BT.clicked.connect(lambda: self.run_ascol_cmd("TEPA"))
        self.telescope_on_BT.clicked.connect(lambda: self.run_ascol_cmd("TEON 1"))
        self.telescope_off_BT.clicked.connect(lambda: self.run_ascol_cmd("TEON 0"))
        self.telescope_stop_BT.clicked.connect(lambda: self.run_ascol_cmd("TEST"))
        self.mirror_flap_open_BT.clicked.connect(lambda: self.run_ascol_cmd("FMOP 1"))
        self.mirror_flap_close_BT.clicked.connect(lambda: self.run_ascol_cmd("FMOP 0"))
        self.mirror_flap_stop_BT.clicked.connect(lambda: self.run_ascol_cmd("FMST"))
        self.dome_camera_power_on_BT.clicked.connect(lambda: self.run_ascol_cmd("DOCO 1"))
        self.dome_camera_power_off_BT.clicked.connect(lambda: self.run_ascol_cmd("DOCO 0"))
        self.control_voltage_on_BT.clicked.connect(lambda: self.run_ascol_cmd("GLCV 1"))
        self.control_voltage_off_BT.clicked.connect(lambda: self.run_ascol_cmd("GLCV 0"))

        self.telescope_previous_BT.clicked.connect(self.telescope_previous_clicked)
        self.telescope_next_BT.clicked.connect(self.telescope_next_clicked)
        self.coordinates_previous_BT.clicked.connect(self.coordinates_previous_clicked)
        self.coordinates_next_BT.clicked.connect(self.coordinates_next_clicked)
        self.image_previous_BT.clicked.connect(self.image_previous_clicked)
        self.image_next_BT.clicked.connect(self.image_next_clicked)

        self.coordinates_stackedWidget.setCurrentIndex(0)
        self.image_stackedWidget.setCurrentIndex(0)

        self.progress_callback_dict = {
            "read": self.progress_read_fn,
            "command": self.progress_command_fn,
        }

        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(2)

        print("Multithreading with maximum %d threads" % self.threadpool.maxThreadCount())

        self.refresh_statusbar(ClientStatus.IDLE)

        self.exit.clear()
        self.stop_event.clear()
        self.thread_exit["read"].clear()

        kwargs = {
            "command": None,
            "thread_exit": self.thread_exit["read"],
        }

        self.ascol_thread = AscolThread(self)

        read_worker = Worker(self.ascol_thread.run, **kwargs) # Any other args, kwargs are passed to the run function
        read_worker.signals.result.connect(self.ascol_result)
        read_worker.signals.finished.connect(self.ascol_finished)
        read_worker.signals.progress.connect(self.ascol_progress)
        read_worker.signals.error.connect(self.ascol_error)

        self.threadpool.start(read_worker)

        self.resize(1400, 1024)
        self.show()

    def load_cfg(self):
        self.cfg = {
            "ice_telescope": {},
            "observer": {},
            "pattern": {},
        }

        rcp = configparser.ConfigParser()
        rcp.read(ASCOL_CLIENT_CFG)

        ice_telescope_callbacks = {
            "host": rcp.get,
            "port": rcp.getint,
        }
        self.run_cfg_callbacks("ice_telescope", ice_telescope_callbacks)

        observer_callbacks = {
            "latitude": rcp.getfloat,
            "longitude": rcp.getfloat,
            "elevation": rcp.getfloat,
        }
        self.run_cfg_callbacks("observer", observer_callbacks)

        pattern_callbacks = {
            "ra": rcp.get,
            "dec": rcp.get,
        }
        self.run_cfg_callbacks("pattern", pattern_callbacks)

        for section in self.cfg:
            for key in self.cfg[section]:
                if key == "password":
                    self.logger.info("cfg.%s.%s = ****" % (section, key))
                else:
                    self.logger.info("cfg.%s.%s = %s" % (section, key, self.cfg[section][key]))

    def get_restrictions(self, filename):
        data = np.loadtxt(filename)
        x, y = zip(*data)

        return [x, y]

    def run_cfg_callbacks(self, section, callbacks):
        for key in callbacks:
            self.cfg[section][key] = callbacks[key](section, key)

    def progress_command_fn(self, data):
        dt_str = datetime.now().strftime("%H:%M:%S")

        self.log_TE.textCursor().insertHtml("<b>%s: </b>" % dt_str)
        self.log_TE.textCursor().insertHtml('<font color="#0000FF">%(command)s => %(result)s</font><br>' % data)

    def set_label_text(self, label, text, color="#CCFFCC"):
        if text in ["OFF", "UNCALIBRATED", "LOCKED", "CLOSED"]:
            color = "#FFCCCC"

        label.setText(text)
        label.setStyleSheet("background-color: %s;" % color)

    def progress_read_fn(self, data):
        #print("BEGIN progress_read_fn %s" % time.perf_counter())

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
            #"coordinates.ra",
            #"coordinates.dec",
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
            "global_state.telescope": ["OFF","STOP", "TRACK", "SLEW", "SLEWHADA", "SYNC", "PARK"],
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
            value = data
            for name in key.split("."):
                if not hasattr(value, name):
                    self.logger.error("ICE value '%s' not found (name = %s)" % (key, name))
                    continue
                value = getattr(value, name)

            widget_name = "%s_LB" % key.replace(".", "_")
            if not hasattr(self, widget_name):
                self.logger.error("QLabel '%s' not found" % widget_name)
                continue

            label = getattr(self, widget_name)

            if key == "utc":
                dt = datetime.fromtimestamp(value, tz=timezone.utc)
                value = dt.strftime("%Y-%m-%d %H:%M:%S")
                observing_time = Time(dt, location=self.earth_location)
                alt_az = AltAz(location=self.earth_location, obstime=observing_time)
                lst = observing_time.sidereal_time("mean")
                self.set_label_text(self.lst_LB, lst.to_string(sep=":"))

                ra = self.ra_pattern.search(data.coordinates.ra)
                if ra:
                    ra = ra.groupdict()
                    ra = "%(dd)sh%(mm)sm%(ss)ss" % ra
                else:
                    ra = None

                dec = self.dec_pattern.search(data.coordinates.dec)
                if dec:
                    dec = dec.groupdict()
                    dec = "%(dd)sd%(mm)sm%(ss)ss" % dec
                else:
                    dec = None

                if ra is not None and dec is not None:
                    coord = SkyCoord(ra, dec, frame="icrs", equinox="J2000")
                    c = coord.transform_to(alt_az)

                    if (time.perf_counter() - self.redraw_canvas_counter) > 30:
                        # WARNING: Velice pomale fce neni dobre volat prilis casto
                        self.star_matplotlib_canvas.plot_star(coord, observing_time, self.observer)
                        self.limits_matplotlib_canvas.plot_star(coord, observing_time, self.observer)
                        self.restrictions_matplotlib_canvas.plot_restrictions(coord, observing_time, self.observer, float(data.axes.ha), float(data.axes.da))
                        self.redraw_canvas_counter = time.perf_counter()

                    self.set_label_text(self.altitude_LB, c.alt.to_string(sep=":"))
                    self.set_label_text(self.azimuth_LB, c.az.to_string(sep=":"))
                    self.set_label_text(self.airmass_LB, "%.2f" % c.secz)
                    self.set_label_text(self.coordinates_ra_LB, coord.ra.to_string(unit=u.hour, sep=":"))
                    self.set_label_text(self.coordinates_dec_LB, coord.dec.to_string(sep=":"))

                    ha = lst - coord.ra
                    self.set_label_text(self.ha_LB, ha.to_string(sep=":"))

            suffix = ""
            if key in meteo_units:
                suffix = " %s" % meteo_units[key]

            if key in global_state2str:
                try:
                    value = global_state2str[key][value]
                except:
                    value = "UNKNOWN"

            self.set_label_text(label, "%s%s" % (value, suffix))

        status_bits2str = {
              0: ["OFF", "ON", self.remote_mode_LB],                       #  0 System is in REMOTE mode
              1: ["OFF", "ON", self.control_voltage_LB],                   #  1 Control voltage is turned on
              2: ["UNCALIBRATED", "CALIBRATED", self.ha_calibration_LB],   #  2 HA axis is calibrated
              3: ["UNCALIBRATED", "CALIBRATED", self.da_calibration_LB],   #  3 DEC axis is calibrated
              4: ["UNCALIBRATED", "CALIBRATED", self.dome_calibration_LB], #  4 Dome is calibrated
              5: ["OFF", "ON", self.correction_refraction_state_LB],       #  5 Correction of refraction is turned on
              6: ["OFF", "ON", self.correction_model_state_LB],            #  6 Correction model function is turned on
              7: ["OFF", "ON", None],                                      #  7 Guide mode is turned on
              8: ["", "MOVE", None],                                       #  8 Focusing is in move
              9: ["OFF", "ON", self.dome_lamp_LB],                         #  9 Dome light is on
              10: ["OFF", "ON", self.vent_tube_state_LB],                  # 10 Vent on tube is on
              11: ["LOCKED", "UNLOCKED", self.ha_lock_LB],                 # 11 HA axis unlocked
              12: ["LOCKED", "UNLOCKED", self.da_lock_LB],                 # 12 DEC axis unlocked
              13: ["OFF", "ON", self.dome_camera_power_LB],                # 13 Dome camera is on
        }

        for shift in range(14):
            value = (data.global_state.status_bits >> shift) & 1
            label = status_bits2str[shift][2]
            if label is not None:
                self.set_label_text(label, status_bits2str[shift][value])

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
            value = (data.global_state.error_bits >> shift) & 1
            if value:
                error_flag = True
                error_msg = error_bits2str[shift]
                errors.append(error_msg)
                self.set_label_text(self.error_msg_LB, error_msg, color="#FFCCCC")

        if error_flag:
            self.error_msg_LB.setToolTip("\n".join(errors))
        else:
            self.set_label_text(self.error_msg_LB, "Alright")

        #if "MEST" in data:
        #    value = data["MEST"]
        #    self.set_label_text(self.meteo_humidity_LB, "%i %%" % value["humidity"])
        #    self.set_label_text(self.meteo_temperature_LB, "%.1f °C" % value["temperature"])
        #    self.set_label_text(self.meteo_wind_speed_LB, "%.1f m/s" % value["wind_speed"])
        #    self.set_label_text(self.brightness_max_LB, "%.1f kLux" % value["brightness_max"])

        #print("END progress_read_fn %s" % time.perf_counter())

    def ascol_progress(self, category, data):
        if self.exit.is_set():
            return

        if category == "msg":
            self.refresh_statusbar(ClientStatus.RUNNING, data["msg"])
        elif category in self.progress_callback_dict:
            self.logger.debug("ascol_progress(category = %s, data = %s)" % (category, data))
            self.progress_callback_dict[category](data)
            self.refresh_statusbar(ClientStatus.RUNNING, category)

    def ascol_result(self, s):
        if self.exit.is_set():
            return

        self.logger.info("ascol_result = %s" % s)

    def ascol_error(self, error):
        if self.exit.is_set():
            return

        dt_str = datetime.now().strftime("%H:%M:%S")
        exctype, value, format_exc = error

        self.refresh_statusbar(ClientStatus.FAILED, "%s %s" % (exctype, value))

        self.logger.error("exctype = %s" % exctype)
        self.logger.error("value = %s" % value)
        self.logger.error("format_exc = %s" % format_exc)

        self.log_TE.textCursor().insertHtml("<b>%s: </b>" % dt_str)
        self.log_TE.textCursor().insertHtml('<font color="#FF0000">%s</font><br>' % value)

    def ascol_finished(self):

        if self.exit.is_set():
            self.logger.info("AscolThread COMPLETE! Exiting...")
            return

        if self.status != ClientStatus.FAILED:
            self.refresh_statusbar(ClientStatus.SUCCESS)

        self.logger.info("AscolThread COMPLETE!")

    def is_stop(self):

        if self.exit.is_set() or self.stop_event.is_set():
            return True

        return False

    def refresh_statusbar(self, value, msg=""):
        dt_str = datetime.now().strftime("%H:%M:%S")
        name = value.name
        self.status = value

        self.statusbar.showMessage("Status: %s %s %s" % (name, dt_str, msg))
        self.statusbar.setStyleSheet("background-color: %s;" % self.status_color[name])

    def create_ascol_command_thread(self, command):
        self.refresh_statusbar(ClientStatus.RUNNING)

        self.exit.clear()
        self.stop_event.clear()
        self.thread_exit["command"].clear()

        kwargs = {
            "command": command,
            "thread_exit": self.thread_exit["command"],
        }

        dt_str = datetime.now().strftime("%H:%M:%S")
        self.log_TE.textCursor().insertHtml("<b>%s: </b>" % dt_str)
        self.log_TE.textCursor().insertHtml('<font color="#000000">ASCOL: %s</font><br>' % command)
        self.logger.info("create_ascol_command_thread(%s)" % command)

        self.ascol_thread = AscolThread(self)

        command_worker = Worker(self.ascol_thread.run, **kwargs) # Any other args, kwargs are passed to the run function
        command_worker.signals.result.connect(self.ascol_result)
        command_worker.signals.finished.connect(self.ascol_finished)
        command_worker.signals.progress.connect(self.ascol_progress)
        command_worker.signals.error.connect(self.ascol_error)

        self.threadpool.start(command_worker)

    def telescope_next_clicked(self):
        idx = self.telescope_stackedWidget.currentIndex()
        self.telescope_stackedWidget.setCurrentIndex(idx-1)

    def telescope_previous_clicked(self):
        idx = self.telescope_stackedWidget.currentIndex()
        self.telescope_stackedWidget.setCurrentIndex(idx+1)

    def coordinates_previous_clicked(self):
        idx = self.coordinates_stackedWidget.currentIndex()
        self.coordinates_stackedWidget.setCurrentIndex(idx-1)

    def coordinates_next_clicked(self):
        idx = self.coordinates_stackedWidget.currentIndex()
        self.coordinates_stackedWidget.setCurrentIndex(idx+1)

    def image_previous_clicked(self):
        idx = self.image_stackedWidget.currentIndex()
        self.image_stackedWidget.setCurrentIndex(idx-1)

    def image_next_clicked(self):
        idx = self.image_stackedWidget.currentIndex()
        self.image_stackedWidget.setCurrentIndex(idx+1)

    def load_target_from_simbad_clicked(self):
        self.refresh_statusbar(ClientStatus.RUNNING, "Loading target from Simbad...")

        self.thread_exit["simbad"].clear()

        kwargs = {
            "thread_exit": self.thread_exit["simbad"],
            "target": self.object_LE.text(),
        }

        # WARNING: Pokud by byla instance objektu SelectTargetThread pouze jako
        # lokalni promena teto metody, tak by se ve vetsine pripadu tato instance
        # uvolnila z pameti drive nez by byla moznost zavolat jeji metody, ktere
        # jsou navazany na jednotlive udalosti.
        self.load_target_from_simbad_thread = LoadTargetFromSimbadThread(self)

        simbad_worker = Worker(self.load_target_from_simbad_thread.run, **kwargs) # Any other args, kwargs are passed to the run function
        simbad_worker.signals.result.connect(self.load_target_from_simbad_thread.result)
        simbad_worker.signals.finished.connect(self.load_target_from_simbad_thread.finished)
        simbad_worker.signals.progress.connect(self.load_target_from_simbad_thread.progress)
        simbad_worker.signals.error.connect(self.load_target_from_simbad_thread.error)

        self.threadpool.start(simbad_worker)

    def run_ascol_clicked(self):
        command = [self.ascol_LE.text()]
        self.create_ascol_command_thread(command)

    def telescope_correction_model_changed(self, idx):
        command = []
        command.append("TSCM %s" % self.telescope_correction_model_CB.currentText())

        self.create_ascol_command_thread(command)

    def send_ra_dec_clicked(self):
        ra = self.ra_LE.text()
        dec = self.dec_LE.text()

        position = 0 # east
        if self.telescope_position_CB.currentText() == "west":
            position = 1

        command = []
        command.append("TSRA %s %s %i" % (ra, dec, position))

        self.create_ascol_command_thread(command)

    def user_offsets_absolute_clicked(self):
        ra = self.user_offsets_ra_DSB.value()
        dec = self.user_offsets_dec_DSB.value()

        command = []
        command.append("TSUA %.1f %.1f" % (ra, dec))

        self.create_ascol_command_thread(command)

    def autoguider_offsets_absolute_clicked(self):
        ra = self.autoguider_offsets_ra_DSB.value()
        dec = self.autoguider_offsets_dec_DSB.value()

        command = []
        command.append("TSGA %.1f %.1f" % (ra, dec))

        self.create_ascol_command_thread(command)

    def dome_position_clicked(self):
        command = []
        command.append("DOSA %.2f" % self.dome_position_DSB.value())
        command.append("DOGA")

        self.create_ascol_command_thread(command)

    def focus_position_clicked(self):
        command = []
        command.append("FOSA %.3f" % self.focus_position_DSB.value())
        command.append("FOGA")

        self.create_ascol_command_thread(command)

    def set_focus_relative_position(self, direction):
        command = []
        command.append("FOSR %s%.3f" % (direction, self.focus_relative_position_DSB.value()))
        command.append("FOGR")

        self.create_ascol_command_thread(command)

    def run_ascol_cmd(self, cmd):
        self.create_ascol_command_thread([cmd])

    def autoguider_offset(self, action):
        ra_offset = 0.0
        dec_offset = 0.0

        if action == "ra-":
            ra_offset -= self.autoguider_offset_relative_DSB.value()
        elif action == "ra+":
            ra_offset += self.autoguider_offset_relative_DSB.value()
        elif action == "dec-":
            dec_offset -= self.autoguider_offset_relative_DSB.value()
        elif action == "dec+":
            dec_offset += self.autoguider_offset_relative_DSB.value()

        command = []
        command.append("TSGR %.2f %.2f" % (ra_offset, dec_offset))

        self.create_ascol_command_thread(command)

    def go_ha_da_clicked(self):
        ha = self.axes_ha_DSB.value()
        da = self.axes_da_DSB.value()

        command = []
        command.append("TSHA %.4f %.4f" % (ha, da))
        command.append("TGHA")

        self.create_ascol_command_thread(command)

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

def main():
    app = QApplication([])
    ascol_client_ui = ASCOLClientUI()

    return app.exec()

if __name__ == '__main__':
    main()
