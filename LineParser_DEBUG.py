import re

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


def parse_data_line(record):
    string_pattern = re.compile(
        r"""^(?P<string>[^0-9]\S+)$""")
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
             (?P<sec>[0-9]{2})[.]          # Seconds
             (?P<msec>[0-9]{3})$           # Milliseconds             
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
            msecs   = int(datetime_match.group("msec"))
            data_value = datetime.datetime(
                year = year, month = month, day = day,
                hour = hours, minute = minutes, second = seconds,
                microsecond = 1000 * msecs)
        elif string_match is not None:
            data_value = str(string_match.group("string"))
        else:
            raise IncorrectFileFormat("qq", 38,
                                      "error parsing " + data_string)
        data_tuple += (data_value,)

    return data_tuple

line = "P+M+C	299	241	14103MP_P+M+C.FIN"
data = parse_data_line(line)
print(data)
