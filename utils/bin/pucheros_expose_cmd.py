#! /usr/bin/env python3
# -*- coding: utf-8 -*-

#
# Author: Jan Fuchs <fuky@asu.cas.cz>
#
# Copyright (C) 2022 Astronomical Institute, Academy Sciences of the Czech Republic, v.v.i.
#
# Example:
#
#     $ pucheros_expose_cmd.py "Au mic" 300 25 30
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

import sys
import requests
import time

class PucherosExpose:

    def __init__(self, target, target_exptime, comp_exptime, count):
        self.server = "http://192.168.224.115:5000"

        self.run_comp(comp_exptime)

        for idx in range(1, count+1):
            print("%i. Start target %s %i seconds" % (idx, target, target_exptime))
            self.run_science(target_exptime, target)
            print("%i. Start comp %i seconds" % (idx, comp_exptime))
            self.run_comp(comp_exptime)
            time.sleep(1)

        #self.run_flat(10)
        #self.run_comp(25)
        #self.run_science(10, "test")

    def run_action(self, action, params):
        url = "%s/%s" % (self.server, action)
        response = requests.post(url, json=params)

        print("%s => %i" % (action, response.status_code))
        print(params)

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

def main():
    if len(sys.argv) != 5:
        print("Usage: %s TARGET EXPTIME COMP_EXPTIME COUNT" % sys.argv[0])
        sys.exit()

    target, target_exptime, comp_exptime, count = sys.argv[1:]

    pucheros_expose = PucherosExpose(target, int(target_exptime), int(comp_exptime), int(count))

if __name__ == '__main__':
    main()
