#! /usr/bin/env python3
# -*- coding: utf-8 -*-

#
# Author: Jan Fuchs <fuky@asu.cas.cz>
#
# Copyright (C) 2022 Astronomical Institute, Academy Sciences of the Czech Republic, v.v.i.
#
# ICE_CONFIG=/home/fuky/git/github/platospec/telescope/etc/ice_client.cfg ./ascol_client_cli.py
#

import os
import sys
import Ice

SCRIPT_PATH = os.path.dirname(os.path.realpath(os.path.abspath(__file__)))
sys.path.append(SCRIPT_PATH)
sys.path.append("%s/../python" % SCRIPT_PATH)

import PlatoSpec

class ASCOLClientCLI:

    def __init__(self):
        self.cfg = {
            "ice_telescope": {
                "host": "localhost",
                "port": 9999,
            }
        }

        with Ice.initialize(sys.argv) as communicator:
            base = communicator.stringToProxy("Telescope:default -h %(host)s -p %(port)i" % self.cfg["ice_telescope"])
            self.telescope_proxy = PlatoSpec.TelescopePrx.checkedCast(base)
            if not self.telescope_proxy:
                raise RuntimeError("Invalid proxy")

            status = self.telescope_proxy.get_status()
            print(status)

            result = self.telescope_proxy.run_ascol("DOSO 1")
            print("Dome Slit Open", result)

            result = self.telescope_proxy.run_ascol("TESY 1")
            print("Start east calibration procedures", result)

            result = self.telescope_proxy.run_ascol("TSRA 120101.1 455959.9 0")
            print("Set sky coordinates setpoint", result)
            result = self.telescope_proxy.run_ascol("TGRA")
            print("Move to the sky coordinates setpoint", result)

            result = self.telescope_proxy.run_ascol("TSGM 1")
            print("Turn on guiding mode", result)

def main():
    ascol_client_cli = ASCOLClientCLI()

if __name__ == '__main__':
    main()
