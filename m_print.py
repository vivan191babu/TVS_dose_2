#!/usr/bin/env python3


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

def print_table(column_hdrs : list, rows : dict):
    # Headers
    print(" " * 18, end = "")
    for hdr in column_hdrs:
        print(f"{hdr:5.1f}" + " " * 5, end = "")
    print()
    # Rows
    for key, val in rows.items():
        Emin = key[0]
        Emax = key[1]
        print(f"{Emin:3.1e} - {Emax:3.1e} ", end = "")
        for cell in val:
            print(f"{cell:9.1f} ", end = "")
        print()

