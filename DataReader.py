#!/usr/bin/env python3

import datetime, itertools, re, math


RegZoneField = "RegZone"

class DataReaderException(Exception):
    pass

class IncorrectFileFormat(DataReaderException):
    def __init__(self, file_name, line_no, description):
        super().__init__()
        self.file_name = file_name
        self.line_no = line_no
        self.description = description

    def __str__(self):
        return ("File " + self.file_name +
                " has incorrect format, " +
                "line {n:d}: ".format(n = self.line_no) +
                self.description)

class FieldError(DataReaderException):
    def __init__(self, description):
        super().__init__()
        self.description = description

    def __str__(self):
        return ("Field error: " + self.description)

class TDataReader(object):

    def __init__(self, data_file_name):
        """ Reads data file trying to understand fields
            names and data types
        """

        # This is a local function for line parsing
        # provided separators are tabs
        def parse_line(line):
            field_pattern = r"[\t\n]"
            fields_list = re.split(field_pattern, line)[:-1]
            return fields_list

        # This is a local function for first line parsing
        # wich expected to be field names
        def parse_first_line(record):
            string_pattern = re.compile(r"^[^0-9]\S*$")
            fields = record
            if not all(string_pattern.match(field) is not None
                       for field in fields):
                fields = list()
            return fields

        # This is a local function for data line parsing
        def parse_data_line(record):
            string_pattern = re.compile(
                r"""^(?P<string>\S+)$""")
            int_number_pattern = re.compile(
                r"""^(?P<number>[-+]?[0-9]+)$""")
            float_number_pattern = re.compile(
                r"""^(?P<number>                   # To create symbolic group
                      [-+]?[0-9]*[.]?[0-9]+        # Mantissa part
                      ([eE][-+]?[0-9]+)?)$         # Optional exponent
                """, re.VERBOSE)
            datetime_pattern = re.compile(
                r"""^(?P<day>[0-9]{1,2})[.]        # Day
                     (?P<month>[0-9]{2})[.]        # Month
                     (?P<year>[0-9]{4})[ ]         # Year
                     (?P<hour>[0-9]{1,2})[:]       # Hours
                     (?P<min>[0-9]{2})[:]          # Minutes
                     (?P<sec>[0-9]{2})$            # Seconds
                 """, re.VERBOSE)

            data_tuple = tuple()

            for data_string in record:
                int_num_match   = int_number_pattern.match(data_string)
                float_num_match = float_number_pattern.match(data_string)
                datetime_match  = datetime_pattern.match(data_string)
                string_match    = string_pattern.match(data_string)
                # int matching is disabled for a while
                # because float is good enough
                #if int_num_match is not None:
                #    data_value = int(int_num_match.group("number"))
                if float_num_match is not None:
                    data_value = float(float_num_match.group("number"))
                elif datetime_match is not None:
                    day     = int(datetime_match.group("day"))
                    month   = int(datetime_match.group("month"))
                    year    = int(datetime_match.group("year"))
                    hours   = int(datetime_match.group("hour"))
                    minutes = int(datetime_match.group("min"))
                    seconds = int(datetime_match.group("sec"))
                    data_value = datetime.datetime(
                        year = year, month = month, day = day,
                        hour = hours, minute = minutes, second = seconds,
                        microsecond = 0)
                elif string_match is not None:
                    data_value = str(string_match.group("string"))
                else:
                    raise IncorrectFileFormat(data_file_name, line_no,
                                              "error parsing " + data_string)
                data_tuple += (data_value,)

            return data_tuple

        # This is a local function for data line type checking
        # against theinstanse's self.data_types tuple.
        # If there is more data than types in self.data_types
        # (but no more than in self.fields!) then self.data_types
        # is extended accordingly
        def check_data_type(data_tuple):
            if (len(data_tuple) > len(self.fields)) and (len(self.fields) > 0):
                raise IncorrectFileFormat(data_file_name, line_no,
                        "{fld_no:d} fields but {vals:d} data values ".format(
                            fld_no = len(self.fields), vals = len(data_tuple)))
            if len(data_tuple) > len(self.data_types):
                # Add new data types
                for data_item in itertools.islice(data_tuple,
                                    len(self.data_types), None):
                    self.data_types += (type(data_item),)
            for (data_item,data_type) in zip(data_tuple,self.data_types):
                if type(data_item) is not data_type:
                    raise IncorrectFileFormat(data_file_name, line_no,
            "type mismatch: {item:s} has type {dtype:s} but {exp:s} expected".format(
                                           item = str(data_item),
                                           dtype = str(type(data_item)),
                                           exp = str(data_type)))


        # This is __init__ function itself body
        self.fields = list()
        self.data_types = tuple()
        self.data_lines = int(0)
        self.raw_data = list()
        with open(file=data_file_name,
                  mode='r',
                  encoding='utf8') as data_file_object:
            line_no = 1

            # Skip the comment lines
            check_comment = True
            while check_comment:
                file_pos = data_file_object.tell()
                first_line = data_file_object.readline()
                line_no += 1
                if not first_line.startswith("#"):
                    check_comment = False
                    line_no -=1
                    break

            # Analyze the first meaningful line first :-)
            record = parse_line(first_line)
            self.fields = parse_first_line(record)
            if len(self.fields) > 0:
                line_no += 1
            else:
                # First line contains ordinary data
                data_file_object.seek(file_pos)

            for line in data_file_object:
                record = parse_line(line)
                data_tuple = parse_data_line(record)
                check_data_type(data_tuple)
                self.raw_data.append(data_tuple)
                line_no += 1
                self.data_lines += 1

    def find_field_index(self, field):
        if type(field) is str:
            try:
                field_index = self.fields.index(field)
            except ValueError as ex:
                raise FieldError("No {fld:s} field".format(fld = field))
        else:
            try:
                field_index = int(field)
            except ValueError as ex:
                raise FieldError("Field {fld:s} is not recognized".format(
                                 fld = field))
        return field_index

    def sort_data(self, field):
        field_index = self.find_field_index(field)
        self.raw_data.sort(key = lambda x: x[field_index])

    def interpolate_by_field(self, field, field_data):
        field_index = self.find_field_index(field)
        if self.data_types[field_index] is str:
            raise FieldError(("Can't interpolate on {fld:s} " +
                             "field of string type").format(fld = field))

        self.sort_data(field)
        for idx in range(len(self.raw_data)):
            if field_data < self.raw_data[idx][field_index]: break
        if idx == 0: idx = 1

        prev_field = self.raw_data[idx-1][field_index]
        next_field = self.raw_data[idx][field_index]
        prev_data = self.raw_data[idx-1]
        next_data = self.raw_data[idx]

        k = (field_data - prev_field) / (next_field - prev_field)
        value = [(prev_data_item + k * (next_data_item - prev_data_item))
                 if type(prev_data_item) is not str else 'string!'
                 for (prev_data_item, next_data_item) in zip(
                      prev_data, next_data)]

        return value

    def interpolate_by_rec_no(self, rec_no):
        ''' This function interpolates record by record number
            (index in self.raw_data). As it is interpolation,
            rec_no MAY be float number!!!
        '''
        n_records = len(self.raw_data)
        if rec_no < 0:
            rec_no = 0.0
        if rec_no > (n_records - 1):
            rec_no = n_records - 1
        idx = math.floor(rec_no)

        prev_data = self.raw_data[idx]
        next_data = self.raw_data[idx + 1]

        k = rec_no - idx
        value = [(prev_data_item + k * (next_data_item - prev_data_item))
                 if type(prev_data_item) is not str else 'string!'
                 for (prev_data_item, next_data_item) in zip(
                      prev_data, next_data)]

        return value

    def get_item_by_field(self, field_name, field_value):
        field_index = self.find_field_index(field_name)
        for rec in self.raw_data:
            if rec[field_index] == field_value:
                return rec
        raise KeyError

    def __len__(self):
        return len(self.raw_data)

    def __contains__(self, RegZone):
        field_index = self.find_field_index(RegZoneField)
        for rec in self.raw_data:
            if rec[field_index] == RegZone:
                return True
        return False

    def __getitem__(self, RegZone):
        field_index = self.find_field_index(RegZoneField)
        for rec in self.raw_data:
            if rec[field_index] == RegZone:
                return rec
        raise KeyError
