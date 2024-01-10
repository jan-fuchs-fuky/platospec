#! /usr/bin/env python3
# -*- coding: utf-8 -*-

#
# Author: Jan Fuchs <fuky@asu.cas.cz>
#
# Copyright (C) 2021-2022 Astronomical Institute, Academy Sciences of the Czech Republic, v.v.i.
#
# $ fits2video.py -i /data/allsky/images -o /data/allsky/fresh/videos --force --actual 30 --fps 6
# $ fits2video.py -i /data/allsky/images -o /data/allsky/fresh/videos --force --actual 120 --fps 24
# $ fits2video.py -i /data/allsky/images -o /data/allsky/fresh/videos --force --actual 360 --fps 30
#
# $ crontab -e
# */5 0-13,15-23 * * * /opt/bin/fits2video.py -i /data/allsky/images -o /data/allsky/fresh/videos --force --actual 30 --fps 6
# 1,6,11,16,21,26,31,36,41,46,51,56 0-13,15-23 * * * /opt/bin/fits2video.py -i /data/allsky/images -o /data/allsky/fresh/videos --force --actual 120 --fps 24
# 2,17,32,47 0-13,15-23 * * * /opt/bin/fits2video.py -i /data/allsky/images -o /data/allsky/fresh/videos --force --actual 360 --fps 30
#
# $ fits2video.py -i /data/allsky/images -o /data/allsky/lst --make-lst -b 2020-04-13 -e 2021-12-18
#
# $ export OPENCV_LOG_LEVEL=DEBUG
# $ export OPENCV_VIDEOIO_DEBUG=1
#

import re
import os
import sys
import argparse
import logging
import errno
import cv2
import shutil
import numpy as np

from glob import glob
from astropy.io import fits
from skimage.util import img_as_ubyte
from datetime import datetime, timedelta

logging_level = logging.INFO
if __debug__:
    logging_level = logging.DEBUG

logging.basicConfig(stream=sys.stderr, level=logging_level)
logging.debug("HELP - Disable DEBUG output: python3 -O %s" % sys.argv[0])

def create_argument_parser():

    parser = argparse.ArgumentParser(
        description="Fits2Video.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="")

    parser.add_argument("-i", "--input-dir", type=str, default="/data/allsky/images", metavar="DIRECTORY",
                        help="Input DIRECTORY with *.fit.")

    parser.add_argument("-o", "--output-dir", type=str, default="/data/allsky/videos", metavar="DIRECTORY",
                        help="Output DIRECTORY for *.mp4.")

    parser.add_argument("-b", "--begin-date", type=str, metavar="YYYY-MM-DD",
                        help="Begin date YYYY-MM-DD.")

    parser.add_argument("-e", "--end-date", type=str, metavar="YYYY-MM-DD",
                        help="End date YYYY-MM-DD.")

    parser.add_argument("-a", "--actual", type=int, metavar="N",
                        help="Make video from last N fits.")

    parser.add_argument("--fps", default=30, type=int, metavar="VALUE",
                        help="Set FPS to VALUE.")

    parser.add_argument("-f", "--force", action="store_true",
                        help="Enable rewrite output file.")

    parser.add_argument("--make-lst", action="store_true",
                        help="Generate fits.lst from *.fit[.fz].")

    parser.add_argument("--convert-png", action="store_true",
                        help="Convert *.png to *.mp4.")

    return parser

def mkdir_p(path):
    """ 'mkdir -p' in Python """
    try:
        os.makedirs(path)
    except OSError as exc: # Python >2.5
        if (exc.errno == errno.EEXIST) and os.path.isdir(path):
            pass
        else:
            raise

class Fits2Video:

    def __init__(self, args):
        self.args = args
        self.begin_date = None
        self.end_date = None

        if self.args.begin_date:
            self.begin_date = datetime.strptime(self.args.begin_date, "%Y-%m-%d")

        if self.args.end_date:
            self.end_date = datetime.strptime(self.args.end_date, "%Y-%m-%d")

        # /data/allsky/images/2021/11/16/
        YYYY_MM_DD_PATTERN_STR = (
            "^.*/(?P<year>[0-9]{4})/"
            "(?P<month>[0-9]{2})/"
            "(?P<day>[0-9]{2})$"
        )

        self.yyyy_mm_dd_pattern = re.compile(YYYY_MM_DD_PATTERN_STR)

        if self.args.actual:
            # aktuální den překlopí o 15 minut později, aby byla dostupná data
            # pro prvních 15 minut nového dne (tedy 12:00 až 12:15)
            dt = datetime.utcnow() - timedelta(hours=12, minutes=15)
            actual_day = dt.strftime("%Y/%m/%d")
            input_dir = os.path.join(self.args.input_dir, actual_day)
            logging.debug("input_dir = %s" % input_dir)
            input_dirs = [input_dir]
        else:
            input_dirs = self.get_input_dirs()

        for input_dir in input_dirs:
            try:
                if self.args.make_lst:
                    self.make_lst(input_dir)
                elif self.args.convert_png:
                    self.process_dir(input_dir, png=True)
                else:
                    self.process_dir(input_dir)
            except:
                logging.exception("self.process_dir() failed")

    @staticmethod
    def get_dirs(dirname, counter):
        result_dirs = []
        counter += 1
        logging.debug("Fits2Video.get_dirs(): counter = %i" % counter)

        for item in os.listdir(dirname):
            item_dir = os.path.join(dirname, item)
            if not os.path.isdir(item_dir):
                continue

            if counter == 3:
                result_dirs.append(item_dir)
            else:
                result_dirs.extend(Fits2Video.get_dirs(item_dir, counter))

        logging.debug("Fits2Video.get_dirs(): counter = %i, result_dirs = %s" % (counter, result_dirs))
        return result_dirs

    def get_input_dirs(self):
        input_dirs = []

        for item in Fits2Video.get_dirs(self.args.input_dir, 0):
            match = self.yyyy_mm_dd_pattern.search(item)
            if not match:
                logging.debug("Skipping directory %s (unknown pattern)" % item)
                continue

            date_str = "%(year)s-%(month)s-%(day)s" % match.groupdict()

            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
            except:
                logging.debug("Skipping directory %s (bad date)" % item)
                continue

            if self.begin_date and date < self.begin_date:
                logging.debug("Skipping directory %s (older data)" % item)
                continue

            if self.end_date and date > self.end_date:
                logging.debug("Skipping directory %s (newer data)" % item)
                continue

            input_dirs.append(item)

        return sorted(input_dirs)

    def make_lst(self, input_dir):
        year_month = input_dir[-10:-3]
        prefix = input_dir[-10:].replace("/", "-")

        output_dir = os.path.join(self.args.output_dir, year_month)
        output_filename = os.path.join(output_dir, "%s.lst" % prefix)

        if not self.args.force and os.path.exists(output_filename):
            logging.debug("Output file %s exists. Skipping %s." % (output_filename, input_dir))
            return

        mkdir_p(output_dir)

        with open(output_filename, "w") as fo:
            # .fit and .fit.fz
            filenames = sorted(glob("%s/*.fit*" % input_dir))
            filenames_len = len(filenames)
            counter = 0
            for filename in filenames:
                counter += 1

                hdu_idx = 0
                if filename[-3:] == ".fz":
                    hdu_idx = 1

                with fits.open(filename) as hdulist:
                    prihdr = hdulist[hdu_idx].header
                    fits_date = prihdr["DATE-OBS"]
                    fits_time = prihdr["UT"]
                    # 2021-11-15 15:19:18
                    date_time_str = "%s %s" % (fits_date, fits_time)
                    dt = datetime.strptime(date_time_str, "%Y-%m-%d %H:%M:%S")

                    fo.write("%s %s\n" % (filename, date_time_str))

    def process_dir(self, input_dir, png=False):
        year_month = input_dir[-10:-3]
        prefix = input_dir[-10:].replace("/", "-")

        if self.args.actual:
            output_dir = self.args.output_dir
            output_filename = os.path.join(output_dir, "actual_%04i_new.mp4" % self.args.actual)

            if os.path.isfile(output_filename):
                return
        else:
            output_dir = os.path.join(self.args.output_dir, year_month)
            output_filename = os.path.join(output_dir, "%s.mp4" % prefix)

        if not self.args.force and os.path.exists(output_filename):
            logging.debug("Output file %s exists. Skipping %s." % (output_filename, input_dir))
            return

        mkdir_p(output_dir)

        fourcc = cv2.VideoWriter_fourcc(*'avc1')
        video_writer = cv2.VideoWriter(output_filename, fourcc, self.args.fps, (1280, 960), 0)

        if png:
            pattern = "*.png"
        else:
            pattern = "*.fit*"

        logging.debug("pattern = %s" % pattern)

        # .fit and .fit.fz
        filenames = sorted(glob("%s/%s" % (input_dir, pattern)))
        filenames_len = len(filenames)
        counter = 0
        for filename in filenames:
            counter += 1

            if self.args.actual and counter < (filenames_len - self.args.actual):
                continue

            if png:
                img = cv2.imread(filename, cv2.IMREAD_GRAYSCALE)
                video_writer.write(img)
            else:
                hdu_idx = 0
                if filename[-3:] == ".fz":
                    hdu_idx = 1

                with fits.open(filename) as hdulist:
                    prihdr = hdulist[hdu_idx].header
                    # DATE-OBS= '2022-10-31T01:10:41.791'
                    fits_date_obs = prihdr["DATE-OBS"]
                    img = img_as_ubyte(hdulist[hdu_idx].data)
                    text = "%s" % (fits_date_obs)

                    cv2.putText(img, text, org=(20, 100), fontFace=0, fontScale=3, color=(255, 255, 255), thickness=6)

                    video_writer.write(img)

            logging.debug("%s %3.0f%% (%i from %i)" % (filename, counter / (filenames_len / 100.0), counter, filenames_len))

        video_writer.release()
        os.sync()
        logging.debug("%s SUCCESS" % output_filename)

        if self.args.actual:
            # /data/allsky/videos/actual_0030_new.mp4
            shutil.move(output_filename, output_filename.replace("_new", ""))

def main():
    parser = create_argument_parser()
    args = parser.parse_args()
    logging.debug("args = %s" % args)

    fits2video = Fits2Video(args)

if __name__ == '__main__':
    main()
