#!/usr/bin/python3

# AIPlanner - Deep Learning Financial Planner
# Copyright (C) 2019 Gordon Irlam
#
# All rights reserved. This program may not be used, copied, modified,
# or redistributed without permission.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the
# implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
# PURPOSE.

from argparse import ArgumentParser
from datetime import datetime, timedelta
from json import dumps, loads
from os.path import expanduser
from re import search
from sys import stdin
from urllib.request import urlopen

def update(models_dir, read_stdin, write_stdout):

    page = stdin.read() if read_stdin else urlopen('https://www.marketwatch.com/investing/index/vix').read().decode('utf-8')

    vix = search('<meta name="price" content="(\d+\.\d+)"', page).group(1)
    vix = float(vix)

    date = search('<meta name="quoteTime" content="(\w+ \d+, \d+) .*"', page).group(1)
    date = datetime.strptime(date, '%b %d, %Y')
    date_str = date.date().isoformat()

    if write_stdout:
        print(date_str, vix)

    # Estimate of current observed monthly annualized stock market volatility relative to long term average.
    # For 1950-2108 the daily volatility of log returns of the S&P 500 was 14.0.
    #
    # VIX is a measure of the expected volatility of the S&P 500 over the next month rather than the current volatility, but hopefully this is close enough.
    level = vix / 14.0

    now = datetime.utcnow()
    assert now - timedelta(days = 7) < date <= now
    assert 0.5 < level < 5.0

    if write_stdout:
        print(level)
    else:
        try:
            f = open(models_dir + '/market-data.json')
            data = loads(f.read())
        except IOError:
            data = {}
        data['stocks_volatility'] = level
        data['stocks_volatility_date'] = date_str
        with open(models_dir + '/market-data.json', 'w') as f:
            print(dumps(data, indent = 4, sort_keys = True), file = f)

def main():

    parser = ArgumentParser()

    parser.add_argument('--models-dir', default = '~/aiplanner-data/models')
    parser.add_argument('--stdin', action = 'store_true', default = False)
    parser.add_argument('--stdout', action = 'store_true', default = False)

    args = parser.parse_args()

    update(expanduser(args.models_dir), args.stdin, args.stdout)

if __name__ == '__main__':
    main()
