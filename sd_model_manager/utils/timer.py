#!/usr/bin/env python

import atexit
import time
import functools

def secondsToStr(t):
    return "%d:%02d:%02d.%03d" % \
        functools.reduce(lambda ll,b : divmod(ll[0],b) + ll[1:],
            [(t*1000,),1000,60,60])

line = "="*40

class Timer:
    def log(self, s, elapsed=None):
        t = time.perf_counter()
        print(line)
        print(secondsToStr(t) + ' - ' + s)
        self.elapsed = t - self.last
        self.last = t
        elapsed = elapsed or self.elapsed
        if elapsed:
            print("Elapsed time:", secondsToStr(elapsed))
        print(line)
        print()

    def __enter__(self):
        self.start = time.perf_counter()
        self.last = self.start
        return self

    def __exit__(self, type, value, traceback):
        end = time.perf_counter()
        elapsed = end - self.start
        self.log("End Program", elapsed)
