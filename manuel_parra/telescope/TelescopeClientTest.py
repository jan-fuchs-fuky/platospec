import Ice
import PlatoSpec
import sys
import time
import argparse


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

    def disconnect(self):
        '''
        Disconnect from Telescope ICE server object.
        '''
        msg = 'Desconnecting from Telescope server...'
        print(msg)
        if self.communicator:
            try:
                self.communicator.destroy()
            except:
                print('Unknown execption...')

    def initialize(self):
        '''
        Telescope initialization sequence using ASCOL software.
        '''
        msg = 'Starting TCS initialize procedure'
        print(msg)

        try:
            # Dome Slit Open
            result = self.telescope_proxy.run_ascol('DOSO 1\r\n')
            msg = 'Execute Dome Slit Open, result: %s' % str(result)
            print(msg)
            if 'ERR' in result:
                msg = 'Fail during Dome Slit Open'
                print(msg)

                return False

            # Dome Automated
            result = self.telescope_proxy.run_ascol('DOAM\r\n')
            msg = 'Execute Dome Automated, result: %s' % str(result)
            print(msg)
            if 'ERR' in result:
                msg = 'Fail during Dome Automated'
                print(msg)

                return False

            # Telescope Synchronization East
            result = self.telescope_proxy.run_ascol('TESY 1\r\n')
            msg = 'Execute Telescope Synchronization East, result: %s' % str(
                result)
            print(msg)
            if 'ERR' in result:
                msg = 'Fail during Telescope Synchronization East'
                print(msg)

                return False

            msg = 'TCS initialize procedure is ready'
            print(msg)

            return True
        except:
            print('Unknown execption...')

    def start_tracking_source(self, ra, dec):
        '''
        Send telescope to right ascension and declination coordinates and 
        enable the tracking using ASCOL software.
        '''
        msg = 'Starting TCS tracking to RA: %s DEC: %s' % (ra, dec)
        print(msg)

        try:
            # Telescope set RA/DEC East
            cmd = 'TSRA %s %s 0\r\n' % (ra, dec)
            result = self.telescope_proxy.run_ascol(cmd)
            msg = 'Execute Telescope set RA/DEC East, result: %s' % str(result)
            print(msg)
            if 'ERR' in result:
                msg = 'Fail during Telescope set RA/DEC East'
                print(msg)

                return False

            # Telescope go RA/DEC
            result = self.telescope_proxy.run_ascol('TGRA\r\n')
            msg = 'Execute Telescope go RA/DEC, result: %s' % str(result)
            print(msg)
            if 'ERR' in result:
                msg = 'Fail during Telescope go RA/DEC'
                print(msg)

                return False

            # Telescope set Guiding Mode On
            result = self.telescope_proxy.run_ascol('TSGM 1\r\n')
            msg = 'Execute Telescope set Guiding Mode On, result: %s' % str(
                result)
            print(msg)
            if 'ERR' in result:
                msg = 'Fail during Telescope set Guiding Mode On'
                print(msg)

                return False

            msg = 'TCS start tracking source procedure is ready'
            print(msg)

            return True
        except:
            print('Unknown execption...')

    def stop_tracking_source(self):
        '''
        Stop source tracking using ASCOL software.
        '''
        msg = 'Starting TCS stop tracking source procedure'
        print(msg)

        try:
            # Telescope set Guiding Mode Off
            result = self.telescope_proxy.run_ascol('TSGM 0\r\n')
            msg = 'Execute Telescope set Guiding Mode Off, result: %s' % str(
                result)
            print(msg)
            if 'ERR' in result:
                msg = 'Fail during Telescope set Guiding Mode Off'
                print(msg)

                return False

            # Telescope stop
            result = self.telescope_proxy.run_ascol('TEST\r\n')
            msg = 'Execute Telescope Stop, result: %s' % str(result)
            print(msg)
            if 'ERR' in result:
                msg = 'Fail during Telescope Stop'
                print(msg)

                return False

            msg = 'TCS stop tracking source procedure is ready'
            print(msg)

            return True
        except:
            print('Unknown execption...')

    def shutdown(self):
        '''
        Telescope shutdown sequence using ASCOL software.
        '''
        msg = 'Starting TCS shutdown procedure'
        print(msg)

        try:
            # Telescope stop
            result = self.telescope_proxy.run_ascol('TEST\r\n')
            msg = 'Execute Telescope Stop, result: %s' % str(result)
            print(msg)
            if 'ERR' in result:
                msg = 'Fail during Telescope Stop'
                print(msg)

                return False

            # Telescope park
            result = self.telescope_proxy.run_ascol('TEPA\r\n')
            msg = 'Execute Telescope Park, result: %s' % str(result)
            print(msg)
            if 'ERR' in result:
                msg = 'Fail during Telescope Park'
                print(msg)

                return False

            # Dome Park
            result = self.telescope_proxy.run_ascol('DOPA\r\n')
            msg = 'Execute Dome Park, result: %s' % str(result)
            print(msg)
            if 'ERR' in result:
                msg = 'Fail during Dome Park'
                print(msg)

                return False

            # Dome Slit Close
            result = self.telescope_proxy.run_ascol('DOSO 0\r\n')
            msg = 'Execute Dome Slit Close, result: %s' % str(result)
            print(msg)
            if 'ERR' in result:
                msg = 'Fail during Dome Slit Close'
                print(msg)

                return False

            msg = 'TCS shutdown procedure is ready'
            print(msg)

            return True
        except:
            print('Unknown execption...')

    def get_telescope_status(self):
        '''
        Return Telescope RA/DEC position.
        '''
        telescope_status = self.telescope_proxy.get_status()
        coordinates = telescope_status.coordinates

        result = {}
        result['ra'] = coordinates.ra
        result['dec'] = coordinates.dec
        result['position'] = coordinates.position

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
    msg = 'Telescope initial status: %s' % str(telescope_status)
    print(msg)

    '''
    msg = 'Initialize telescope and track the MOON'
    print(msg)
    client.initialize()
    client.start_tracking_source('164742.3', '362837.9')

    time.sleep(60.0)

    msg = 'Reading Telescope status'
    print(msg)

    telescope_status = client.get_telescope_status()
    msg = 'Telescope initial status: %s' % str(telescope_status)
    print(msg)

    weather_status = client.get_weather_status()
    msg = 'Wheather initial status: %s' % str(weather_status)
    print(msg)

    time.sleep(60.0)

    msg = 'Stop source tracking and Shutdown telescope'
    print(msg)
    client.stop_tracking_source()
    client.shutdown()

    telescope_status = client.get_telescope_status()
    msg = 'Telescope initial status: %s' % str(telescope_status)
    print(msg)
    '''

    client.disconnect()
