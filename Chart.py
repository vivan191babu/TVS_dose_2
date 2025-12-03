#!/usr/bin/env python3

import tkinter, tkinter.ttk
import math, logging, os
import CreateLogsDir

ChartAreaSize = (800, 400)
XChartPad = 100
YChartPad = 20
XYReserv = 5
ChartXGrids = 10
ChartYGrids = 10
FontFamily = 'Arial'
FontSize   = 12
LogAreaSize = (35, 20)

# Uncomment for detailed debug info
#log_level = logging.DEBUG
log_level = logging.INFO


class ChartMainWindow(tkinter.Frame):
    _trackHist = list()
    _x_grids = list()
    _y_grids = list()
    _x_marks = list()
    _y_marks = list()
    
    def line_plotter(self, xs, ys, **opts):
        xy_list = list()
        for (x, y) in zip(xs, ys):
            xy_list.append(x)
            xy_list.append(y)
        objId = self._chart_area.create_line(*xy_list, **opts)
        self._trackHist.append(objId)
        
    def circle_plotter(self, xs, ys, radius, **opts):
        for (x, y) in zip(xs, ys):
            objId = self._chart_area.create_oval(x - radius,
                   y - radius, x + radius, y + radius, **opts)
            self._trackHist.append(objId)

    def triangle_plotter(self, xs, ys, side, **opts):
        s3 = math.sqrt(3.0)
        delta_x = side / 2.0
        delta_y = side / (2.0 * s3)
        delta_y2 = side * (s3 / 2.0 - 1.0 / (2.0 * s3))
        for (x, y) in zip(xs, ys):
            x1 = x - delta_x
            y1 = y - delta_y
            x2 = x
            y2 = y + delta_y2
            x3 = x + delta_x
            y3 = y1
            objId = self._chart_area.create_polygon(
                      x1, y1, x2, y2, x3, y3, **opts)
            self._trackHist.append(objId)

    def __init__(self, parent):
        super(ChartMainWindow, self).__init__(parent)
        self._parent = parent
        self.grid(row = 0, column = 0)
        self._chart_area = tkinter.Canvas(self, bg='white',
             width = ChartAreaSize[0], height = ChartAreaSize[1])
        self._chart_area.grid(row = 0, column = 0,
                  sticky=tkinter.N+tkinter.E+tkinter.S+tkinter.W)
        self._log_yScroll = tkinter.ttk.Scrollbar(self, orient = tkinter.VERTICAL)
        self._log_yScroll.grid(row = 0, column = 2,
                               sticky = tkinter.N + tkinter.S)
        self._log_area = tkinter.Listbox(self, bg='white',
             width = LogAreaSize[0], height = LogAreaSize[1],
             activestyle = 'none', font = (FontFamily, str(FontSize)),
                            yscrollcommand = self._log_yScroll.set)
        self._log_area.grid(row = 0, column = 1,
                  sticky=tkinter.N+tkinter.E+tkinter.S+tkinter.W)
        self._log_yScroll['command'] = self._log_area.yview
        
        log_record_format = '%(asctime)s %(levelname)s: %(message)s'
        log_time_format   = '%d.%m.%Y %H:%M:%S'
        logger_name = 'Chart'
        log_file_name = os.path.join(CreateLogsDir.LogsDir, logger_name + '.log')
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(log_level)
        log_handler = logging.FileHandler(filename = log_file_name,
                                          mode = 'at',
                                          encoding = 'utf8')
        log_formatter = logging.Formatter(fmt = log_record_format,
                                          datefmt  = log_time_format,
                                          style    = '%')
        log_handler.setFormatter(log_formatter)
        self.logger.addHandler(log_handler)
        
        self.logger.info('ChartMainWindow created')

    def del_prev_charts(self):
        if self._trackHist is not None:
            for objId in self._trackHist:
                self._chart_area.delete(objId)
        self._trackHist = list()

    def del_log(self):
        log_lines = self._log_area.size()
        if log_lines > 0:
            self._log_area.delete(0, log_lines - 1)

    def log_line(self, *lines):
        self._log_area.insert(tkinter.END, *lines)

    def draw_grid(self, x_min, x_max, y_min, y_max):

        def round_order_up(x, order):
            x_norm = x / math.pow(10, order)
            x_norm_round = round(x_norm + 0.05, 1)
            x_rounded = x_norm_round * math.pow(10, order)
            return x_rounded
            
        def round_order_dwn(x, order):
            x_norm = x / math.pow(10, order)
            x_norm_round = round(x_norm - 0.05, 1)
            x_rounded = x_norm_round * math.pow(10, order)
            return x_rounded

        pwr_x = math.ceil(math.log10(x_max - x_min))
        pwr_y = math.ceil(math.log10(y_max - y_min))
        corr_x = (x_max - x_min) / 1.0e10
        corr_y = (y_max - y_min) / 1.0e10
        self._chart_x_min = round_order_dwn(x_min + corr_x, pwr_x)
        self._chart_x_max = round_order_up(x_max - corr_x, pwr_x)
        self._chart_y_min = round_order_dwn(y_min + corr_y, pwr_y)
        self._chart_y_max = round_order_up(y_max - corr_y, pwr_y)
        chart_x_step = (self._chart_x_max - self._chart_x_min) / ChartXGrids
        chart_y_step = (self._chart_y_max - self._chart_y_min) / ChartYGrids

        self._scale_x = ((ChartAreaSize[0] - XChartPad - XYReserv) /
                         (self._chart_x_max - self._chart_x_min))
        self._scale_y = ((ChartAreaSize[1] - YChartPad - XYReserv) /
                         (self._chart_y_max - self._chart_y_min))

        self.logger.debug('Given x_min={} x_max={}'.format(
                                              x_min, x_max))
        self.logger.debug('chart_x_min={} chart_x_max={}'.format(
                            self._chart_x_min, self._chart_x_max))
        self.logger.debug('Given y_min={} y_max={}'.format(
                                              y_min, y_max))
        self.logger.debug('chart_y_min={} chart_y_max={}'.format(
                            self._chart_y_min, self._chart_y_max))

        # Delete previous grids
        if self._x_grids is not None:
            for objId in self._x_grids:
                self._chart_area.delete(objId)
        if self._y_grids is not None:
            for objId in self._y_grids:
                self._chart_area.delete(objId)
        if self._x_marks is not None:
            for objId in self._x_marks:
                self._chart_area.delete(objId)
        if self._y_marks is not None:
            for objId in self._y_marks:
                self._chart_area.delete(objId)

        # Draw new grids
        for x_grid in range(ChartXGrids + 1):
            x = x_grid * chart_x_step * self._scale_x + XChartPad
            y = XYReserv
            x2, y2 = x, ChartAreaSize[1] - YChartPad * 0.9
            objId = self._chart_area.create_line(x, y, x2, y2, fill='black')
            self._x_grids.append(objId)
            if pwr_x <= 0:
                format_spec = '0:.{}f'.format(int(abs(pwr_x)) + 2)
            else:
                format_spec = '0:{}.1f'.format(int(pwr_x))
            format_spec = '{' + format_spec + '}'
            mark_text = format_spec.format(self._chart_x_min +
                                           x_grid * chart_x_step)
            textObjId = self._chart_area.create_text(x, y2 + FontSize / 2 + 2,
                         text = mark_text, font = (FontFamily, str(FontSize)))
            self._x_marks.append(textObjId)

        for y_grid in range(ChartYGrids + 1):
            x,  y  = XChartPad * 0.9, (ChartAreaSize[1] -
                     (y_grid * chart_y_step * self._scale_y + YChartPad))
            x2, y2 = ChartAreaSize[0] - XYReserv, y
            objId = self._chart_area.create_line(x, y, x2, y2, fill='black')
            self._y_grids.append(objId)
            if pwr_y <= 0:
                format_spec = '0:.{}f'.format(int(abs(pwr_y)) + 2)
            else:
                format_spec = '0:{}.0f'.format(int(pwr_y))
            format_spec = '{' + format_spec + '}'
            mark_text = format_spec.format(self._chart_y_min +
                                           y_grid * chart_y_step)
            textObjId = self._chart_area.create_text(XChartPad * 0.5, y,
                         text = mark_text, font = (FontFamily, str(FontSize)))
            self._y_marks.append(textObjId)
            
    def plotValues(self, xs, ys, plotter):
        ''' Takes values to plot from xs and ys vectors
        '''
        xs_plot = list()
        ys_plot = list()
        for (x, y) in zip(xs, ys):
            x_plot = (x - self._chart_x_min) * self._scale_x + XChartPad
            y_plot = (ChartAreaSize[1] -
                      ((y - self._chart_y_min) * self._scale_y + YChartPad))
            self.logger.debug('x={} y={} x_plot={} y_plot={}'.format(
                                                x, y, x_plot, y_plot))
            xs_plot.append(x_plot)
            ys_plot.append(y_plot)
        plotter(xs_plot, ys_plot)

    def quit(self, event = None):
        self._parent.destroy()

