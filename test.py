#!/usr/bin/env python3

import nswairquality

if __name__ == "__main__":
    x = nswairquality.NSWAirQuality()
    print(x.toJSON(True))
