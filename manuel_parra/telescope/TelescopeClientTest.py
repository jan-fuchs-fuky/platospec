import Ice
import PlatoSpec
import sys
import time
import json
import argparse
import traceback

from datetime import datetime, timezone

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

    def initialize(self):
        '''
        Telescope initialization sequence using ASCOL software.
        '''
        msg = 'Starting TCS initialize procedure'
        print(msg)

        try:
            self.run_ascol('GLCV 1', 'Control Voltage ON')
            self.wait('control_voltage', 'ON')
            self.wait('error_flag', 'OFF')

            self.run_ascol('TEON 1', 'Telescope ON')
            self.wait('global_state.telescope', 'OFF', negate=True)

            self.run_ascol('DOSO 1', 'Dome Slit Open')
            self.wait('global_state.slit', 'OPENED')

            self.run_ascol('DOAM', 'Dome Automated')
            self.run_ascol('FMOP 1', 'Flap Mirror Open')
            self.run_ascol('TSCM 4', 'Set correction model to 4')
            self.run_ascol('TESY 0', 'Telescope Synchronization West')

            required_state = [
                ['global_state.dome', 'AUTO_'],
                ['global_state.mirror_cover', 'OPENED'],
                ['correction_model', '4'],
                ['ha_calibration', 'CALIBRATED'],
                ['da_calibration', 'CALIBRATED'],
            ]

            for key, value in required_state:
                self.wait(key, value)

            msg = 'TCS initialize procedure is ready'
            print(msg)

            return True
        except:
            print('Unknown execption...')
            traceback.print_exc()

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

    def shutdown(self):
        '''
        Telescope shutdown sequence using ASCOL software.
        '''
        msg = 'Starting TCS shutdown procedure'
        print(msg)

        try:
            self.run_ascol('TEPA', 'Telescope Park')

            self.run_ascol('FMOP 0', 'Flap Mirror Close')
            self.wait('global_state.mirror_cover', 'CLOSED')

            self.run_ascol('DOSO 0', 'Dome Slit Close')
            self.wait('global_state.slit', 'CLOSED')

            self.run_ascol('DOPA', 'Dome Park')

            required_state = [
                ['global_state.telescope', 'OFF'],
                ['global_state.dome', 'STOP'],
            ]

            for key, value in required_state:
                self.wait(key, value)

            self.run_ascol('GLCV 0', 'Control Voltage OFF')
            self.wait('control_voltage', 'OFF')

            msg = 'TCS shutdown procedure is ready'
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config',
                        required=True,
                        help='Telescope server/client configuration file.')
    args = parser.parse_args()

    client = TelescopeClient()
    client.connect(args.config)

    msg = 'Reading Telescope initial status'
    print(msg)

    telescope_status = client.get_telescope_status()
    msg = 'Telescope initial status:'
    print(msg)
    print(json.dumps(telescope_status, indent=4, default=str))

    msg = 'Initialize telescope and track the MOON'
    print(msg)
    client.initialize()
    client.start_tracking_source('101000.0', '-285400.0')

    time.sleep(10.0)

    msg = 'Reading Telescope status'
    print(msg)

    telescope_status = client.get_telescope_status()
    msg = 'Telescope initial status: %s' % str(telescope_status)
    print(msg)
    print(json.dumps(telescope_status, indent=4, default=str))

    weather_status = client.get_weather_status()
    msg = 'Wheather initial status: %s' % str(weather_status)
    print(msg)

    time.sleep(10.0)

    msg = 'Stop source tracking and Shutdown telescope'
    print(msg)
    client.stop_tracking_source()
    client.shutdown()

    telescope_status = client.get_telescope_status()
    msg = 'Telescope initial status: %s' % str(telescope_status)
    print(msg)
    print(json.dumps(telescope_status, indent=4, default=str))

    client.disconnect()
