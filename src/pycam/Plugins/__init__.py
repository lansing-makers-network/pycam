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

import os
import imp
import inspect
# TODO: load these modules only on demand
import gtk
import gobject

import pycam.Utils.log
import pycam.Utils.locations


_log = pycam.Utils.log.get_logger()


class PluginBase(object):

    UI_FILE = None
    DEPENDS = []
    ICONS = {}
    ICON_SIZE = 23

    def __init__(self, core, name):
        self.enabled = True
        self.name = name
        self.core = core
        self.gui = None
        self.log = _log
        if self.UI_FILE:
            gtk_build_file = pycam.Utils.locations.get_ui_file_location(
                    self.UI_FILE)
            if gtk_build_file:
                self.gui = gtk.Builder()
                try:
                    self.gui.add_from_file(gtk_build_file)
                except RuntimeError:
                    self.gui = None
        for key in self.ICONS:
            icon_location = pycam.Utils.locations.get_ui_file_location(
                    self.ICONS[key])
            if icon_location:
                try:
                    pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
                            icon_location, self.ICON_SIZE, self.ICON_SIZE)
                except gobject.GError:
                    self.ICONS[key] = None
                else:
                    self.ICONS[key] = pixbuf
            else:
                self.log.debug("Failed to locate icon: %s" % self.ICONS[key])
                self.ICONS[key] = None

    def setup(self):
        raise NotImplementedError(("Module %s (%s) does not implement " + \
                "'setup'") % (self.name, __file__))

    def teardown(self):
        raise NotImplementedError("Module %s (%s) does not implement " + \
                "'teardown'" % (self.name, __file__))


class PluginManager(object):

    def __init__(self, core):
        self.core = core
        self.modules = {}

    def import_plugins(self, directory=None):
        if directory is None:
            directory = os.path.dirname(__file__)
        try:
            files = os.listdir(directory)
        except OSError:
            return
        plugins = []
        for filename in files:
            if filename.endswith(".py") and \
                    (filename.lower() != "__init__.py") and \
                    os.path.isfile(os.path.join(directory, filename)):
                mod_name = filename[0:-(len(".py"))]
                try:
                    mod_file, mod_filename, mod_desc = imp.find_module(
                            mod_name, [directory])
                    full_mod_name = "pycam.Plugins.%s" % mod_name
                    mod = imp.load_module(full_mod_name, mod_file,
                            mod_filename, mod_desc)
                except ImportError:
                    _log.info("Skipping broken plugin %s" % os.path.join(
                            directory, filename))
                    continue
                for attr in dir(mod):
                    item = getattr(mod, attr)
                    if inspect.isclass(item) and hasattr(item, "setup"):
                        plugin_name = "%s.%s" % (os.path.basename(
                                mod_filename)[0:-len(".py")], attr)
                        plugins.append((item, mod_filename, attr))
        try_again = True
        while try_again:
            try_again = False
            postponed_plugins = []
            for plugin, filename, name in plugins:
                for dep in plugin.DEPENDS:
                    if not dep in self.modules and \
                            not "%s.%s" % (dep, dep) in self.modules:
                        # dependency not loaded, yet
                        postponed_plugins.append((plugin, filename, name))
                        break
                else:
                    self._load_plugin(plugin, filename, name)
                    try_again = True
            plugins = postponed_plugins
        for plugin, filename, name in plugins:
            # module failed to load due to missing dependencies
            _log.info("Skipping plugin '%s' due to missing dependencies: %s" % \
                    (name, ", ".join(plugin.DEPENDS)))

    def _load_plugin(self, obj, filename, plugin_name):
        if plugin_name in self.modules:
            _log.debug("Cleaning up module %s" % plugin_name)
            self.modules[plugin_name].teardown()
        _log.debug("Initializing module %s (%s)" % (plugin_name, filename))
        new_plugin = obj(self.core, plugin_name)
        if not new_plugin.setup():
            raise RuntimeError("Failed to load plugin '%s'" % str(plugin_name))
        else:
            self.modules[plugin_name] = new_plugin


class ListPluginBase(PluginBase, list):

    ACTION_UP, ACTION_DOWN, ACTION_DELETE, ACTION_CLEAR = range(4)

    def __init__(self, *args, **kwargs):
        super(ListPluginBase, self).__init__(*args, **kwargs)
        self._update_model_funcs = []
        def get_function(func_name):
            return lambda *args, **kwargs: self._change_wrapper(func_name, *args, **kwargs)
        for name in "append", "insert", "pop", "reverse", "sort":
            setattr(self, name, get_function(name))

    def _change_wrapper(self, func_name, *args, **kwargs):
        value = getattr(super(ListPluginBase, self), func_name)(*args, **kwargs)
        self._update_model()
        return value

    def _get_selected(self, modelview, index=False, force_list=False):
        if hasattr(modelview, "get_selection"):
            # a treeview selection
            selection = modelview.get_selection()
            selection_mode = selection.get_mode()
            paths = selection.get_selected_rows()[1]
        else:
            # an iconview
            selection_mode = modelview.get_selection_mode()
            paths = modelview.get_selected_items()
        if index:
            get_result = lambda path: path[0]
        else:
            get_result = lambda path: self[path[0]]
        if (selection_mode == gtk.SELECTION_MULTIPLE) or force_list:
            result = []
            for path in paths:
                result.append(get_result(path))
        else:
            if not paths:
                return None
            else:
                result = get_result(paths[0])
        return result

    def _update_model(self):
        for update_func in self._update_model_funcs:
            update_func()

    def register_model_update(self, func):
        self._update_model_funcs.append(func)

    def unregister_model_update(self, func):
        if func in self._update_model_funcs:
            self._update_model_funcs.remove(func)

    def _list_action(self, *args):
        # the second-to-last paramater should be the model view
        modelview = args[-2]
        # the last parameter should be the action (ACTION_UP|DOWN|DELETE|CLEAR)
        action = args[-1]
        if not action in (self.ACTION_UP, self.ACTION_DOWN,
                self.ACTION_DELETE, self.ACTION_CLEAR):
            self.log.info("Invalid action for ListPluginBase.list_action: " + \
                    str(action))
            return
        selected_items = self._get_selected(modelview, index=True,
                force_list=True)
        selected_items.sort()
        if action in (self.ACTION_DOWN, self.ACTION_DELETE):
            selected_items.sort(reverse=True)
        new_selection = []
        if action == self.ACTION_CLEAR:
            while len(self) > 0:
                self.pop(0)
        else:
            for index in selected_items:
                if action == self.ACTION_UP:
                    if index > 0:
                        item = self.pop(index)
                        self.insert(index - 1, item)
                        new_selection.append(index - 1)
                elif action == self.ACTION_DOWN:
                    if index < len(self) - 1:
                        item = self.pop(index)
                        self.insert(index + 1, item)
                        new_selection.append(index + 1)
                elif action == self.ACTION_DELETE:
                    self.pop(index)
                    new_selection.append(min(index, len(self) - 1))
                else:
                    pass
        self._update_model()
        if hasattr(modelview, "get_selection"):
            selection = modelview.get_selection()
        else:
            selection = modelview
        selection.unselect_all()
        for index in new_selection:
            selection.select_path((index,))

    def _update_list_action_button_state(self, *args):
        modelview = args[-3]
        action = args[-2]
        button = args[-1]
        paths = self._get_selected(modelview, index=True, force_list=True)
        if action == self.ACTION_CLEAR:
            button.set_sensitive(len(self) > 0)
        elif not paths:
            button.set_sensitive(False)
        else:
            if action == self.ACTION_UP:
                button.set_sensitive(not 0 in paths)
            elif action == self.ACTION_DOWN:
                button.set_sensitive(not (len(self) - 1) in paths)
            else:
                button.set_sensitive(True)

    def register_list_action_button(self, action, modelview, button):
        if hasattr(modelview, "get_selection"):
            # a treeview
            selection = modelview.get_selection()
            selection.connect("changed", self._update_list_action_button_state,
                    modelview, action, button)
        else:
            modelview.connect("selection-changed",
                    self._update_list_action_button_state, modelview, action,
                    button)
        model = modelview.get_model()
        for signal in ("row-changed", "row-deleted",
                "row-has-child-toggled", "row-inserted", "rows-reordered"):
            model.connect(signal, self._update_list_action_button_state,
                    modelview, action, button)
        button.connect("clicked", self._list_action, modelview, action)
