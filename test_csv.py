#!/usr/bin/env python3

import csv
import datetime, math

DateFormat = '%d.%m.%Y %H:%M:%S'

def m_print(*what, level = -1):
    def str_val(value):
        if type(value) is datetime.datetime:
            return value.strftime(DateFormat)
        elif type(value) is int:
            return str(value)
        elif type(value) is float:
            if -5 < math.log10(1e-10 + math.fabs(value)) < 10:
                return f"{value:3.6f}"
            else:
                return f"{value:3.6e}"
        else:
            return str(value)

    if level == -1:
        timestamp = datetime.datetime.now().strftime(DateFormat) + ": "
        print(timestamp, end="")
    for p in what:
        if type(p) is list:
            level += 1
            print((" " * level) + f"List of {len(p)} elements:")
            for n,e in enumerate(p):
                print((" " * level) + f"{n}: ", end="")
                m_print(e, level = level)
        elif type(p) is tuple:
            level += 1
            print((" " * level) + f"Tuple of {len(p)} elements:")
            for n,e in enumerate(p):
                print((" " * level) + f"{n}: ", end="")
                m_print(e, level = level)
        elif type(p) is dict:
            level += 1
            print((" " * level) + f"Dictionary of {len(p)} elements:")
            for n,(k,v) in enumerate(p.items()):
                print((" " * level) + f"{n}: ", end="")
                m_print(k, ":", v, level = level)
        else:
            print(str_val(p), end=" ")
    print()


with open('env_history.txt', newline='') as csvfile:
	d=csv.DictReader(csvfile,dialect=csv.excel_tab)
	for row in d:
		m_print(row)
