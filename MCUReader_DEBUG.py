#!/usr/bin/env python3

import DataReader
import datetime, re

TIME_FORMAT = '%d.%m.%Y %H:%M:%S'

FINfn = "MCU_FIN\\14103MP_P+M.FIN"

def print_list(L):
    if type(L) is list:
        print(f"List of {len(L)} elements:")
        for n,e in enumerate(L):
            print(f"{n}: {e}")
    else:
        print(f"L is not a list, type(L) is {type(L)}")

def print_dict(D):
    if type(D) is dict or type(D) is types.MappingProxyType:
        print(f"Dictionary of {len(D)} elements:")
        for n,(k,v) in enumerate(D.items()):
            print(f"{n}: {k}: {v} id={id(v):016X}")
    else:
        print(f"D is not a dictionary, type(D) is {type(D)}")


ZoneKey = "MCU zone"
CellKey = "Cell"
ChannelKey = "Channel"
PitchKey = "Pitch"
MeanKey = "Mean"
StdevKey = "Stdev"
RecUsefullKey = "Usefull"
R18CellField = "Cell"
R18PitchField = "Pitch"
R3ChannelField = "Channel"
# "RegZone" field name being index field is defined in DataReader.py

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

def AlgorithmInit(FINfn):

    zones_line = " -- ZONES --"
    objects_line = " -- OBJECTS --"
    hdr_line = "         Zone          Mean        StdDev"
    R3_line  = " NUCLIDE:          MIXT, REACTION:            3, ENERGY:    0.00000E+00"
    R18_line = " NUCLIDE:          MIXT, REACTION:           18, ENERGY:    0.00000E+00"

    
    MCU_FAs_fn = "MCU_FAs.txt"
    FAs_reader = DataReader.TDataReader(MCU_FAs_fn)

    MCU_detectors_fn = "MCU_detectors.txt"
    MCU_detectors_reader = DataReader.TDataReader(MCU_detectors_fn)

    print("FAs Fields: ")
    print_list(FAs_reader.fields)
    print(f"Total {len(FAs_reader.raw_data)} data records")
    
    R3Lines2find = 3
    R18Lines2find = 3
    R3Records = 0; R18Records = 0
    R3Over = False; R18Over = False
    with open(file = FINfn, mode='r', encoding='utf8') as FINfileObject:
        finLineNo = 0
        for finLine in FINfileObject:
            finLineNo += 1
            if finLine.startswith(zones_line):
                print("ZONES found")
                R3Lines2find -= 1
                R18Lines2find -= 1
                continue
            if finLine.startswith(objects_line):
                print("OBJECTS found")
                R3Lines2find += 10
                R18Lines2find += 10
                continue
            if finLine.startswith(R3_line):
                print("MIX R3 found")
                R3Lines2find -= 1
                continue
            if finLine.startswith(R18_line):
                print("MIX R18 found")
                R18Lines2find -= 1
                continue
            if R3Lines2find == 1 and finLine.startswith(hdr_line):
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
                    R3Records += 1
            if R18Lines2find == 1 and finLine.startswith(hdr_line):
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
                    R18Records += 1
            if R3Over and R18Over:
                break

    print(f"Totally {R3Records} R3 records")
    print(f"Totally {R18Records} R18 records")
    
if __name__ == "__main__":
    start_time = datetime.datetime.now()
    print('Start time is ',
          start_time.strftime(TIME_FORMAT))

    AlgorithmInit(FINfn)
    
    finish_time = datetime.datetime.now()
    work_time = finish_time - start_time
    work_seconds = work_time / datetime.timedelta(
                        microseconds = 1) / 1.0e6
    print('Finish time is ',
          finish_time.strftime(TIME_FORMAT))
    print('Work time was ', work_seconds, ' seconds')
    
