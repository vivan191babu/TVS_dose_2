""" Обрабатываем финовские файлы из MCU"""
import csv


def get_csv(d, c):
    c.writerow(d)


def find_starting_lin(f):
    """ Находим строку с которой начинаем считывать данные"""
    with open(f) as fin:
        list_fin = fin.readlines()
        count = len(list_fin)
        for n in range(0, count - 1000):
            text_fin = ' NUCLIDE:          MIXT, REACTION:           18, ENERGY:    0.00000E+00' '\n'
            if list_fin[n] == text_fin:
                starting_line = n
    return starting_line


mcu_core = []
file_core = []
with open('MCU_Core.csv') as csvfile:
    reader = csv.DictReader(csvfile)
    for line in reader:
        print(line)
        mcu_core.append(line)
        file_core.append(line['file'] + '.FIN')

process_names = file_core
# for i in range(1, len(mcu_core) + 1):
#     process_names.append('process' + str(i))
fieldnames = ['Cell', 'Zone', 'Pitch'] + process_names
d = dict.fromkeys(fieldnames)
print(d)

starting_line = find_starting_lin('MCU_FIN/' + file_core[0])

with open('R18.csv', 'w', newline='') as cfile:
    writer = csv.DictWriter(cfile, fieldnames=fieldnames)
    writer.writeheader()
    with open('Cell.csv') as csvfile:
        reader = csv.reader(csvfile)
        start = 21

        for line in reader:
            d[fieldnames[0]] = line[1]   # Cell
            for reg_zone in range(0, 10):
                d[fieldnames[1]] = str(int(line[0]) + reg_zone)    # zone
                d[fieldnames[2]] = reg_zone                        # pitch
                number_name = 3
                """ Обход по файлам FIN"""
                for k in file_core:
                    with open('MCU_FIN/' + k) as fin:
                        list_fin = fin.readlines()
                        d[fieldnames[number_name]] = list_fin[starting_line + start][16:28]  # fission_reaction_rate
                        number_name += 1
                get_csv(d, writer)
                start += 1
print(d)



    #
    #
    #
    #             continue
    #

#
# writer.writerow({'Cell': 'Baked', 'Zone': 'Beans'})
