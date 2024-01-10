#! /usr/bin/env python3
# -*- coding: utf-8 -*-

#
# Author: Jan Fuchs <fuky@asu.cas.cz>
#
# Copyright (C) 2022 Astronomical Institute, Academy Sciences of the Czech Republic, v.v.i.
#
# GLCV (GLobal Control Voltage control)
# GLVE (Global Version)
# GLLG (Global LoGin)
# GLLL (GLobal read Latitude and Longitude)
# GLUT (GLobal read UTc)
# GLSD (GLobal read SiDereal time)
# GLDP (GLobal DePartment)
# GLVT (GLobal Vent Tube control)
# GLST (Global STate)
# TEON (TElescope ON/off)
# TEST (TElescope STop)
# TEFL (Telescope FLip)
# TEPA (TElescope PArk)
# TESY (TElescope SYnchronization)
# TSRA (Telescope Set Right ascension and declination Absolute)
# TSHA (Telescope Set Hour and declination axis Absolute)
# TGRA (Telescope Go Right ascension and declination Absolute)
# TGHA (Telescope Go Hour and declination axis Absolute)
# TSCM (Telescope Set Correction of telescope Model)
# TRCM (Telescope Read Correction of telescope Model)
# TSGM (Telescope Set Guiding Mode)
# TSUS (Telescope Set User Speeds)
# TEUS (TElescope User Speeds on/off)
# TSUA (Telescope Set User offsets Absolute)
# TSUR (Telescope Set User offsets Relative)
# TSGA (Telescope Set autoGuider offsets Absolute)
# TSGR (Telescope Set autoGuider offsets Relative)
# TRUO (Telescope Read User Offsets)
# TRGO (Telescope Read autoGuider Offsets)
# TSS1 (Telescope Set Speed 1)
# TSS2 (Telescope Set Speed 2)
# TSS3 (Telescope Set Speed 3)
# TRUS (Telescope Read User Speeds)
# TRS1 (Telescope Read Speed 1)
# TRS2 (Telescope Read Speed 2)
# TRS3 (Telescope Read Speed 3)
# TRRD (Telescope Read Right ascension and Declination)
# TRSP (Telescope Read sky Set Point)
# TRHD (Telescope Read Hour and Declination axis angle)
# TSAL (Telescope Set Axis Lock)
# TRSD (Telescope Read dec Screw Distance)
# TSSC (Telescope Start dec Screw Centering)
# DOSA (DOme Set Absolute position)
# DOGA (DOme Go Absolute position)
# DOAM (DOme AutoMated)
# DOPA (DOme PArk)
# DOCA (DOme CAlibration)
# DOSO (DOme Slit Open/close)
# DOST (DOme STop)
# DOPO (DOme read absolute POsition)
# DOLO (DOme Lamp On/off)
# FMOP (Flap Mirror OPen/close)
# FMST (Flap Mirror STop)
# FOSA (FOcus Set Absolute position)
# FOSR (FOcus Set Relative position)
# FOGA (FOcus Go Absolute Position)
# FOGR (FOcus Go Relative Position)
# FOST (FOcus STop)
# FOPO (FOcus read absolute Position)
# MEST (MEteo STatus)

import os
import sys
import logging
import socketserver
import traceback

from astropy.time import Time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

SCRIPT_PATH = os.path.dirname(os.path.realpath(os.path.abspath(__file__)))
sys.path.append(SCRIPT_PATH)

ASCOL_SIMULATOR_LOG = "%s/../log/ascol_simulator.log" % SCRIPT_PATH

def init_logger(logger, filename):
    formatter = logging.Formatter("%(asctime)s - %(name)s[%(process)d] - %(levelname)s - %(message)s")

    fh = RotatingFileHandler(filename, maxBytes=1048576, backupCount=10)
    #fh.setLevel(logging.INFO)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)

    #logger.setLevel(logging.INFO)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(fh)

class AscolState:

    def __init__(self, logger):
        self.logger = logger

        self.password = "123456"
        self.ra = "171436.983"
        self.dec = "-291600.57"
        self.position = "0"
        self.voltage = 0
        self.power = 0
        self.correction_model = 1
        self.setpoint_ra = self.ra
        self.setpoint_dec = self.dec
        self.setpoint_position = self.position
        self.ha = "67.8901"
        self.da = "65.4321"
        self.mechanical_setpoint_ha = self.ha
        self.mechanical_setpoint_da = self.da
        self.model = "1"
        self.user_speed_ra = "125.18945"
        self.user_speed_dec = "-53.26874"
        self.user_speed_enabled = "1"
        self.user_offset_absolute_ra = "1.1"
        self.user_offset_absolute_dec = "2.2"
        self.autoguider_offset_absolute_ra = "1.1"
        self.autoguider_offset_absolute_dec = "2.2"
        self.speed1 = "4000.01"
        self.speed2 = "120.00"
        self.speed3 = "10.00"
        self.dome_position = "65.43"
        self.required_dome_position = self.dome_position
        self.slit_position = "0"
        self.focus_position = "5.678"
        self.required_focus_position = self.focus_position
        self.required_relative_focus_position = "-4.321"

        # status_bits
        self.dome_camera_power = 0

    def run_cmd(self, cmd_args):
        result = None
        cmd, *args = cmd_args.strip().split(" ")

        try:
            cmd_callback = getattr(self, "cmd_%s" % cmd.lower())
            if not callable(cmd_callback):
                raise Exception("%s is not callable" % cmd_callback)

            result = cmd_callback(*args)
        except:
            self.logger.exception("run_cmd() exception")

        if result is None:
            return "ERR\r\n"

        return "%s\r\n" % result

    # GLVE (Global Version)
    def cmd_glve(self):
        return "2 0 29"

    # GLLG (Global LoGin)
    def cmd_gllg(self, password):
        if password == self.password:
            return "1"

        return "0"

    # GLLL (GLobal read Latitude and Longitude)
    def cmd_glll(self):
        return "-254665.08 -105346.80"

    # GLUT (GLobal read UTc)
    def cmd_glut(self):
        dt = datetime.now(tz=timezone.utc)
        mjd_date_time = Time(dt, scale="utc").to_value(format="mjd")
        mjd_date_str = str(mjd_date_time).split(".")[0]

        return "%s %s" % (mjd_date_str, dt.strftime("%H%M%S.%f"))

    # GLSD (GLobal read SiDereal time)
    def cmd_glsd(self):
        return "912605.96"

    # GLDP (GLobal DePartment)
    def cmd_gldp(self):
        return "PS"

    # GLVT (GLobal Vent Tube control)
    def cmd_glvt(self):
        return "1"

    # GLST (Global STate)
    def cmd_glst(self):
        status_bits_values = [
            0, # 0
            0, # 1
            0, # 2
            0, # 3
            0, # 4
            0, # 5
            0, # 6
            0, # 7
            0, # 8
            0, # 9
            0, # 10
            0, # 11
            0, # 12
            self.dome_camera_power, # 13
        ]

        status_bits = 0
        for shift in range(14):
            status_bits += status_bits_values[shift] << shift

        return "0 0 4 4 0 %i 4628" % status_bits

    # TSCM (TElescope Set Correction of telescope Model)
    def cmd_tscm(self, model):
        self.correction_model = model
        return "1"

    # TRCM (Telescope Read Correction of telescope Model)
    def cmd_trcm(self):
        return self.correction_model

    # GLCV (GLobal Control Voltage control)
    def cmd_glcv(self, voltage):
        self.voltage = voltage
        return voltage

    # TEON (TElescope ON/off)
    def cmd_teon(self, power):
        self.power = power
        return power

    # TEST (TElescope STop)
    def cmd_test(self):
        return "1"

    # TEFL (Telescope FLip)
    def cmd_tefl(self):
        return "1"

    # TEPA (TElescope PArk)
    def cmd_tepa(self):
        return "1"

    # TESY (TElescope SYnchronization)
    def cmd_tesy(self, position):
        return "1"

    # TSRA (Telescope Set Right ascension and declination Absolute)
    def cmd_tsra(self, ra, dec, position):
        self.setpoint_ra = ra
        self.setpoint_dec = dec
        self.setpoint_position = position
        return "1"

    # TSHA (Telescope Set Hour and declination axis Absolute)
    def cmd_tsha(self, ha, da):
        self.mechanical_setpoint_ha = ha
        self.mechanical_setpoint_da = da
        return "1"

    # TGRA (Telescope Go Right ascension and declination Absolute)
    def cmd_tgra(self):
        self.ra = self.setpoint_ra
        self.dec = self.setpoint_dec
        self.position = self.setpoint_position
        return "1"

    # TGHA (Telescope Go Hour and declination axis Absolute)
    def cmd_tgha(self):
        self.ha = self.mechanical_setpoint_ha
        self.da = self.mechanical_setpoint_da
        return "1"

    # TSGM (Telescope Set Guiding Mode)
    def cmd_tsgm(self, enabled):
        return "1"

    # TSUS (Telescope Set User Speeds)
    def cmd_tsus(self, speed_ra, speed_dec):
        self.user_speed_ra = speed_ra
        self.user_speed_dec = speed_dec
        return "1"

    # TEUS (TElescope User Speeds on/off)
    def cmd_teus(self, enabled):
        self.user_speed_enabled = enabled
        return "1"

    # TSUA (Telescope Set User offsets Absolute)
    def cmd_tsua(self, offset_ra, offsets_dec):
        self.user_offset_absolute_ra = offset_ra
        self.user_offset_absolute_dec = offsets_dec
        return "1"

    # TSUR (Telescope Set User offsets Relative)
    def cmd_tsur(self, offset_ra, offsets_dec):
        self.user_offset_absolute_ra += offset_ra
        self.user_offset_absolute_dec += offsets_dec
        return "1"

    # TSGA (Telescope Set autoGuider offsets Absolute)
    def cmd_tsga(self, offset_ra, offsets_dec):
        self.autoguider_offset_absolute_ra = offset_ra
        self.autoguider_offset_absolute_dec = offsets_dec
        return "1"

    # TSGR (Telescope Set autoGuider offsets Relative)
    def cmd_tsgr(self, offset_ra, offsets_dec):
        self.autoguider_offset_absolute_ra += offset_ra
        self.autoguider_offset_absolute_dec += offsets_dec
        return "1"

    # TRUO (Telescope Read User Offsets)
    def cmd_truo(self):
        return "%s %s" % (self.user_offset_absolute_ra, self.user_offset_absolute_dec)

    # TRGO (Telescope Read autoGuider Offsets)
    def cmd_trgo(self):
        return "%s %s" % (self.autoguider_offset_absolute_ra, self.autoguider_offset_absolute_dec)

    # TSS1 (Telescope Set Speed 1)
    def cmd_tss1(self, speed):
        self.speed1 = speed
        return "1"

    # TSS2 (Telescope Set Speed 2)
    def cmd_tss2(self, speed):
        self.speed2 = speed
        return "1"

    # TSS3 (Telescope Set Speed 3)
    def cmd_tss3(self, speed):
        self.speed3 = speed
        return "1"

    # TRUS (Telescope Read User Speeds)
    def cmd_trus(self):
        return "%s %s %s" % (self.user_speed_ra, self.user_speed_dec, self.user_speed_enabled)

    # TRS1 (Telescope Read Speed 1)
    def cmd_trs1(self):
        return self.speed1

    # TRS2 (Telescope Read Speed 2)
    def cmd_trs2(self):
        return self.speed2

    # TRS3 (Telescope Read Speed 3)
    def cmd_trs3(self):
        return self.speed3

    # TRRD (Telescope Read Right ascension and Declination)
    def cmd_trrd(self):
        return "%s %s %s" % (self.ra, self.dec, self.position)

    # TRSP (Telescope Read sky Set Point)
    def cmd_trsp(self):
        return "%s %s %s" % (self.setpoint_ra, self.setpoint_dec, self.setpoint_position)

    # TRHD (Telescope Read Hour and Declination axis angle)
    def cmd_trhd(self):
        return "%s %s" % (self.ha, self.da)

    # TSAL (Telescope Set Axis Lock)
    def cmd_tsal(self, ha_lock, dec_lock):
        return "1"

    # TRSD (Telescope Read dec Screw Distance)
    def cmd_trsd(self):
        return "07200.12"

    # TSSC (Telescope Start dec Screw Centering)
    def cmd_tssc(self):
        return "1"

    # DOSA (DOme Set Absolute position)
    def cmd_dosa(self, position):
        self.prepared_dome_position = position
        return "1"

    # DOGA (DOme Go Absolute position)
    def cmd_doga(self):
        self.dome_position = self.prepared_dome_position
        return "1"

    # DOAM (DOme AutoMated)
    def cmd_doam(self):
        return "1"

    # DOPA (DOme PArk)
    def cmd_dopa(self):
        return "1"

    # DOCA (DOme CAlibration)
    def cmd_doca(self):
        return "1"

    # DOSO (DOme Slit Open/close)
    def cmd_doso(self, position):
        self.slit_position = position
        return "1"

    # DOST (DOme STop)
    def cmd_dost(self):
        return "1"

    # DOPO (DOme read absolute POsition)
    def cmd_dopo(self):
        return self.dome_position

    # DOLO (DOme Lamp On/off)
    def cmd_dolo(self, power):
        return "1"

    # DOCO (DOme Camera On/off)
    def cmd_doco(self, power):
        self.dome_camera_power = int(power)
        return "1"

    # FMOP (Flap Mirror OPen/close)
    def cmd_fmop(self, position):
        return "1"

    # FMST (Flap Mirror STop)
    def cmd_fmst(self):
        return "1"

    # FOSA (FOcus Set Absolute position)
    def cmd_fosa(self, position):
        self.required_focus_position = position
        return "1"

    # FOSR (FOcus Set Relative position)
    def cmd_fosr(self, position):
        self.required_relative_focus_position = position
        return "1"

    # FOGA (FOcus Go Absolute Position)
    def cmd_foga(self):
        self.focus_position = self.required_focus_position
        return "1"

    # FOGR (FOcus Go Relative Position)
    def cmd_fogr(self):
        self.focus_position += self.required_relative_focus_position
        return "1"

    # FOST (FOcus STop)
    def cmd_fost(self):
        return "1"

    # FOPO (FOcus read absolute Position)
    def cmd_fopo(self):
        return self.focus_position

    # MEST (MEteo STatus)
    def cmd_mest(self):
        return "24644.0 106257.0 90714.0 25448.0 106257.0 016 017.4 002.2 254 0 0771.40 -0152.60 4095 2"

class AscolTCPHandler(socketserver.BaseRequestHandler):

    def __init__(self, request, client_address, server):
        super(AscolTCPHandler, self).__init__(request, client_address, server)

    def handle(self):
        logger = self.server.logger
        ascol_state = self.server.get_ascol_state()
        exit = False

        while not exit:
            try:
                cmd = self.request.recv(1024).strip().decode("ascii")
                response = ascol_state.run_cmd(cmd)
                logger.info("%s: %s => %s" % (self.client_address[0], cmd, response))
            except:
                exit = True
                response = "ERR\r\n"
                logger.exception("AscolTCPHandler exception")

            self.request.sendall(response.encode("ascii"))

class AscolTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

    def __init__(self, logger, server_address, RequestHandlerClass):
        super(AscolTCPServer, self).__init__(server_address, RequestHandlerClass)
        self.logger = logger
        self.ascol_state = AscolState(logger)

    def get_ascol_state(self):
        return self.ascol_state

class AscolSimulator:

    def __init__(self, logger):
        HOST, PORT = "localhost", 2000
        self.logger = logger
        self.logger.info("Starting process 'ascol_simulator'")

        with AscolTCPServer(logger, (HOST, PORT), AscolTCPHandler) as server:
            server.serve_forever()

def main():
    logger = logging.getLogger("ascol_simulator")
    init_logger(logger, ASCOL_SIMULATOR_LOG)

    AscolSimulator(logger)

if __name__ == '__main__':
    main()
