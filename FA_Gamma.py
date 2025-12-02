#!/usr/bin/env python3

import m_print
import datetime, re, os, string, math

TIME_FORMAT = '%d.%m.%Y %H:%M:%S'

MCUGreenDirName = "TVS_Green"

# Structure is a series of nested dictionaries as
# Greens[1..5] key is where the source is, values are
#  IncGamma[Esrc] key is the source gamma-quantum energy, eV, values are
#   RegZones[100..149] key is MCU reg zone, values are
#    Fluxes[E] key is dissipated quantum energy, eV, values are fluxes, p/cm2*sec

def ReadFIN(fn):
    def ParseDataLine(line):
        clear_line = line.strip(string.whitespace)
        separators = re.compile(r"\s+")
        val_str = separators.split(clear_line)
        try:
            vals = [float(v) for v in val_str]
        except ValueError:
            vals = None
        return vals

    def ParseZoneLine(line):
        line_pattern = re.compile(
        r"""ZONE:
              \s+                          # Any number of spaces
             (?P<zone>[0-9]+)              # Integer Zone no
        """, re.VERBOSE)
        num_match = line_pattern.search(line)
        if num_match is not None:
            zone = int(num_match.group("zone"))
        else:
            zone = None
        return zone

    def AddFluxLine(vals):
        E = vals[0]
        Flux = vals[1]
        Fluxes[E] = Flux


    Flag1 = "-- ZONES --"
    Flag2 = "FLUX"
    Flag3 = "Energy"
    Flag4 = "-- OBJECTS --"
    Lines2Find = 3
    RegZones = dict()
    Fluxes = dict()
    with open(file = fn, mode='r', encoding='utf8') as FINfileObject:
        finLineNo = 0
        for finLine in FINfileObject:
            finLineNo += 1
            if finLine.strip(string.whitespace).startswith(Flag1):
                Lines2Find -= 1
                continue
            if (Lines2Find == 2 and
                finLine.strip(string.whitespace).startswith(Flag2)):
                Lines2Find -= 1
                zone = ParseZoneLine(finLine)
                continue
            if (Lines2Find == 1 and
                finLine.strip(string.whitespace).startswith(Flag3)):
                Lines2Find -= 1
                continue
            if Lines2Find == 0:
                #m_print.m_print(f"Reading spectrum, line no = {finLineNo}")
                values = ParseDataLine(finLine)
                if values is None:
                    # Finished reading sources for particular zone
                    Lines2Find = 2
                    RegZones[zone] = Fluxes
                    Fluxes = dict()
                else:
                    AddFluxLine(values)
            if finLine.strip(string.whitespace).startswith(Flag4):
                break

    # Now we have to divide MCU "fluxes" into reg zones volumes
    # to get the values in "p/cm2*sec" units
    Rs = [3,4,5,6,7,39,42]
    h = 9.2
    Vs = dict()
    for R,r in zip(Rs[1:],Rs[:-1]):
        Vs[R] = math.pi*(R*R-r*r)*h
    z10 = {10:4, 11:5, 12:6, 13:7, 14:42}
    for zone in RegZones:
        for E in RegZones[zone]:
            ZoneRemoteness = zone // 10
            ZoneVolume = Vs[z10[ZoneRemoteness]]
            RegZones[zone][E] /= ZoneVolume
    return RegZones

def readFINsDir(dir_name):
    IncGamma = dict()
    folder = os.path.join(os.curdir, MCUGreenDirName, dir_name)
    FINFileTemplate = re.compile(
        r"""^TVS_N.FIN_S
            (?P<finno>[0-9]+)$
         """, re.VERBOSE)
    STAFileTemplate = re.compile(
        r"""^EMES
            \s+                          # Any number of spaces
            (?P<number>                  # To create symbolic group
            [-+]?[0-9]*[.]?[0-9]+        # Mantissa part
            ([eE][-+]?[0-9]+)?)$
         """, re.VERBOSE)

    for filename in os.listdir(folder):
        f = os.path.join(folder, filename)
        fin_match = FINFileTemplate.match(filename)
        if os.path.isfile(f) and fin_match is not None:
            fin_no = int(fin_match.group("finno"))
            param_fn = f"STA{fin_no:08d}"
            fp = os.path.join(folder, param_fn)
            with open(file = fp, mode='rt', encoding='cp1251') as param_file_object:
                for pl in param_file_object:
                    param_match = STAFileTemplate.match(pl)
                    if param_match is not None:
                        break
            Esrc = float(param_match.group("number"))
            # print(filename, fin_no, Esrc)
            regZones = ReadFIN(f)
            IncGamma[Esrc] = regZones
    return IncGamma

def readGreenFuncs():
    Greens = dict()
    for src in range(1,6):
        dir_name = f"TVS_{src:1d}"
        IncGamma = readFINsDir(dir_name)
        Greens[src] = IncGamma
    return Greens
        

