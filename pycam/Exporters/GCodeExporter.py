# -*- coding: utf-8 -*-
"""
$Id$

Copyright 2010-2011 Lars Kruse <devel@sumpfralle.de>
Copyright 2008-2009 Lode Leroy

This file is part of PyCAM.

PyCAM is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

PyCAM is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with PyCAM.  If not, see <http://www.gnu.org/licenses/>.
"""

import decimal
import os
import pycam.Utils.log

log = pycam.Utils.log.get_logger()


DEFAULT_HEADER = ("G40 (disable tool radius compensation)",
                "G49 (disable tool length compensation)",
                "G80 (cancel modal motion)",
                "G54 (select coordinate system 1)",
                "G90 (disable incremental moves)")

DEFAULT_FOOTER = ("M2 (end program)")

PATH_MODES = {"exact_path": 0, "exact_stop": 1, "continuous": 2}
MAX_DIGITS = 12


def _get_num_of_significant_digits(number):
    """ Determine the number of significant digits of a float number. """
    # use only positive numbers
    number = abs(number)
    max_diff = 0.1 ** MAX_DIGITS
    if number <= max_diff:
        # input value is smaller than the smallest usable number
        return MAX_DIGITS
    elif number >= 1:
        # no negative number of significant digits
        return 0
    else:
        for digit in range(1, MAX_DIGITS):
            shifted = number * (10 ** digit)
            if shifted - int(shifted) < max_diff:
                return digit
        else:
            return MAX_DIGITS


def _get_num_converter(step_width):
    """ Return a float-to-decimal conversion function with a prevision suitable
    for the given step width.
    """
    digits = _get_num_of_significant_digits(step_width)
    format_string = "%%.%df" % digits
    return lambda number: decimal.Decimal(format_string % number)
    

class GCodeGenerator(object):

    NUM_OF_AXES = 3

    def __init__(self, destination, metric_units=True, safety_height=0.0,
            toggle_spindle_status=False, spindle_delay=3, header=None,
            comment=None, minimum_steps=None, touch_off_on_startup=False,
            touch_off_on_tool_change=False, touch_off_position=None,
            touch_off_rapid_move=0, touch_off_slow_move=1,
            touch_off_slow_feedrate=20, touch_off_height=0,
            touch_off_pause_execution=False, footer=None,
            alternate_line_comments=False, disable_tool_during_rapids=False,
            static_z_height=False, feedrate_with_moves=False, rapid_feedrate=0):
        if isinstance(destination, basestring):
            # open the file
            self.destination = file(destination,"w")
            self._close_stream_on_exit = True
        else:
            # assume that "destination" is something like a StringIO instance
            # or an open file
            self.destination = destination
            # don't close the stream if we did not open it on our own
            self._close_stream_on_exit = False
        self.use_alternate_line_comments = alternate_line_comments
        self.static_z_height = static_z_height
        self.feedrate_with_moves = feedrate_with_moves
        self.rapid_feedrate = rapid_feedrate
        self.disable_tool_during_rapids = disable_tool_during_rapids
        self.safety_height = safety_height
        self.toggle_spindle_status = toggle_spindle_status
        self.spindle_delay = spindle_delay
        self.comment = comment
        # define all axes steps and the corresponding formatters
        self._axes_formatter = []
        if not minimum_steps:
            # default: minimum steps for all axes = 0.0001
            minimum_steps = [0.0001]
        for i in range(self.NUM_OF_AXES):
            if i < len(minimum_steps):
                step_width = minimum_steps[i]
            else:
                step_width = minimum_steps[-1]
            conv = _get_num_converter(step_width)
            self._axes_formatter.append((conv(step_width), conv))
        self._finished = False
        if comment:
            self.add_comment(comment)
        if header is None:
            self.append(DEFAULT_HEADER)
        else:
            self.append(header)
        if metric_units:
            self.append("G21", "metric")
        else:
            self.append("G20", "imperial")
        if footer is None:
            self.footer = DEFAULT_FOOTER
        else:
            self.footer = footer

        self.last_position = [None, None, None]
        self.last_rapid = None
        self.last_tool_id = None
        self.last_feedrate = 100
        if touch_off_on_startup or touch_off_on_tool_change:
            self.store_touch_off_position(touch_off_position)
        self.touch_off_on_startup = touch_off_on_startup
        self.touch_off_on_tool_change = touch_off_on_tool_change
        self.touch_off_rapid_move = touch_off_rapid_move
        self.touch_off_slow_move = touch_off_slow_move
        self.touch_off_slow_feedrate = touch_off_slow_feedrate
        self.touch_off_pause_execution = touch_off_pause_execution
        self.touch_off_height = touch_off_height
        self._on_startup = True

    def run_touch_off(self, new_tool_id=None, force_height=None):
        # either "new_tool_id" or "force_height" should be specified
        self.append("")
        self.append("", "Start of touch off operation")
        self.append("G90", "disable incremental moves")
        self.append("G49", "disable tool offset compensation")
        self.append("G53 G0 Z#5163", "go to touch off position: z")
        self.append("G28", "go to final touch off position")
        self.append("G91", "enter incremental mode")
        self.append("F%f" % self.touch_off_slow_feedrate, "reduce feed rate during touch off")
        if self.touch_off_pause_execution:
            self.append("", "msg,Pausing before tool change")
            self.append("M0", "pause before touch off")
        # measure the current tool length
        if self.touch_off_rapid_move > 0:
            self.append("G0 Z-%f" % self.touch_off_rapid_move, "go down rapidly")
        self.append("G38.2 Z-%f" % self.touch_off_slow_move, "do the touch off")
        if not force_height is None:
            self.append("G92 Z%f" % force_height)
        self.append("G28", "go up again")
        if not new_tool_id is None:
            # compensate the length of the new tool
            self.append("#100=#5063", "store current tool length compensation")
            self.append("T%d M6" % new_tool_id)
            if self.touch_off_rapid_move > 0:
                self.append("G0 Z-%f" % self.touch_off_rapid_move, "go down rapidly")
            self.append("G38.2 Z-%f" % self.touch_off_slow_move, "do the touch off")
            self.append("G28", "go up again")
            # compensate the tool length difference
            self.append("G43.1 Z[#5063-#100]", "compensate the new tool length")
        self.append("F%f" % self.last_feedrate, "restore feed rate")
        self.append("G90", "disable incremental mode")
        # Move up to a safe height. This is either "safety height" or the touch
        # off start location. The highest value of these two is used.
        if self.touch_off_on_startup and not self.touch_off_height is None:
            touch_off_safety_height = self.touch_off_height + \
                    self.touch_off_slow_move + self.touch_off_rapid_move
            final_height = max(touch_off_safety_height, self.safety_height)
            self.append("G0 Z%.3f" % final_height)
        else:
            # We assume, that the touch off start position is _above_ the
            # top of the material. This is documented.
            # A proper ("safer") implementation would compare "safety_height"
            # with the touch off start location. But this requires "O"-Codes
            # which are only usable for EMC2 (probably).
            self.append("G53 G0 Z#5163", "go to touch off position: z")
        if self.touch_off_pause_execution:
            self.append("", "msg,Pausing after tool change")
            self.append("M0", "pause after touch off")
        self.append("", "End of touch off operation")
        self.append("")

    def store_touch_off_position(self, position):
        if position is None:
            self.append("G28.1", "store current position for touch off")
        else:
            self.append("#5161=%f" % position.x, "touch off position: x")
            self.append("#5162=%f" % position.y, "touch off position: y")
            self.append("#5163=%f" % position.z, "touch off position: z")

    def set_speed(self, feedrate=None, spindle_speed=None):
        if not feedrate is None:
            self.append("F%.5f" % feedrate)
            self.last_feedrate = feedrate
        if not spindle_speed is None:
            self.append("S%.5f" % spindle_speed)
            self.last_spindle_rate = spindle_speed

    def set_path_mode(self, mode, motion_tolerance=None,
            naive_cam_tolerance=None):
        result = []
        if mode == PATH_MODES["exact_path"]:
            result = ("G61", "exact path mode")
        elif mode == PATH_MODES["exact_stop"]:
            result = ("G61.1", "exact stop mode")
        elif mode == PATH_MODES["continuous"]:
            if motion_tolerance is None:
                result = ("G64", "continuous mode with maximum speed")
            elif naive_cam_tolerance is None:
                result = ("G64 P%f" % motion_tolerance,
                          "continuous mode with tolerance")
            else:
                result = ("G64 P%f Q%f" % (motion_tolerance, naive_cam_tolerance),
                          "continuous mode with tolerance and cleanup")
        else:
            raise ValueError("GCodeGenerator: invalid path mode (%s)" \
                    % str(mode))
        self.append(result[0], result[1])

    def add_moves(self, moves, tool_id=None, comment=None):
        if not comment is None:
            self.add_comment(comment)
        skip_safety_height_move = False
        if not tool_id is None:
            if self.last_tool_id == tool_id:
                # nothing to be done
                pass
            elif self.touch_off_on_tool_change and \
                    not (self.last_tool_id is None):
                self.run_touch_off(new_tool_id=tool_id)
                skip_safety_height_move = True
            else:
                self.append("T%d M6" % tool_id)
                if self._on_startup and self.touch_off_on_startup:
                    self.run_touch_off(force_height=self.touch_off_height)
                    skip_safety_height_move = True
                    self._on_startup = False
            self.last_tool_id = tool_id
        # move straight up to safety height
        if not skip_safety_height_move:
            self.add_move_to_safety()
        self.set_spindle_status(True)
        for pos, rapid in moves:
            self.add_move(pos, rapid=rapid)
        # go back to safety height
        self.add_move_to_safety()
        self.set_spindle_status(False)
        # make sure that all sections are independent of each other
        self.last_position = [None, None, None]
        self.last_rapid = None

    def set_spindle_status(self, status):
        if self.toggle_spindle_status:
            if status:
                self.append("M3", "start spindle")
            else:
                self.append("M5", "stop spindle")
            self.append("G04 P%d" % self.spindle_delay,
                        "wait for %d seconds" % self.spindle_delay)

    def add_move_to_safety(self):
        if self.static_z_height:
            return
        new_pos = [None, None, self.safety_height]
        self.add_move(new_pos, rapid=True)

    def add_move(self, position, rapid=False):
        """ add the GCode for a machine move to 'position'. Use rapid (G0) or
        normal (G01) speed.

        @value position: the new position
        @type position: Point or list(float)
        @value rapid: is this a rapid move?
        @type rapid: bool
        """
        new_pos = []
        indices = "xy" if self.static_z_height else "xyz"
        for index, attr in enumerate(indices):
            conv = self._axes_formatter[index][1]
            if hasattr(position, attr):
                value = getattr(position, attr)
            else:
                value = position[index]
            if value is None:
                new_pos.append(None)
            else:
                new_pos.append(conv(value))
        # check if there was a significant move
        no_diff = True
        for index in range(len(new_pos)):
            if new_pos[index] is None:
                continue
            if self.last_position[index] is None:
                no_diff = False
                break
            diff = abs(new_pos[index] - self.last_position[index])
            if diff >= self._axes_formatter[index][0]:
                no_diff = False
                break
        if no_diff:
            # we can safely skip this move
            return
        # compose the position string
        pos_string = []
        indices = "XY" if self.static_z_height else "XYZ"
        for index, axis_spec in enumerate(indices):
            if new_pos[index] is None:
                continue
            if not self.last_position or \
                    (new_pos[index] != self.last_position[index]):
                pos_string.append("%s%s" % (axis_spec, new_pos[index]))
                self.last_position[index] = new_pos[index]
        feedrate = 0
        if rapid == self.last_rapid and False:
            prefix = ""
        elif rapid:
            if self.disable_tool_during_rapids and not self.last_rapid:
                self.append("M5")
            prefix = "G0"
            feedrate = self.rapid_feedrate
        else:
            if self.disable_tool_during_rapids and self.last_rapid:
                self.append("M3 S%s" % self.last_spindle_rate)
            prefix = "G1"
            feedrate = self.last_feedrate
        self.last_rapid = rapid
        if self.feedrate_with_moves and feedrate:
            self.append("%s %s F%.5f" % (prefix, " ".join(pos_string), feedrate))
        else:
            self.append("%s %s" % (prefix, " ".join(pos_string)))

    def finish(self):
        self.add_move_to_safety()
        self.append(self.footer)
        self._finished = True

    def add_comment(self, comment):
        if isinstance(comment, basestring):
            lines = comment.split(os.linesep)
        else:
            lines = comment
        for line in lines:
            self.append(";%s" % line)

    def format_line_comment(self, comment):
        if self.use_alternate_line_comments:
            return ";%s" % comment
        else:
            return "(%s)" % comment

    def append(self, command, comment=""):
        if self._finished:
            raise TypeError("GCodeGenerator: can't add further commands to a " \
                    + "finished GCodeGenerator instance: %s" % str(command))

        if isinstance(command, basestring):
            if comment:
                command = "%s %s" % (command, self.format_line_comment(comment))
            command = [command]
        elif comment:
            self.destination.write(self.format_line_comment(comment) + os.linesep)

        for line in command:
            self.destination.write(line + os.linesep)

