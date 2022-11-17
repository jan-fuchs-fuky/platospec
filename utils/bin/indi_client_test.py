#! /usr/bin/env python3
# -*- coding: utf-8 -*-

#
# Author: Jan Fuchs <fuky@asu.cas.cz>
#
# Copyright (C) 2022 Astronomical Institute, Academy Sciences of the Czech Republic, v.v.i.
#

import os
import sys
sys.path.append("%s/lib/python3/dist-packages" % os.path.expanduser("~"))

import PyIndi
import time
import math

class IndiClient(PyIndi.BaseClient):

    def __init__(self):
        super(IndiClient, self).__init__()

    def newDevice(self, d):
        print("New device %s" % d.getDeviceName())

    def newProperty(self, p):
        #print("New property %s for device %s (getSwitch() => %s)" % (p.getName(), p.getDeviceName(), p.getSwitch()))
        pass

    def removeProperty(self, p):
        pass

    def newBLOB(self, bp):
        print("new BLOB ", bp.name)

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

class IndiClientTest:

    def __init__(self):
        self.indiclient = IndiClient()
        self.indiclient.setServer("192.168.224.116", 7624)

        if not self.indiclient.connectServer():
            raise Exception("No indiserver running on %s:%i" % (self.indiclient.getHost(), self.indiclient.getPort()))

        ccd = "QHY CCD QHY5LII-M-60b7e"
        self.device_ccd = self.indiclient.getDevice(ccd)
        for i in range(5):
            if self.device_ccd:
                break
            print("Waiting on CCD...")
            time.sleep(1)
            self.device_ccd = self.indiclient.getDevice(ccd)
        else:
            raise Exception("%s not found" % ccd)

        ccd_connect = self.device_ccd.getSwitch("CONNECTION")
        for i in range(10):
            if ccd_connect:
                break
            print("Waiting on CONNECTION...")
            time.sleep(0.5)
            ccd_connect = self.device_ccd.getSwitch("CONNECTION")
        else:
            raise Exception("CONNECTION failed")

        if not self.device_ccd.isConnected():
            ccd_connect[0].s = PyIndi.ISS_ON  # the "CONNECT" switch
            ccd_connect[1].s = PyIndi.ISS_OFF # the "DISCONNECT" switch
            self.indiclient.sendNewSwitch(ccd_connect)

        ccd_gain = self.get_number("CCD_GAIN")
        ccd_gain[0].value = 15
        self.indiclient.sendNewNumber(ccd_gain)
        print("Set CCD_GAIN to %i" % ccd_gain[0].value)
        time.sleep(1)

        ccd_exposure = self.get_number("CCD_EXPOSURE")
        ccd_exposure[0].value = 10
        self.indiclient.sendNewNumber(ccd_exposure)
        print("Set CCD_EXPOSURE to %.2f seconds and sleep 2 seconds" % ccd_exposure[0].value)
        time.sleep(2)

        for i in range(30):
            ccd_exposure = self.get_number("CCD_EXPOSURE")
            if math.isclose(ccd_exposure[0].value, 0.0):
                print("Expose success")
                break

            print("Exposing...")
            time.sleep(1)

    def get_number(self, name):
        number = self.device_ccd.getNumber(name)
        for i in range(10):
            if number:
                break
            print("Waiting on number %s..." % name)
            time.sleep(0.5)
            number = self.device_ccd.getNumber(name)
        else:
            raise Exception("Get %s failed" % name)

        print("%s = %.2f" % (name, number[0].value))

        return number

def main():
    print("PyIndi.INDIV = %s" % PyIndi.INDIV)
    print("PyIndi.INDI_VERSION = %i.%i.%i" % (PyIndi.INDI_VERSION_MAJOR, PyIndi.INDI_VERSION_MINOR, PyIndi.INDI_VERSION_RELEASE))

    indi_client_test = IndiClientTest()

if __name__ == '__main__':
    main()
