#!/usr/bin/env python3

import DataReader
import FA_Gamma
import m_print
import datetime, re, os, math, subprocess, string
from typing import Optional, Tuple

TIME_FORMAT = '%d.%m.%Y %H:%M:%S'

FINsListFile = "MCUFINs.txt"
MCU_FAs_fn = "MCU_FAs.txt"
MCU_detectors_fn = "MCU_detectors.txt"
detectors_eff_fn = "detectors_eff.txt"
MCU_FA_spans = 0     # Will be adjusted during MCU_FAs_fn file parsing



NEED_HISTRORY_FILES = False
EXECUTE_NOW = False
INIT_ONLY = True

# Глобальные объекты (инициализируются через InitStaticArray)
Algorithms = None
Greens = None
CoreHistory = None

# Config files directory
ConfigDIRName = "Configs"

envelope_fn = "env_history.txt"
maxW_fn = "maxW_history.txt"
maxW2_fn = "maxW2_history.txt"

MCUDIRName = "MCU_FIN"
ZoneKey = "MCU zone"
CellKey = "Cell"
ChannelKey = "Channel"
PitchKey = "Pitch"
MeanKey = "Mean"
StdevKey = "Stdev"
RecUsefullKey = "Usefull"

# Fields related to MCU_FAs.txt file
R18CellField = "Cell"
R18PitchField = "Pitch"

# Fields related to MCU_detectors.txt file
R3ChannelField = "Channel"
# "RegZone" field name being index field is defined in DataReader.py

# Fields related to MCUFINs.txt file
AlgNameField = "Algorithm"
HCritField = "Hcrit"
NFAsField = "FAs"
FINFileName = "FileName"
ReferenceField = "Reference"

# Fields related to detectors_eff.txt file
RefDetChannelField = "Channel"
RefDetEffectivenessField = "Eff"

# ORIGEN-related constants
OrigenDIRName = "Origens"
template_file_name = "Origen_template.inp"
scale_bin = "c:\\SCALE-6.2.4\\bin\\scalerte.exe"
MARKER_T = "t=[ 1234567890987654321.1234567890987654321 ]"
MARKER_PWR = "power = [ 1234567890987654321.1234567890987654321e38 ]"
MARKER_TREG = "tt=[ 12 34 56 78 90 98 76 54 32 10 ]"
TIME_SHIFT = 10000.0
DECAY_HOURS = 320

# Result files dir
ResultsDIRName = "Core_FAs"


# --- Core test plan (Test_Plan) selection ---
# By default TCoreHistory reads Configs/Test_Plan.txt, but GUI may override it.
CoreTestPlanFile = None  # full path to test plan file, or None for default


def SetCoreTestPlanFile(path: Optional[str]):
    """Override the core test plan file.

    Parameters
    ----------
    path:
        Full path (absolute or relative) to the test plan file.
        If None or empty, the default Configs/Test_Plan.txt will be used.
    """
    global CoreTestPlanFile
    if path is None:
        CoreTestPlanFile = None
        return
    p = str(path).strip()
    CoreTestPlanFile = p if p else None


# --- Core test plan (Test_Plan) selection ---
# If None => default Configs/Test_Plan.txt (backward compatible)
CoreTestPlanFile: Optional[str] = None


def SetCoreTestPlanFile(path: Optional[str]):
    """Set custom core test plan file path (may have any name)."""
    global CoreTestPlanFile
    if path is None:
        CoreTestPlanFile = None
        return
    p = str(path).strip()
    CoreTestPlanFile = os.path.abspath(p) if p else None


def GetCoreTestPlanFile() -> str:
    """Return actual plan file path used by core history reader."""
    if CoreTestPlanFile:
        return CoreTestPlanFile
    # default (old behaviour)
    return os.path.abspath(os.path.join(os.curdir, ConfigDIRName, TCoreHistory.history_fn))


def ValidateCoreTestPlanFile(plan_path: str, algorithms: dict) -> None:
    """
    Validate Test_Plan file format.

    Required header fields: t, N(W), Algorithm, FAs
    Additional checks:
      - at least 2 records
      - first power must be ~0
      - time must be non-decreasing
      - (Algorithm, FAs) key must exist in 'algorithms'
    Raises CoreHistoryInvalid on any mismatch.
    """
    required = {"t", "N(W)", "Algorithm", "FAs"}

    if not plan_path or not os.path.isfile(plan_path):
        raise CoreHistoryInvalid(f"file not found: {plan_path}")

    try:
        rdr = DataReader.TDataReader(plan_path)
    except Exception as exc:
        raise CoreHistoryInvalid(str(exc))

    if not rdr.fields or not required.issubset(set(rdr.fields)):
        raise CoreHistoryInvalid(
            "unexpected header. Required fields: " + ", ".join(sorted(required))
        )

    t_i = rdr.find_field_index("t")
    p_i = rdr.find_field_index("N(W)")
    a_i = rdr.find_field_index("Algorithm")
    f_i = rdr.find_field_index("FAs")

    if len(rdr.raw_data) < 2:
        raise CoreHistoryInvalid("too few data records (need at least 2)")

    # numeric checks + monotonic time
    try:
        t0 = float(rdr.raw_data[0][t_i])
        p0 = float(rdr.raw_data[0][p_i])
    except Exception:
        raise CoreHistoryInvalid("t and N(W) must be numeric")

    if p0 > 1e-15:
        raise CoreHistoryInvalid("first record must have zero power")

    prev_t = t0
    for line_no, rec in enumerate(rdr.raw_data[1:], start=2):
        try:
            t = float(rec[t_i])
        except Exception:
            raise CoreHistoryInvalid(f"t is not numeric (line {line_no})")

        if t < prev_t:
            raise CoreHistoryInvalid(f"time must be non-decreasing (line {line_no})")
        prev_t = t

        alg_name = rec[a_i]
        try:
            n_fas = int(float(rec[f_i]))
        except Exception:
            raise CoreHistoryInvalid(f"FAs is not integer-like (line {line_no})")

        key = (alg_name, n_fas)
        if key not in algorithms:
            raise CoreHistoryInvalid(
                f"unknown Algorithm/FAs at line {line_no}: {alg_name} / {n_fas}"
            )


# Core procession exception as a base class
class CoreProcException(Exception):
    pass

class CoreHistoryInvalid(CoreProcException):
    def __init__(self, _why):
        super().__init()
        self.why = _why

    def __str__(self):
        return ("Core history file invalid: " + self.why)

def write_data_file(fn, *arrays):
    with open(file = fn,
         mode='w', encoding='utf8') as file_object:
        for data_fields in zip(*arrays):
            data_string = "\t".join("{data}".format(data = data_field)
                                    for data_field in data_fields)
            file_object.write(data_string + '\n')

def MakeOrigenFile(Origen_fn, str_t, str_power, str_treg):
    fn = os.path.join(os.curdir, OrigenDIRName, Origen_fn)
    template_fn = os.path.join(os.curdir, OrigenDIRName, template_file_name)
    with open(file = template_fn,
             mode='r', encoding='cp1251') as template_file_object:
        entire_file = template_file_object.read()
    m_print.m_print(f"File {template_file_name} opened, it's length is {len(entire_file)}")

    t_position = entire_file.find(MARKER_T)
    pwr_position = entire_file.find(MARKER_PWR)
    treg_position = entire_file.find(MARKER_TREG)
    m_print.m_print(f"t_position is {t_position}, pwr_position is {pwr_position}")

    t_corrected = entire_file.replace(MARKER_T, str_t)
    pwr_corrected = t_corrected.replace(MARKER_PWR, str_power)
    treg_corrected = pwr_corrected.replace(MARKER_TREG, str_treg)

    with open(file = fn, mode='w', encoding='cp1251') as origen_file_object:
        origen_file_object.write(treg_corrected)
    m_print.m_print(f"File {fn} saved")

def RunOrigen(task_fn):
    origen_fn = os.path.join(os.curdir, OrigenDIRName, task_fn)
    call_args = [scale_bin, origen_fn]
    try:
        result = subprocess.run(call_args, check=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                encoding='utf-8')
        if result.returncode == 0:
            m_print.m_print("Origen was run successfully")
        else:
            m_print.m_print(f"Origen's exit code was {result.returncode}")
    except subprocess.CalledProcessError as ex:
        m_print.m_print("Exception while Origen-ing")
        m_print.m_print("Exit status = {}".format(ex.returncode))
        m_print.m_print("Invokation string was {}".format(ex.cmd))
        m_print.m_print("scalerte stdout was {}".format(ex.stdout))
        m_print.m_print("scalerte stderr was {}".format(ex.stderr))

def ReadLine(line):
    line_pattern = re.compile(
            r"""^\s+                           # Any number of spaces
                 (?P<zone>[0-9]+)              # Integer Zone no
                  \s+                          # Any number of spaces
                 (?P<mean>                     # Mean flux
                  [-+]?[0-9]*[.]?[0-9]+        # Mantissa part
                  ([eE][-+]?[0-9]+)?)          # Optional exponent
                  \s+                          # Any number of spaces
                  (?P<StdDev>                  # Flux standard deviation
                  [-+]?[0-9]*[.]?[0-9]+        # Mantissa part
                  ([eE][-+]?[0-9]+)?)          # Optional exponent
                  [\r\n]$                      # End of line
            """, re.VERBOSE)
    triple_num_match = line_pattern.match(line)
    if triple_num_match is None:
        details = {ZoneKey:-1, MeanKey:float("NaN"), StdevKey:float("NaN")}
        return False, details
    zone = int(triple_num_match.group("zone"))
    mean = float(triple_num_match.group("mean"))
    stdev = float(triple_num_match.group("StdDev"))
    details = {ZoneKey:zone, MeanKey:mean, StdevKey:stdev}
    return True, details

def ReadR18Line(FAs_reader, line):
    data_line_OK, data_dict = ReadLine(line)

    zone = data_dict[ZoneKey]
    cell_idx = FAs_reader.find_field_index(R18CellField)
    pitch_idx = FAs_reader.find_field_index(R18PitchField)

    try:
        FAspan = FAs_reader[zone]
        cell = str(FAspan[cell_idx])
        pitch = int(FAspan[pitch_idx])

        FAspanD = {ZoneKey:zone, CellKey:cell, PitchKey:pitch,
                   MeanKey:data_dict[MeanKey],
                   StdevKey:data_dict[StdevKey],
                   RecUsefullKey:True}
        # print_dict(FAspanD)
    except KeyError:
        # print(f"Zone {zone} was not found in MCU_FAs.txt")
        FAspanD = {ZoneKey:zone, CellKey:"-", PitchKey:-1,
                   MeanKey:float("NaN"), StdevKey:float("NaN"), RecUsefullKey:False}

    return data_line_OK, FAspanD

def ReadR3Line(MCU_detectors_reader, line):
    data_line_OK, data_dict = ReadLine(line)

    zone = data_dict[ZoneKey]
    channel_idx = MCU_detectors_reader.find_field_index(R3ChannelField)

    try:
        det_channel = MCU_detectors_reader[zone]
        channel = int(det_channel[channel_idx])

        detector = {ZoneKey:zone, ChannelKey:channel,
                   MeanKey:data_dict[MeanKey],
                   StdevKey:data_dict[StdevKey],
                   RecUsefullKey:True}
        # print_dict(detector)
    except KeyError:
        # print(f"Zone {zone} was not found in MCU_detectors.txt")
        detector = {ZoneKey:zone, ChannelKey:-1,
                   MeanKey:float("NaN"), StdevKey:float("NaN"), RecUsefullKey:False}

    return data_line_OK, detector

# Calculated FAs - there ara whole core of them in each TAlgorithm
class TCalcFA(object):
    def __init__(self):
        self.fissions = dict()

class Tdetector(object):
    def __init__(self):
        self.R3 = None
        self.effectiveness = None   # A/W or nv/W

class TAlgorithm(object):

    zones_line = " -- ZONES --"
    objects_line = " -- OBJECTS --"
    hdr_line = "         Zone          Mean        StdDev"
    R3_line  = " NUCLIDE:          MIXT, REACTION:            3, ENERGY:    0.00000E+00"
    R18_line = " NUCLIDE:          MIXT, REACTION:           18, ENERGY:    0.00000E+00"

    def __init__(self, FAs_reader, detectors_eff_reader, MCU_detectors_reader,
                 HCrit, NFAs, FINfn, isRefAlg):

        self.FAs = dict()
        self.detectors = dict()
        self.Hcrit = float(HCrit)
        self.isReference = bool(isRefAlg)

        def add_detector(data_dict):
            detector = Tdetector()
            detector.channel = data_dict[ChannelKey]
            detector.R3 = data_dict[MeanKey]
            self.detectors[data_dict[ChannelKey]] = detector

        def add_mod_FA(data_dict):
            global MCU_FA_spans
            if data_dict[CellKey] not in self.FAs:
                self.FAs[data_dict[CellKey]] = TCalcFA()
            self.FAs[data_dict[CellKey]].fissions[data_dict[PitchKey]
                                                ] = data_dict[MeanKey]
            if data_dict[PitchKey] + 1 > MCU_FA_spans:
                MCU_FA_spans = data_dict[PitchKey] + 1

        # Read MCU .fin file
        fn = os.path.join(MCUDIRName, FINfn)
        R3Lines2find = 3
        R18Lines2find = 3
        R3Records = 0; R18Records = 0
        R3Over = False; R18Over = False
        with open(file = fn, mode='r', encoding='utf8') as FINfileObject:
            finLineNo = 0
            for finLine in FINfileObject:
                finLineNo += 1
                if finLine.startswith(type(self).zones_line):
                    # print("ZONES found")
                    R3Lines2find -= 1
                    R18Lines2find -= 1
                    continue
                if finLine.startswith(type(self).objects_line):
                    # print("OBJECTS found")
                    R3Lines2find += 10
                    R18Lines2find += 10
                    continue
                if finLine.startswith(type(self).R3_line):
                    # print("MIX R3 found")
                    R3Lines2find -= 1
                    continue
                if finLine.startswith(type(self).R18_line):
                    # print("MIX R18 found")
                    R18Lines2find -= 1
                    continue
                if R3Lines2find == 1 and finLine.startswith(type(self).hdr_line):
                    R3Lines2find -= 1
                    continue
                if R3Lines2find == 0:
                    # Read MIX R3 info
                    # print(f"Reading R3, line no = {finLineNo}")
                    data_line_OK, data_dict = ReadR3Line(MCU_detectors_reader, finLine)
                    if not data_line_OK:
                        # Finished reading R3 array
                        R3Lines2find += 10
                        R3Over = True
                    elif data_dict[RecUsefullKey]:
                        # print_dict(data_dict)
                        add_detector(data_dict)
                        R3Records += 1
                if R18Lines2find == 1 and finLine.startswith(type(self).hdr_line):
                    R18Lines2find -= 1
                    continue
                if R18Lines2find == 0:
                    # Read MIX R18 info
                    # print(f"Reading R18, line no = {finLineNo}")
                    data_line_OK, data_dict = ReadR18Line(FAs_reader, finLine)
                    if not data_line_OK:
                        # Finished reading R18 array
                        R18Lines2find += 10
                        R18Over = True
                    elif data_dict[RecUsefullKey]:
                        # print_dict(data_dict)
                        add_mod_FA(data_dict)
                        R18Records += 1
                if R3Over and R18Over:
                    break

        # Calculate total core fissions
        self.total_fissions = float(0)
        for FA in self.FAs.values():
            for span_fissions in FA.fissions.values():
                self.total_fissions += span_fissions

        # Calculate the relative energy distribution between FAs spans
        for FA in self.FAs.values():
            for span in FA.fissions:
                FA.fissions[span] /= self.total_fissions


# Actual FAs
class TFA(object):
    def __init__(self):
        self.burnup = dict()     # FA span burnup, W*hr
        self.FA_burnup = 0.0

# Particular FA span history
class TFAspanHistory(object):
    def __init__(self):
        self.history = list()

    def add_point(self, hrs, pwr):
        if len(self.history) == 0:
            self.ref_hrs = hrs
        self.history.append((hrs, pwr))

    def save_into_file(self, result_fn):
        fn = os.path.join(os.curdir, ResultsDIRName, result_fn)
        with open(file = fn, mode='wt',
                  encoding='utf8') as data_file_object:
            # Header line
            hdrs = ("Hours", "Power")
            hdr_line = "\t".join(hdrs) + "\n"
            data_file_object.write(hdr_line)
            # Data array
            self.history.sort(key = lambda x: x[0])
            for rec in self.history:
                time = f"{rec[0]:8.6f}"
                pwr = f"{rec[1]:8.6f}"
                dv = (time, pwr)
                data_line = "\t".join(dv) + "\n"
                data_file_object.write(data_line)

    def save_into_file_2(self, result_fn):
        fn = os.path.join(os.curdir, ResultsDIRName, result_fn)
        def line_layout(rec):
            time = f"{rec[0]:8.6f}"
            pwr = f"{rec[1]:8.6f}"
            dv = (time, pwr)
            data_line = "\t".join(dv) + "\n"
            return data_line

        with open(file = fn, mode='wt',
                  encoding='utf8') as data_file_object:
            # Header line
            hdrs = ("Hours", "Power")
            hdr_line = "\t".join(hdrs) + "\n"
            data_file_object.write(hdr_line)
            # Data array
            self.history.sort(key = lambda x: x[0])
            # First rec
            data_line = line_layout(self.history[0])
            data_file_object.write(data_line)
            prev_time = self.history[0][0]
            # Second to last but one
            for rec in self.history[1:-1]:
                rec_prev_date = (prev_time, rec[1])
                data_line = line_layout(rec_prev_date)
                data_file_object.write(data_line)
                data_line = line_layout(rec)
                data_file_object.write(data_line)
                prev_time = rec[0]
            # Last rec
            data_line = line_layout(self.history[-1])
            data_file_object.write(data_line)

    def build_origen_params(self):
        hours = list()
        powers = list()
        for rec in self.history:
            h = rec[0] - self.ref_hrs
            hours.append(h + TIME_SHIFT)
            powers.append(rec[1] / 1e6)      # MW

        time = " ".join(f"{h}" for h in hours)
        power = " ".join(f"{pwr}" for pwr in powers)
        report_time = "t = [ " + time + "]"
        report_power = "power = [ " + power + "]"
        return report_time, report_power

# Envelope FA span history
class TEnvelopeFAspanHistory(object):
    def __init__(self):
        self.history = list()

    def add_point(self, hrs, pwr, cell, span):
        if len(self.history) == 0:
            self.ref_hrs = hrs
        self.history.append((hrs, pwr, cell, span))

    def save_into_file(self, result_fn):
        fn = os.path.join(os.curdir, ResultsDIRName, result_fn)
        with open(file = fn, mode='wt',
                  encoding='utf8') as data_file_object:
            # Header line
            hdrs = ("Hours", "Power", "Cell", "Span")
            hdr_line = "\t".join(hdrs) + "\n"
            data_file_object.write(hdr_line)
            # Data array
            self.history.sort(key = lambda x: x[0])
            for rec in self.history:
                time = f"{rec[0]:8.6f}"
                pwr = f"{rec[1]:8.6f}"
                cell = str(rec[2])
                span = f"{rec[3]:d}"
                dv = (time, pwr, cell, span)
                data_line = "\t".join(dv) + "\n"
                data_file_object.write(data_line)

    def save_into_file_2(self, result_fn):
        fn = os.path.join(os.curdir, ResultsDIRName, result_fn)
        def line_layout(rec):
            time = f"{rec[0]:8.6f}"
            pwr = f"{rec[1]:8.6f}"
            cell = str(rec[2])
            span = f"{rec[3]:d}"
            dv = (time, pwr, cell, span)
            data_line = "\t".join(dv) + "\n"
            return data_line

        with open(file = fn, mode='wt',
                  encoding='utf8') as data_file_object:
            # Header line
            hdrs = ("Hours", "Power", "Cell", "Span")
            hdr_line = "\t".join(hdrs) + "\n"
            data_file_object.write(hdr_line)
            # Data array
            self.history.sort(key = lambda x: x[0])
            # First rec
            data_line = line_layout(self.history[0])
            data_file_object.write(data_line)
            prev_time = self.history[0][0]
            # Second to last but one
            for rec in self.history[1:-1]:
                rec_prev_date = (prev_time, ) + rec[1:]
                data_line = line_layout(rec_prev_date)
                data_file_object.write(data_line)
                data_line = line_layout(rec)
                data_file_object.write(data_line)
                prev_time = rec[0]
            # Last rec
            data_line = line_layout(self.history[-1])
            data_file_object.write(data_line)

    def build_origen_params(self):
        hours = list()
        powers = list()
        for rec in self.history:
            h = rec[0] - self.ref_hrs
            hours.append(h + TIME_SHIFT)
            powers.append(rec[1] / 1e6)      # MW

        time = " ".join(f"{h}" for h in hours)
        power = " ".join(f"{pwr}" for pwr in powers)
        report_time = "t = [ " + time + "]"
        report_power = "power = [ " + power + "]"
        return report_time, report_power



class TCoreHistory(object):
    history_fn = "Test_Plan.txt"
    Origen_fns = ["max_burnup", "max_2_hours", "envelope"]
    # NRB-99 constants for photon fluxes per 1e-12 Sv
    NRB = {10e3:0.0485, 15e3:0.125, 20e3:0.205, 30e3:0.300,  40e3:0.338,
           50e3:0.357,  60e3:0.378, 80e3:0.440, 0.1e6:0.517, 0.15e6:0.752,
           0.2e6:1.0,   0.3e6:1.51, 0.4e6:2.0,  0.5e6:2.47,  0.6e6:2.91,
           0.8e6:3.73,  1e6:4.48,   2e6:7.49,   4e6:12.0,    6e6:16.0,
           8e6:19.9,    10e6:23.8}


    def append_history_rec(self, t, N, alg, FAs):
        with open(file = type(self).history_fn, mode='at',
                  encoding='utf8') as data_file_object:
            rec = (t.strftime(TIME_FORMAT), str(N), str(alg), f"{FAs:d}")
            line = '\t'.join(rec) + '\n'
            data_file_object.write(line)


    def __init__(self, _algorithms, _Greens):
        TimeField = "t"
        PowerField = "N(W)"
        AlgField = "Algorithm"
        FAsField = "FAs"

        self.algorithms = _algorithms
        self.Greens = _Greens
        # Find the reference algorithm
        for alg_key, alg in self.algorithms.items():
            if alg.isReference:
                reference_algorithm = alg
                ref_alg_key = alg_key

        # Read the core test planned schedule
        fn = GetCoreTestPlanFile()
        self.HistoryReader = DataReader.TDataReader(fn)
        m_print.m_print("Core test plan read successfully")
        m_print.m_print("Fields: ")
        m_print.m_print(self.HistoryReader.fields)
        m_print.m_print(f"Total {len(self.HistoryReader.raw_data)} data records")
        self.TimeIndex = self.HistoryReader.find_field_index(TimeField)
        self.PowerIndex = self.HistoryReader.find_field_index(PowerField)
        self.AlgIndex = self.HistoryReader.find_field_index(AlgField)
        self.FAsIndex = self.HistoryReader.find_field_index(FAsField)

        # Check fist record power, must be zero
        power0 = self.HistoryReader.raw_data[0][self.PowerIndex]
        if power0 > 1e-15:
            raise CoreHistoryInvalid("first record must have zero power")

        # Create TWO fuel assemblies lists from the reference algorithm
        # with zero burn-up
        # first is for total burn-up accumulation, second for last 2 hours
        self.FAs = dict()
        self.FAs2 = dict()
        for cell in reference_algorithm.FAs:
            self.FAs[cell] = TFA()
            self.FAs2[cell] = TFA()
            for FAspan in reference_algorithm.FAs[cell].fissions:
                self.FAs[cell].burnup[FAspan] = 0.0
                self.FAs2[cell].burnup[FAspan] = 0.0
        # for debugging/testing only
        m_print.m_print(f"Totally {len(self.FAs)} FAs in the core")
##        m_print.m_print("Following are FA cells with number of spans:")
##        for FA in self.FAs:
##            print(FA, len(self.FAs[FA].burnup))

        # FA span with the maximun burnup
        self.Wmax_history = TFAspanHistory()
        # FA span with the maximun burnup for the last 2 hours
        self.Wmax2_history = TFAspanHistory()
        # Max burnup among every FA spans
        self.Wenvelope_history = TEnvelopeFAspanHistory()
        # Envelope axial energy generation distribution
        # Dictionary of MCU_FA_spans elements
        self.Wenvelope_axial = dict()

        # Prev 2 hours
        last_history_time = self.HistoryReader.raw_data[-1][self.TimeIndex]
        last2hours = last_history_time - 2
        # Calculate the burn-up for every FA span
        prev_history_time = self.HistoryReader.raw_data[0][self.TimeIndex]
        pwr0 = self.HistoryReader.raw_data[0][self.PowerIndex]   # must be zero!
        self.Wenvelope_history.add_point(prev_history_time, pwr0, "", -1)
        for rec in self.HistoryReader.raw_data[1::]:
            time = rec[self.TimeIndex]
            pwr = rec[self.PowerIndex]
            alg_name = rec[self.AlgIndex]
            alg_FAs = int(rec[self.FAsIndex])
            dt = time - prev_history_time
            burnup = pwr * dt              # W*hr
            prev_history_time = time
            max_burnup = 0.0
            max_cell = ""
            max_span = -1
            max_K = 0.0
            for FA in self.FAs:
                for FAspan in self.FAs[FA].burnup:
                    K = self.algorithms[(alg_name, alg_FAs)
                                        ].FAs[FA].fissions[FAspan]
                    # Accumulate the total burnup
                    span_burnup = burnup * K
                    self.FAs[FA].burnup[FAspan] += span_burnup
                    # Find the maximum for envelope
                    if span_burnup > max_burnup:
                        max_burnup = span_burnup
                        max_cell = FA
                        max_span = FAspan
                        max_K = K
                    self.FAs[FA].FA_burnup += span_burnup   # W*hr
            self.Wenvelope_history.add_point(
                              time, pwr*max_K, max_cell, max_span)

            for FA in self.FAs2:
                for FAspan in self.FAs2[FA].burnup:
                    K = self.algorithms[(alg_name, alg_FAs)
                                        ].FAs[FA].fissions[FAspan]
                    # Accumulate the burnup for last 2 hours
                    if time > last2hours:
                        self.FAs2[FA].burnup[FAspan] += burnup * K
                        self.FAs2[FA].FA_burnup += burnup * K      # W*hr

        # Now let's find the FA span with the maximum total burnup
        max_cell = ""
        max_span = -1
        max_burnup = 0.0
        for FA in self.FAs:
            for FAspan in self.FAs[FA].burnup:
                if self.FAs[FA].burnup[FAspan] > max_burnup:
                    max_burnup = self.FAs[FA].burnup[FAspan]      # W*hr
                    max_cell = FA
                    max_span = FAspan
        m_print.m_print("Overall maximum burnup was found for:")
        m_print.m_print(f"cell {max_cell} span {max_span} burnup {max_burnup} W*hr")

        # And FA span burnup envelope
        self.Wenvelope_axial = {k:0.0 for k in range(MCU_FA_spans)}
        for FA in self.FAs:
            for alg in self.algorithms:
                for FAspan in range(MCU_FA_spans):
                    # alg is (alg_name, NFAs) tuple - key to self.algorithms dictionary
                    span_fissions = self.algorithms[alg].FAs[FA].fissions[FAspan
                                                 ] * MCU_FA_spans * alg[1]
                    if span_fissions > self.Wenvelope_axial[FAspan]:
                        self.Wenvelope_axial[FAspan] = span_fissions

        m_print.m_print("Axial relative burnup envelope:")
        m_print.m_print(self.Wenvelope_axial)

        # And the FA span with the maximum burnup for the last 2 hours
        max_cell_2 = ""
        max_span_2 = -1
        max_burnup_2 = 0.0
        for FA in self.FAs2:
            for FAspan in self.FAs2[FA].burnup:
                if self.FAs2[FA].burnup[FAspan] > max_burnup_2:
                    max_burnup_2 = self.FAs2[FA].burnup[FAspan]
                    max_cell_2 = FA
                    max_span_2 = FAspan
        m_print.m_print("Maximum burnup for last 2 hours was found for:")
        m_print.m_print(f"cell {max_cell_2} span {max_span_2} burnup {max_burnup_2} W*hr")

        # Now prepare the history for those two variants
        for rec in self.HistoryReader.raw_data:
            time = rec[self.TimeIndex]
            pwr = rec[self.PowerIndex]
            alg_name = rec[self.AlgIndex]
            alg_FAs = int(rec[self.FAsIndex])
            K = self.algorithms[(alg_name, alg_FAs)
                                ].FAs[max_cell].fissions[max_span]
            K2 = self.algorithms[(alg_name, alg_FAs)
                                 ].FAs[max_cell_2].fissions[max_span_2]
            self.Wmax_history.add_point(time, pwr*K)
            self.Wmax2_history.add_point(time, pwr*K2)

        # FA with max burnup
        max_cell = ""
        max_burnup = 0.0
        for FA in self.FAs:
            if self.FAs[FA].FA_burnup > max_burnup:
                max_burnup = self.FAs[FA].FA_burnup
                max_cell = FA
        self.Wmax_FA = (max_cell, max_burnup)
        m_print.m_print(f"FA with max burnup is {max_cell}: {max_burnup} W*hrs")

        # FA with max burnup for last 2 hours
        max_cell = ""
        max_burnup = 0.0
        for FA in self.FAs2:
            if self.FAs2[FA].FA_burnup > max_burnup:
                max_burnup = self.FAs2[FA].FA_burnup
                max_cell = FA
        self.Wmax_FA2 = (max_cell, max_burnup)
        m_print.m_print(f"FA with max burnup for last 2 hours is {max_cell}: {max_burnup} W*hrs")

    def ParseOrigenOut(self, Origen_fn, container):
        def ParseOrigenLine(line):
            clear_line = line.strip(string.whitespace)
            separators = re.compile(
                r"""\s-\s|\s+""")
            val_str = separators.split(clear_line)
            try:
                vals = [float(v) for v in val_str]
            except ValueError:
                vals = None
            return vals

        def StoreOrigenEnergyBand(values):
            Emin = 1e6 * min(values[0:2])  # eV
            Emax = 1e6 * max(values[0:2])  # eV
            container[(Emin, Emax)] = values[2:]


        spectrum_line = "Gamma source intensity (1/s) as a function of time for case 'decay'"
        hdr_line = "boundaries (MeV)"
        Lines2Find = 3
        srcRecords = 0
        fn = os.path.join(os.curdir, OrigenDIRName, Origen_fn)
        with open(file = fn, mode='r', encoding='cp1251') as OrigenfileObject:
            OrigenLineNo = 0
            for OrigenLine in OrigenfileObject:
                OrigenLineNo += 1
                if OrigenLine.find(spectrum_line) != -1:
                    Lines2Find -= 1
                    continue
                if (Lines2Find == 2 and
                    all(x=='-' for x in OrigenLine.strip(string.whitespace))):
                    Lines2Find -= 1
                    continue
                if (Lines2Find == 1 and
                    OrigenLine.find(hdr_line) != -1):
                    Lines2Find -= 1
                    continue
                if Lines2Find == 0:
                    # Read Origen spectrum part
                    # m_print.m_print(f"Reading sources, line no = {OrigenLineNo}")
                    values = ParseOrigenLine(OrigenLine)
                    if values is None:
                        # Finished reading sources
                        break
                    else:
                        # m_print.m_print(values)
                        StoreOrigenEnergyBand(values)
                        srcRecords += 1

        m_print.m_print(f"{srcRecords} Origen sources were read")

    def InvokeOrigen(self, max_reg_hours):
        N_pts = 10
        precision = 1
        tmax_log = math.log(max_reg_hours)
        self.tregs = [round(math.exp(n / N_pts * tmax_log), precision)
                                           for n in range(1, N_pts+1)]
        self.tregs = [0.0] + self.tregs
        str_treg = "t = [" + " ".join(f"{v:.1f}" for v in self.tregs[1:]) + " ]"
        # Create the containers for Origen spectrums
        self.Wmax_src_spectrums = dict()
        self.Wmax2_src_spectrums = dict()
        self.Wenvelope_src_spectrums = dict()
        containers = [self.Wmax_src_spectrums,
                      self.Wmax2_src_spectrums,
                      self.Wenvelope_src_spectrums]
        # Calls ORIGEN 3 times
        methods = [self.Wmax_history.build_origen_params,
                   self.Wmax2_history.build_origen_params,
                   self.Wenvelope_history.build_origen_params]
        for fn, method, container in zip(
                    type(self).Origen_fns, methods, containers):
            str_t, str_power = method()
            MakeOrigenFile(fn + ".inp", str_t, str_power, str_treg)
            RunOrigen(fn + ".inp")
            self.ParseOrigenOut(fn + ".out", container)

    def FACellDoseRate(self, cell, max_reg_hours):
        N_pts = 10
        precision = 1
        tmax_log = math.log(max_reg_hours)
        self.tregs = [round(math.exp(n / N_pts * tmax_log), precision)
                                           for n in range(1, N_pts+1)]
        self.tregs = [0.0] + self.tregs
        str_treg = "t = [" + " ".join(f"{v:.1f}" for v in self.tregs[1:]) + " ]"

        cell_history = dict()
        for FA_span in range(MCU_FA_spans):
            cell_history[FA_span] = TFAspanHistory()
        # Prepare the history for the given cell
        for rec in self.HistoryReader.raw_data:
            time = rec[self.TimeIndex]
            pwr = rec[self.PowerIndex]
            alg_name = rec[self.AlgIndex]
            alg_FAs = int(rec[self.FAsIndex])
            for FA_span in range(MCU_FA_spans):
                K = self.algorithms[(alg_name, alg_FAs)
                                    ].FAs[cell].fissions[FA_span]
                cell_history[FA_span].add_point(time, pwr*K)
##        m_print.m_print(f"Cell {cell} history:")
##        for FA_span in range(MCU_FA_spans):
##            m_print.m_print(f"Span {FA_span}")
##            m_print.m_print(cell_history[FA_span].history)

        cell_src_spectrums = dict()
        for FA_span in range(MCU_FA_spans):
            fn = f"{cell}_{FA_span:d}"
            str_t, str_power = cell_history[FA_span].build_origen_params()
            MakeOrigenFile(fn + ".inp", str_t, str_power, str_treg)
            RunOrigen(fn + ".inp")
            cell_src_spectrums[FA_span] = dict()
            self.ParseOrigenOut(fn + ".out", cell_src_spectrums[FA_span])

        # Registered gamma energies
        Zones0 = list(self.Greens[1].values())[0]
        ERegs = list(list(Zones0.values())[0].keys())

        # Iterate over registration zone
        dose_arrays = dict()
        reg_fluxes = dict()
        for zone in range(130,150):
            reg_fluxes[zone] = {k:[0.0]*len(self.tregs) for k in ERegs}

            # Iterate over source span
            for src in range(1, 1+MCU_FA_spans):
                if src <= MCU_FA_spans // 2:
                    IncGamma = self.Greens[src]
                    reg_zone = zone
                else:
                    IncGamma = self.Greens[1+MCU_FA_spans - src]
                    ZoneRemoteness = zone // 10
                    ZoneHeight = zone % 10
                    reg_zone = 10 * ZoneRemoteness + (MCU_FA_spans - ZoneHeight - 1)
                # Iterate over incident energy
                for Esrc in IncGamma:
                    # Check whether the incident energy is in ORIGEN range
                    for OrigenKey in cell_src_spectrums[0]:
                        # OrigenKey is (Emin, Emax) like (1.191E+01, 8.090E+00)
                        if OrigenKey[0] <= Esrc <= OrigenKey[1]:
                            RegZone = IncGamma[Esrc][reg_zone]
                            # Iterate over dissipated flux
                            for flux in RegZone:
                                # Accumulate gamma-flux in reg_fluxes
                                # Iterate over registration time
                                for n_pt, origen_out in enumerate(
                                    cell_src_spectrums[src-1][OrigenKey]):
                                    reg_fluxes[zone][flux][n_pt
                                          ] += RegZone[flux] * origen_out
                            break

            # Now sum with the NRB weights to get the doze rate
            dozeRates = [0.0] * len(self.tregs)
            for E_NRB in type(self).NRB:
                for Elow, EHigh in zip(ERegs[:-1], ERegs[1:]):
                    if Elow <= E_NRB <= EHigh:
                        # Iterate over reg time
                        for n in range(len(dozeRates)):
                            dozeRates[n] += reg_fluxes[zone][EHigh][n
                                                ] * type(self).NRB[E_NRB] * 1e-12
            dose_arrays[zone] = dozeRates
        return dose_arrays


    def FADoseRate(self, axial, zone, sources):
        # axial is a dict {span:rel_burnup}, span is 0..9
        # zone is Green registration zone e.g. 121 or 136 etc
        # sources may be self.Wmax_src_spectrums or self.Wmax2_src_spectrums
        # or self.Wenvelope_src_spectrums
        # Result is the list of doze rates in the reg zone, Sv/sec
        # for times after reactor trip in self.self.tregs


        # Registered gamma energies
        Zones0 = list(self.Greens[1].values())[0]
        ERegs = list(list(Zones0.values())[0].keys())
        # m_print.m_print(ERegs)
        # Initial zero flux in the reg zone
        # times are kept in self.self.tregs
        reg_fluxes = {k:[0.0]*len(self.tregs) for k in ERegs}

        # Iterate over source span
        for src in range(1, 11):
            if src <= 5:
                IncGamma = self.Greens[src]
                reg_zone = zone
            else:
                IncGamma = self.Greens[11 - src]
                ZoneRemoteness = zone // 10
                ZoneHeight = zone % 10
                reg_zone = 10 * ZoneRemoteness + (9 - ZoneHeight)
            K_axial = axial[src-1]
            # Iterate over incident energy
            for Esrc in IncGamma:
                # Check whether the incident energy is in ORIGEN range
                for OrigenKey in sources:
                    if OrigenKey[0] <= Esrc <= OrigenKey[1]:
                        RegZone = IncGamma[Esrc][reg_zone]
                        # Iterate over dissipated flux
                        for flux in RegZone:
                            # Accumulate gamma-flux in reg_fluxes
                            # Iterate over registration time
                            for n_pt, origen_out in enumerate(sources[OrigenKey]):
                                reg_fluxes[flux][n_pt
                                      ] += K_axial * RegZone[flux] * origen_out
                        break
        #m_print.m_print("Times are:")
        #m_print.m_print(self.self.tregs)
        #m_print.m_print("reg_fluxes are:")
        #m_print.m_print(reg_fluxes)

        # Now sum with the NRB weights to get the doze rate
        dozeRates = [0.0] * len(self.tregs)
        for E_NRB in type(self).NRB:
            for Elow, EHigh in zip(ERegs[:-1], ERegs[1:]):
                if Elow <= E_NRB <= EHigh:
                    # Iterate over reg time
                    for n in range(len(dozeRates)):
                        dozeRates[n] += reg_fluxes[EHigh][n] * type(self).NRB[E_NRB] * 1e-12
        return dozeRates


def ReadStaticData(FINsListFile):
    fn = os.path.join(os.curdir, ConfigDIRName, FINsListFile)
    FINsReader = DataReader.TDataReader(fn)
    m_print.m_print("Fields: ")
    m_print.m_print(FINsReader.fields)
    m_print.m_print(f"Total {len(FINsReader.raw_data)} data records")

    Algorithms = dict()
    alg_index = FINsReader.find_field_index(AlgNameField)
    hcrit_index = FINsReader.find_field_index(HCritField)
    NFAs_index = FINsReader.find_field_index(NFAsField)
    FINName_index = FINsReader.find_field_index(FINFileName)
    isRef_index = FINsReader.find_field_index(ReferenceField)

    fn = os.path.join(os.curdir, ConfigDIRName, MCU_FAs_fn)
    FAs_reader = DataReader.TDataReader(fn)
    fn = os.path.join(os.curdir, ConfigDIRName, detectors_eff_fn)
    detectors_eff_reader = DataReader.TDataReader(fn)
    fn = os.path.join(os.curdir, ConfigDIRName, MCU_detectors_fn)
    MCU_detectors_reader = DataReader.TDataReader(fn)

    for alg_param in FINsReader.raw_data:
        alg_name = alg_param[alg_index]
        HCrit = alg_param[hcrit_index]
        NFAs = int(alg_param[NFAs_index])
        FINfn = alg_param[FINName_index]
        isRefAlg = alg_param[isRef_index]
        alg = TAlgorithm(FAs_reader, detectors_eff_reader,
                         MCU_detectors_reader,
                         HCrit, NFAs, FINfn, isRefAlg)
        alg_key = (alg_name, NFAs)
        Algorithms[alg_key] = alg
        m_print.m_print(f"{FINfn} read successfully")
        m_print.m_print(f"{alg_name} {len(alg.FAs)} FAs {len(alg.detectors)} detectors {alg.total_fissions} fissions")
        m_print.m_print(f"key = ({alg_name}, {NFAs})")
        m_print.m_print(f"Max {MCU_FA_spans} FA spans found")
    m_print.m_print(f"{len(Algorithms)} algorithms/FIN files were read")

    # Now read reference detectors effectivenesses
    fn = os.path.join(os.curdir, ConfigDIRName, detectors_eff_fn)
    RefEffReader = DataReader.TDataReader(fn)

    channel_index = RefEffReader.find_field_index(RefDetChannelField)
    eff_index = RefEffReader.find_field_index(RefDetEffectivenessField)

    # Find the reference algorithm
    for alg_key, alg in Algorithms.items():
        if alg.isReference:
            reference_algorithm = alg
            alg_id = f"{alg_key[0]} {alg_key[1]:d} FAs"
            m_print.m_print(f"Reference algorithm {alg_id} found")
            for channel,det in alg.detectors.items():
                try:
                    det.effectiveness = RefEffReader.get_item_by_field(
                              RefDetChannelField, channel)[eff_index]
                except KeyError:
                    m_print.m_print(f"Channel {det.channel} was not found in {detectors_eff_fn}")

    # Fill the detectors effectivenesses for all the other non-reference algorithms
    for alg_key, alg in Algorithms.items():
        if not alg.isReference:
            alg_id = f"{alg_key[0]} {alg_key[1]:d} FAs"
            m_print.m_print(f"Non-reference algorithm {alg_id} found")
            for channel,det in alg.detectors.items():
                K = det.R3 / reference_algorithm.detectors[channel].R3
                det.effectiveness = K * reference_algorithm.detectors[channel].effectiveness

    return Algorithms


# -------- Reactimeter (channel 4) support --------

REACTIMETER_CHANNEL = 4
SKNFP_CHANNELS = (1, 2, 3)

def _geo_mean(vals):
    """Geometric mean for positive values; fallback to arithmetic if invalid."""
    vals = [float(v) for v in vals if v is not None]
    if not vals:
        return None
    if any(v <= 0 for v in vals):
        return sum(vals) / len(vals)
    prod = 1.0
    for v in vals:
        prod *= v
    return prod ** (1.0 / len(vals))

def _arith_mean(vals):
    vals = [float(v) for v in vals if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)

def _read_ref_reactimeter_eff() -> Optional[float]:
    """Read reference reactimeter effectiveness Eff(ch=4) from detectors_eff.txt."""
    fn = os.path.join(os.curdir, ConfigDIRName, detectors_eff_fn)
    rdr = DataReader.TDataReader(fn)
    ch_i = rdr.find_field_index(RefDetChannelField)
    eff_i = rdr.find_field_index(RefDetEffectivenessField)
    for rec in rdr.raw_data:
        try:
            ch = int(float(rec[ch_i]))
        except Exception:
            continue
        if ch == REACTIMETER_CHANNEL:
            try:
                return float(rec[eff_i])
            except Exception:
                return None
    return None

def ComputeReactimeterEffectivenesses(
    algorithms: dict,
    *,
    method: str = "geo",
    sknfp_channels: Tuple[int, ...] = SKNFP_CHANNELS,
    reactimeter_channel: int = REACTIMETER_CHANNEL,
) -> float:
    """
    Заполняет для каждого алгоритма поле alg.reactimeter_eff (A/W),
    оценивая изменение эффективности реактиметра по изменению Eff каналов 1..3.

    Требуется: в detectors_eff.txt должен быть задан канал 4 (референсный).
    Метод: method="geo" (геометрическое среднее) или "arith" (арифметическое).
    """
    # Find reference algorithm
    ref_alg = None
    for _, a in algorithms.items():
        if getattr(a, "isReference", False):
            ref_alg = a
            break
    if ref_alg is None:
        raise RuntimeError("Reference algorithm not found (Reference=1 in MCUFINs.txt).")

    eff_ref_react = _read_ref_reactimeter_eff()
    if eff_ref_react is None:
        raise RuntimeError(
            f"Reactimeter channel {reactimeter_channel} not found in {detectors_eff_fn}. "
            f"Add it as reference effectiveness (A/W)."
        )

    mean_fn = _geo_mean if method.lower() == "geo" else _arith_mean

    # Reference: direct
    setattr(ref_alg, "reactimeter_eff", float(eff_ref_react))
    setattr(ref_alg, "reactimeter_k", 1.0)
    setattr(ref_alg, "reactimeter_method", method.lower())

    # Others: scale by mean ratio of SKNFP channels
    for _, alg in algorithms.items():
        if alg is ref_alg or getattr(alg, "isReference", False):
            continue

        ratios = []
        used_channels = []
        for ch in sknfp_channels:
            if ch not in alg.detectors or ch not in ref_alg.detectors:
                continue
            e_alg = alg.detectors[ch].effectiveness
            e_ref = ref_alg.detectors[ch].effectiveness
            if e_alg is None or e_ref is None:
                continue
            try:
                r = float(e_alg) / float(e_ref)
            except Exception:
                continue
            ratios.append(r)
            used_channels.append(ch)

        k = mean_fn(ratios)
        if k is None:
            setattr(alg, "reactimeter_eff", None)
            setattr(alg, "reactimeter_k", None)
            setattr(alg, "reactimeter_method", method.lower())
            setattr(alg, "reactimeter_used_channels", tuple(used_channels))
            continue

        setattr(alg, "reactimeter_eff", float(eff_ref_react) * float(k))
        setattr(alg, "reactimeter_k", float(k))
        setattr(alg, "reactimeter_method", method.lower())
        setattr(alg, "reactimeter_used_channels", tuple(used_channels))

    return float(eff_ref_react)


def ExportReactimeterCurrents(
    scale: float,
    plan_file: Optional[str] = None,
    out_path: Optional[str] = None,
    *,
    Imin_required_nA: float = 0.5,
    validate_plan: bool = True,
    method: str = "geo",
):
    """
    По Test_Plan рассчитывает ток реактиметра (канал 4) в нА:
      - I_react(t) = N(t) * Eff_react(alg) * 1e9
      - I_react_lim(t) = scale * N(t) * Eff_react(alg) * 1e9

    Также проверяет условие измеряемости: I_react_lim(t) >= Imin_required_nA для участков N(t)>0.

    Пишет файл:
      Core_FAs/reactimeter_currents.txt

    Возвращает dict с минимумом/максимумом и местом минимума.
    """
    global Algorithms
    if Algorithms is None:
        raise RuntimeError("Static data not initialized. Call InitStaticArray() first.")

    # Ensure reactimeter effectiveness exists
    ComputeReactimeterEffectivenesses(Algorithms, method=method)

    if plan_file is not None:
        SetCoreTestPlanFile(plan_file)

    plan_path = GetCoreTestPlanFile()
    if validate_plan:
        ValidateCoreTestPlanFile(plan_path, Algorithms)

    rdr = DataReader.TDataReader(plan_path)
    t_i = rdr.find_field_index("t")
    p_i = rdr.find_field_index("N(W)")
    a_i = rdr.find_field_index("Algorithm")
    f_i = rdr.find_field_index("FAs")

    out_dir = os.path.join(os.curdir, ResultsDIRName)
    os.makedirs(out_dir, exist_ok=True)
    if out_path is None:
        out_path = os.path.join(out_dir, "reactimeter_currents.txt")

    # Stats
    min_lim = None
    min_lim_where = None  # (t, alg, fas, N, Eff, I_lim_nA)
    max_lim = None

    per_alg = {}  # (alg,fas) -> {"min":..., "max":...}

    rows_written = 0

    with open(out_path, "wt", encoding="utf-8") as f:
        f.write("# t_h\tAlgorithm\tFAs\tN_W\tNlim_W\tEffReact_A_per_W\tIreact_nA\tIreact_lim_nA\tOK_ge_%.6g_nA\n" % Imin_required_nA)

        for rec in rdr.raw_data:
            try:
                t = float(rec[t_i])
                N = float(rec[p_i])
            except Exception:
                continue

            alg_name = str(rec[a_i])
            try:
                n_fas = int(float(rec[f_i]))
            except Exception:
                continue

            key = (alg_name, n_fas)
            if key not in Algorithms:
                raise CoreHistoryInvalid(f"unknown Algorithm/FAs in plan: {alg_name} / {n_fas}")

            alg = Algorithms[key]
            eff = getattr(alg, "reactimeter_eff", None)
            if eff is None:
                raise RuntimeError(
                    f"Reactimeter effectiveness is not available for algorithm {alg_name}/{n_fas}. "
                    f"Check that channels 1-3 have effectiveness and detectors_eff.txt has channel 4."
                )

            Nlim = float(scale) * N
            I = N * float(eff) * 1e9
            Ilim = Nlim * float(eff) * 1e9
            ok = (N <= 0.0) or (Ilim >= float(Imin_required_nA))

            f.write(f"{t:.6f}\t{alg_name}\t{n_fas:d}\t{N:.6e}\t{Nlim:.6e}\t{float(eff):.6e}\t{I:.6e}\t{Ilim:.6e}\t{1 if ok else 0}\n")
            rows_written += 1

            # Update per-alg stats only for N>0 segments
            if N > 0.0:
                st = per_alg.get(key)
                if st is None:
                    per_alg[key] = {"min": Ilim, "max": Ilim}
                else:
                    st["min"] = min(st["min"], Ilim)
                    st["max"] = max(st["max"], Ilim)

                if min_lim is None or Ilim < min_lim:
                    min_lim = Ilim
                    min_lim_where = (t, alg_name, n_fas, N, float(eff), Ilim)
                if max_lim is None or Ilim > max_lim:
                    max_lim = Ilim

        # Summary block
        f.write("\n")
        f.write("# SUMMARY\n")
        f.write(f"# scale = {float(scale):.6g}\n")
        f.write(f"# Imin_required_nA = {float(Imin_required_nA):.6g}\n")
        if min_lim_where is not None:
            t, alg_name, n_fas, N, eff, Ilim = min_lim_where
            f.write(f"# MIN_Ireact_lim_nA = {Ilim:.6e} at t={t:.6f}h alg={alg_name} FAs={n_fas} N={N:.6e}W Eff={eff:.6e}A/W\n")
        if max_lim is not None:
            f.write(f"# MAX_Ireact_lim_nA = {max_lim:.6e}\n")
        f.write("# Per-algorithm minima/maxima (only where N>0):\n")
        for key in sorted(per_alg.keys(), key=lambda k: (k[0], k[1])):
            st = per_alg[key]
            f.write(f"#   {key[0]}\t{key[1]}\tmin={st['min']:.6e}\tmax={st['max']:.6e}\n")

    ok_all = True
    if min_lim is not None and min_lim < float(Imin_required_nA):
        ok_all = False

    return {
        "out_path": os.path.abspath(out_path),
        "rows_written": rows_written,
        "scale": float(scale),
        "Imin_required_nA": float(Imin_required_nA),
        "min_lim_nA": (float(min_lim) if min_lim is not None else None),
        "max_lim_nA": (float(max_lim) if max_lim is not None else None),
        "min_where": min_lim_where,  # (t, alg, fas, N, Eff, Ilim_nA)
        "ok": ok_all,
        "per_algorithm": per_alg,
    }


def InitStaticArray(build_core_history: bool = True, plan_file: Optional[str] = None, validate_plan: bool = True):
    """
    Инициализирует статические входные данные проекта.

    build_core_history=True дополнительно строит TCoreHistory (без запуска ORIGEN),
    что позволяет сразу после инициализации получить интегралы мощности по ТВС.

    plan_file:
        Пользовательский путь к файлу Test_Plan (может называться иначе).
        Если None, будет использован стандартный Configs/Test_Plan.txt (как раньше).

    validate_plan:
        Если True — проверяет, что формат Test_Plan подходит.
        При отклонении возбуждает CoreHistoryInvalid.
    """
    global Algorithms, Greens, CoreHistory

    # 1) Применяем выбранный пользователем файл плана (если передан)
    if plan_file is not None:
        SetCoreTestPlanFile(plan_file)

    # 2) Читаем статику (алгоритмы + функции Грина)
    Algorithms = ReadStaticData(FINsListFile)
    # 2.1) Подготовка эффективности реактиметра (канал 4) по изменению каналов 1..3
    try:
        ComputeReactimeterEffectivenesses(Algorithms, method="geo")
    except Exception as exc:
        # Не валим инициализацию, но оставляем понятную диагностику в консоли/логе
        m_print.m_print(f"Reactimeter effectiveness was not prepared: {type(exc).__name__}: {exc}")

    Greens = FA_Gamma.readGreenFuncs()

    # 3) Проверяем формат Test_Plan (опционально)
    if validate_plan:
        plan_path = GetCoreTestPlanFile()
        ValidateCoreTestPlanFile(plan_path, Algorithms)

    # 4) Строим CoreHistory (опционально)
    if build_core_history:
        CoreHistory = TCoreHistory(Algorithms, Greens)


def ProcessCell(cell, hours):
    global Algorithms, Greens, CoreHistory
    if Algorithms is None or Greens is None:
        InitStaticArray(build_core_history=True)
    if CoreHistory is None:
        CoreHistory = TCoreHistory(Algorithms, Greens)

    dose_arrays_Svs = CoreHistory.FACellDoseRate(cell, hours)
    cell_fn = f"{cell}.txt"
    fn = os.path.join(os.curdir, ResultsDIRName, cell_fn)

    dose_arrays_uSvhr = []
    for reg_zone in dose_arrays_Svs:
        dose_arrays_uSvhr.append([Svs * 3600 * 1e6 for Svs in dose_arrays_Svs[reg_zone]])

    write_data_file(fn, CoreHistory.tregs, *dose_arrays_uSvhr)


def _cell_sort_key(cell: str):
    try:
        a, b = cell.split('-')
        return (int(a), int(b))
    except Exception:
        return (cell,)


def ExportFAEnergyIntegrals(out_path: Optional[str] = None):
    """
    Формирует таблицу:
      cell   Integral_all_time(W*hr)   Integral_last_2h(W*hr)

    Также возвращает:
      - ячейку с max интегралом за всё время + её значения (all и 2h)
      - ячейку с max интегралом за 2 часа + её значения (2h и all)

    ВАЖНО: это НЕ запускает ORIGEN и НЕ считает дозу.
    """
    global Algorithms, Greens

    if Algorithms is None or Greens is None:
        raise RuntimeError("Static data not initialized. Call InitStaticArray() first.")

    core = TCoreHistory(Algorithms, Greens)

    # Максимумы (у вас уже рассчитываются внутри TCoreHistory):contentReference[oaicite:2]{index=2}
    cell_all, w_all = core.Wmax_FA
    cell_2h, w_2h = core.Wmax_FA2

    # Дополнительно: "второе число" для каждой из этих ячеек
    w_2h_for_cell_all = core.FAs2[cell_all].FA_burnup if cell_all in core.FAs2 else 0.0
    w_all_for_cell_2h = core.FAs[cell_2h].FA_burnup if cell_2h in core.FAs else 0.0

    # Выходной файл
    out_dir = os.path.join(os.curdir, ResultsDIRName)
    os.makedirs(out_dir, exist_ok=True)
    if out_path is None:
        out_path = os.path.join(out_dir, "FA_power_integrals.txt")

    with open(out_path, "wt", encoding="utf-8") as f:
        f.write("# Cell\tIntegralPower_allTime(W*hr)\tIntegralPower_last2h(W*hr)\n")
        for cell in sorted(core.FAs.keys(), key=_cell_sort_key):
            total = core.FAs[cell].FA_burnup
            last2 = core.FAs2[cell].FA_burnup if cell in core.FAs2 else 0.0
            f.write(f"{cell}\t{total:.6e}\t{last2:.6e}\n")

    return {
        "out_path": os.path.abspath(out_path),

        "cell_all": cell_all,
        "w_all": w_all,
        "w_2h_for_cell_all": w_2h_for_cell_all,

        "cell_2h": cell_2h,
        "w_2h": w_2h,
        "w_all_for_cell_2h": w_all_for_cell_2h,
    }


def ExportAZSetpointsByAlgorithm(
    scale: float,
    plan_file: Optional[str] = None,
    out_path: Optional[str] = None,
    *,
    validate_plan: bool = True,
):
    """
    Рассчитывает уставки токов АЗ по алгоритмам:
      - берёт максимальные мощности (Pmax) для каждой пары (Algorithm, FAs) из Test_Plan,
      - применяет коэффициент scale,
      - умножает на эффективности детекторов и пишет таблицу токов.

    Параметры
    ---------
    scale:
        Масштаб мощности (например, результат estimate_power_scale).
    plan_file:
        Полный путь к файлу Test_Plan. Если None — используется CoreTestPlanFile или Configs/Test_Plan.txt.
    out_path:
        Куда писать результат. Если None — Core_FAs/AZ_setpoints_by_algorithm.txt.
    validate_plan:
        Если True — дополнительно проверяет формат Test_Pлан.

    Возврат
    -------
    dict с ключами:
      {
        "out_path": <abs path>,
        "rows": [
           {
             "algorithm": <str>,
             "fas": <int>,
             "pmax": <float>,
             "plim": <float>,
             "currents_A": {<channel>: <float>, ...},
             "currents_nA": {<channel>: <float>, ...},
           }, ...
        ]
      }
    """
    global Algorithms

    if Algorithms is None:
        raise RuntimeError("Static data not initialized. Call InitStaticArray() first.")

    if plan_file is not None:
        SetCoreTestPlanFile(plan_file)

    plan_path = GetCoreTestPlanFile()
    if validate_plan:
        ValidateCoreTestPlanFile(plan_path, Algorithms)

    rdr = DataReader.TDataReader(plan_path)
    t_i = rdr.find_field_index("t")
    p_i = rdr.find_field_index("N(W)")
    a_i = rdr.find_field_index("Algorithm")
    f_i = rdr.find_field_index("FAs")

    # 1) max power per (Algorithm, FAs)
    pmax = {}
    for rec in rdr.raw_data:
        try:
            p = float(rec[p_i])
        except Exception:
            continue

        alg_name = str(rec[a_i])
        try:
            n_fas = int(float(rec[f_i]))
        except Exception:
            continue

        key = (alg_name, n_fas)
        if key not in Algorithms:
            # plan ссылается на алгоритм, которого нет в MCUFINs
            raise CoreHistoryInvalid(f"unknown Algorithm/FAs in plan: {alg_name} / {n_fas}")

        prev = pmax.get(key)
        if prev is None or p > prev:
            pmax[key] = p

    # 2) currents per algorithm (per channel)
    rows = []
    all_channels = set()

    for (alg_name, n_fas), p_max in sorted(pmax.items(), key=lambda k: (k[0][0], k[0][1])):
        alg = Algorithms[(alg_name, n_fas)]
        p_lim = float(scale) * float(p_max)

        currents_A = {}
        currents_nA = {}

        for ch in sorted(alg.detectors.keys()):
            det = alg.detectors[ch]
            if det.effectiveness is None:
                raise RuntimeError(
                    f"Detector effectiveness is not set for channel {ch} in algorithm {alg_name}/{n_fas}"
                )
            I_A = p_lim * float(det.effectiveness)
            currents_A[ch] = I_A
            currents_nA[ch] = I_A * 1e9
            all_channels.add(ch)

        rows.append(
            {
                "algorithm": alg_name,
                "fas": int(n_fas),
                "pmax": float(p_max),
                "plim": float(p_lim),
                "currents_A": currents_A,
                "currents_nA": currents_nA,
            }
        )

    # 3) output file
    out_dir = os.path.join(os.curdir, ResultsDIRName)
    os.makedirs(out_dir, exist_ok=True)
    if out_path is None:
        out_path = os.path.join(out_dir, "AZ_setpoints_by_algorithm.txt")

    channels_sorted = sorted(all_channels)

    with open(out_path, "wt", encoding="utf-8") as f:
        hdr = ["Algorithm", "FAs", "Pmax_W", "Plim_W"]
        for ch in channels_sorted:
            hdr.append(f"I_ch{ch}_A")
        for ch in channels_sorted:
            hdr.append(f"I_ch{ch}_nA")
        f.write("# " + "\t".join(hdr) + "\n")

        for r in rows:
            line = [r["algorithm"], str(r["fas"]), f"{r['pmax']:.6e}", f"{r['plim']:.6e}"]
            for ch in channels_sorted:
                val = r["currents_A"].get(ch, 0.0)
                line.append(f"{val:.6e}")
            for ch in channels_sorted:
                val = r["currents_nA"].get(ch, 0.0)
                line.append(f"{val:.6e}")
            f.write("\t".join(line) + "\n")

    return {"out_path": os.path.abspath(out_path), "rows": rows}


# -------- Total core energy & U-235 consumption --------

# Physical constants (approximation):
# - Mean energy release per fission: 200 MeV (thermal)  -> ~3.204e-11 J
# - 1 fission consumes 1 atom (for "equivalent U-235 mass" estimate)
_FISSION_ENERGY_MEV = 200.0
_ELECTRONVOLT_J = 1.602176634e-19
_FISSION_ENERGY_J = _FISSION_ENERGY_MEV * 1e6 * _ELECTRONVOLT_J  # J/fission

_AVOGADRO = 6.02214076e23  # 1/mol
_U235_MOLAR_MASS_G = 235.0  # g/mol (engineering accuracy is sufficient here)


def ComputeCoreEnergyAndU235(
    plan_file: Optional[str] = None,
    *,
    scale: float = 1.0,
    validate_plan: bool = True,
):
    """
    Считает суммарную энерговыработку по всей активной зоне по Test_Plan и
    оценивает эквивалентный расход U-235 (в мкг) по энергии делений.

    Интегрирование выполнено в той же логике, что и в TCoreHistory:
    для каждого интервала dt = t_i - t_{i-1} берётся мощность из текущей записи i.

    Параметры
    ---------
    plan_file : путь к Test_Plan (если None — используется выбранный/стандартный)
    scale     : множитель мощности (например результат планирования res.scale)
    validate_plan : проверять формат Test_Plan и валидность Algorithm/FAs

    Возвращает dict:
      {
        "plan_path": ...,
        "scale": ...,
        "t_start_h": ...,
        "t_end_h": ...,
        "duration_h": ...,
        "energy_Wh": ...,
        "energy_kWh": ...,
        "energy_J": ...,
        "fissions": ...,
        "u235_g": ...,
        "u235_ug": ...,
      }
    """
    global Algorithms

    if plan_file is not None:
        SetCoreTestPlanFile(plan_file)

    plan_path = GetCoreTestPlanFile()

    if validate_plan:
        # Используем уже имеющуюся проверку (она требует, чтобы Algorithms были инициализированы)
        if Algorithms is None:
            raise RuntimeError("Algorithms not initialized. Call InitStaticArray() first.")
        ValidateCoreTestPlanFile(plan_path, Algorithms)

    rdr = DataReader.TDataReader(plan_path)
    t_i = rdr.find_field_index("t")
    p_i = rdr.find_field_index("N(W)")

    if len(rdr.raw_data) < 2:
        raise CoreHistoryInvalid("too few data records (need at least 2)")

    # Start/End time
    t0 = float(rdr.raw_data[0][t_i])
    t_last = float(rdr.raw_data[-1][t_i])

    # Integrate energy
    energy_Wh = 0.0
    prev_t = float(rdr.raw_data[0][t_i])

    for rec in rdr.raw_data[1:]:
        t = float(rec[t_i])
        p = float(rec[p_i]) * float(scale)  # W
        dt = t - prev_t                     # hours
        if dt < 0:
            raise CoreHistoryInvalid("time must be non-decreasing")
        energy_Wh += p * dt                 # W*hr
        prev_t = t

    energy_J = energy_Wh * 3600.0
    fissions = energy_J / _FISSION_ENERGY_J if energy_J > 0 else 0.0

    # Equivalent U-235 mass (engineering approximation)
    u235_g = fissions * (_U235_MOLAR_MASS_G / _AVOGADRO)
    u235_ug = u235_g * 1e6

    return {
        "plan_path": os.path.abspath(plan_path),
        "scale": float(scale),
        "t_start_h": t0,
        "t_end_h": t_last,
        "duration_h": (t_last - t0),
        "energy_Wh": float(energy_Wh),
        "energy_kWh": float(energy_Wh) / 1000.0,
        "energy_J": float(energy_J),
        "fissions": float(fissions),
        "u235_g": float(u235_g),
        "u235_ug": float(u235_ug),
    }


def FormatCoreEnergyAndU235Report(info: dict, *, title: str = "Суммарная энерговыработка"):
    """
    Удобный формат вывода для GUI/лога.
    """
    return (
        f"{title}:\n"
        f"  Test_Plan: {info.get('plan_path','')}\n"
        f"  scale = {info.get('scale', 1.0):g}\n"
        f"  t: {info.get('t_start_h', 0.0):g} .. {info.get('t_end_h', 0.0):g} ч "
        f"(Δt={info.get('duration_h', 0.0):g} ч)\n"
        f"  Энерговыработка: {info.get('energy_Wh',0.0):.6g} W·h "
        f"({info.get('energy_kWh',0.0):.6g} kW·h)\n"
        f"  Экв. расход U-235: {info.get('u235_ug',0.0):.6g} мкг "
        f"({info.get('u235_g',0.0):.6g} г)\n"
        f"  (оценка по 200 MeV/деление)"
    )



def _cell_sort_key_legacy(cell: str):
    # сортировка "1-1", "1-2", . по числам
    try:
        a, b = cell.split('-')
        return (int(a), int(b))
    except Exception:
        return (cell,)


def ExportFAEnergyIntegrals_tuple(out_path: Optional[str] = None):
    """
    LEGACY-ВАРИАНТ: оставлен для совместимости со старым форматом возврата.

    Возвращает:
      (abs_out_path, Wmax_FA, Wmax_FA2)
    где W в единицах W*hr.
    """
    global Algorithms, Greens, CoreHistory
    if Algorithms is None or Greens is None:
        InitStaticArray(build_core_history=True)
    if CoreHistory is None:
        CoreHistory = TCoreHistory(Algorithms, Greens)

    out_dir = os.path.join(os.curdir, ResultsDIRName)
    os.makedirs(out_dir, exist_ok=True)
    if out_path is None:
        out_path = os.path.join(out_dir, "FA_power_integrals.txt")

    with open(out_path, "wt", encoding="utf-8") as f:
        f.write("# Cell\tIntegralPower_allTime(W*hr)\tIntegralPower_last2h(W*hr)\n")
        for cell in sorted(CoreHistory.FAs.keys(), key=_cell_sort_key_legacy):
            total = CoreHistory.FAs[cell].FA_burnup
            last2 = CoreHistory.FAs2[cell].FA_burnup if cell in CoreHistory.FAs2 else 0.0
            f.write(f"{cell}\t{total:.6e}\t{last2:.6e}\n")

    return os.path.abspath(out_path), CoreHistory.Wmax_FA, CoreHistory.Wmax_FA2


# алиас “на всякий случай”
ExportFAEnergyIntegralsLegacy = ExportFAEnergyIntegrals_tuple
ExportFAEnergyIntegralsTuple = ExportFAEnergyIntegrals_tuple




if __name__ == "__main__" and EXECUTE_NOW:
    start_time = datetime.datetime.now()
    m_print.m_print('Start time is ',
          start_time.strftime(TIME_FORMAT))

    Algorithms = ReadStaticData(FINsListFile)
    Greens = FA_Gamma.readGreenFuncs()

    if not INIT_ONLY:
        try:
            CoreHistory = TCoreHistory(Algorithms, Greens)
            if NEED_HISTRORY_FILES:
                CoreHistory.Wenvelope_history.save_into_file_2(envelope_fn)
                m_print.m_print(f"Envelope file {envelope_fn} is written")
                CoreHistory.Wmax_history.save_into_file_2(maxW_fn)
                m_print.m_print(f"Max W file {maxW_fn} is written")
                CoreHistory.Wmax2_history.save_into_file_2(maxW2_fn)
                m_print.m_print(f"Max W file {maxW2_fn} is written")
            CoreHistory.InvokeOrigen(DECAY_HOURS)
            # m_print.m_print("FA surface:")
            dose_arrays = list()
            for reg_zone in range(130,140):
                m_print.m_print(f"Zone {reg_zone}:")
                dozeRates = CoreHistory.FADoseRate(CoreHistory.Wenvelope_axial, reg_zone,
                                                   CoreHistory.Wenvelope_src_spectrums)
                dr_uSv_hr = {t:dr*3600*1e6 for t,dr in zip(CoreHistory.tregs, dozeRates)}
                # m_print.m_print(dr_uSv_hr)
                dose_arrays.append([Svs*3600*1e6 for Svs in dozeRates])
            fn = os.path.join(os.curdir, ResultsDIRName, "doses_envelope.txt")
            write_data_file(fn, CoreHistory.tregs, *dose_arrays)

            req_cell = "1-1"
            dose_arrays_Svs = CoreHistory.FACellDoseRate(req_cell, DECAY_HOURS)
            fn = os.path.join(os.curdir, ResultsDIRName, f"{req_cell}.txt")
            dose_arrays_uSvhr = list()
            for reg_zone in dose_arrays_Svs:
                dose_arrays_uSvhr.append([Svs*3600*1e6 for Svs in dose_arrays_Svs[reg_zone]])
            write_data_file(fn, CoreHistory.tregs, *dose_arrays_uSvhr)


        except CoreProcException as ex:
            m_print.m_print("CoreHistory exception:")
            m_print.m_print(str(ex))

    finish_time = datetime.datetime.now()
    work_time = finish_time - start_time
    work_seconds = work_time / datetime.timedelta(
                        microseconds = 1) / 1.0e6
    m_print.m_print('Finish time is ',
          finish_time.strftime(TIME_FORMAT))
    m_print.m_print('Work time was ', work_seconds, ' seconds')
