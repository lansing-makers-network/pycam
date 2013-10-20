# -*- coding: utf-8 -*-
"""
$Id$

Copyright 2011 Lars Kruse <devel@sumpfralle.de>

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


import pycam.Plugins


class GCodeStartStop(pycam.Plugins.PluginBase):

    DEPENDS = ["GCodePreferences"]
    CATEGORIES = ["GCode"]
    UI_FILE = "gcode_start_stop.ui"

    def setup(self):
        if self.gui:
            box = self.gui.get_object("StartStopBox")
            box.unparent()

            self.core.register_ui("gcode_preferences", "Start/Stop",
                    box, weight=71)
            for objname, setting in (
                    ("GCodeStartCode", "gcode_header"),
                    ("GCodeStopCode", "gcode_footer")):
                obj = self.gui.get_object(objname)
                self.core.add_item(setting,
                                   lambda x=obj: self.get_value(x),
                                   obj.get_buffer().set_text)
        return True

    def get_value(self, text_view):
        buffer = text_view.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter())

    def teardown(self):
        if self.gui:
            self.core.unregister_ui("gcode_preferences",
                                    self.gui.get_object("StartStopBox"))
            for setting in ("gcode_header", "gcode_footer"):
                del self.core[setting]
