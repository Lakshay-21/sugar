"""Base class for Python-coded activities

This is currently the only reference for what an 
activity must do to participate in the Sugar desktop.
"""
# Copyright (C) 2006, Red Hat, Inc.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place - Suite 330,
# Boston, MA 02111-1307, USA.

import logging
import os
import time

import gtk, gobject

from sugar.presence import presenceservice
from sugar.activity.activityservice import ActivityService
from sugar.activity import bundleregistry
from sugar.graphics.window import Window
from sugar.graphics.toolbox import Toolbox
from sugar.graphics.toolbutton import ToolButton
from sugar.datastore import datastore
from sugar import profile

class ActivityToolbar(gtk.Toolbar):
    def __init__(self, activity):
        gtk.Toolbar.__init__(self)

        self._activity = activity
        activity.connect('shared', self._activity_shared_cb)
        activity.connect('joined', self._activity_shared_cb)

        if activity.jobject:
            self.title = gtk.Entry()
            self.title.set_size_request(int(gtk.gdk.screen_width() / 6), -1)
            self.title.set_text(activity.jobject['title'])
            self.title.connect('focus-out-event', self._title_focus_out_event_cb)
            self._add_widget(self.title)

            activity.jobject.connect('updated', self._jobject_updated_cb)

        separator = gtk.SeparatorToolItem()
        separator.props.draw = False
        separator.set_expand(True);
        self.insert(separator, -1)
        separator.show()

        self.share = ToolButton('stock-share-mesh')
        self.share.connect('clicked', self._share_clicked_cb)
        self.insert(self.share, -1)
        if activity.get_shared():
            self.share.set_sensitive(False)
        self.share.show()

        separator = gtk.SeparatorToolItem()
        separator.props.draw = False
        self.insert(separator, -1)
        separator.show()

        self.close = ToolButton('window-close')
        self.close.connect('clicked', self._close_clicked_cb)
        self.insert(self.close, -1)
        self.close.show()

    def _share_clicked_cb(self, button):
        self._activity.share()

    def _close_clicked_cb(self, button):
        self._activity.close()

    def _jobject_updated_cb(self, jobject):
        self.title.set_text(jobject['title'])

    def _title_focus_out_event_cb(self, entry, event):
        if self._activity.jobject['title'] != self.title.get_text():
            self._activity.jobject['title'] = self.title.get_text()
            self._activity.save()

    def _add_widget(self, widget, expand=False):
        tool_item = gtk.ToolItem()
        tool_item.set_expand(expand)

        tool_item.add(widget)
        widget.show()

        self.insert(tool_item, -1)
        tool_item.show()

    def _activity_shared_cb(self, activity):
        self.share.set_sensitive(False)

class EditToolbar(gtk.Toolbar):
    def __init__(self):
        gtk.Toolbar.__init__(self)

        self.undo = ToolButton('edit-undo')
        self.insert(self.undo, -1)
        self.undo.show()

        self.redo = ToolButton('edit-redo')
        self.insert(self.redo, -1)
        self.redo.show()

        separator = gtk.SeparatorToolItem()
        separator.set_draw(True)
        self.insert(separator, -1)
        separator.show()

        self.copy = ToolButton('edit-copy')
        self.insert(self.copy, -1)
        self.copy.show()

        self.paste = ToolButton('edit-paste')
        self.insert(self.paste, -1)
        self.paste.show()

class ActivityToolbox(Toolbox):
    def __init__(self, activity):
        Toolbox.__init__(self)
        
        self._activity_toolbar = ActivityToolbar(activity)
        self.add_toolbar('Activity', self._activity_toolbar)
        self._activity_toolbar.show()

    def get_activity_toolbar(self):
        return self._activity_toolbar

class Activity(Window, gtk.Container):
    """Base Activity class that all other Activities derive from."""
    __gtype_name__ = 'SugarActivity'

    __gsignals__ = {
        'shared': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, ([])),
        'joined': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, ([]))
    }

    __gproperties__ = {
        'active': (bool, None, None, False, gobject.PARAM_READWRITE)
    }

    def __init__(self, handle, create_jobject=True):
        """Initialise the Activity 
        
        handle -- sugar.activity.activityhandle.ActivityHandle
            instance providing the activity id and access to the 
            presence service which *may* provide sharing for this 
            application

        create_jobject -- boolean
            define if it should create a journal object if we are
            not resuming

        Side effects: 
        
            Sets the gdk screen DPI setting (resolution) to the 
            Sugar screen resolution.
            
            Connects our "destroy" message to our _destroy_cb
            method.
        
            Creates a base gtk.Window within this window.
            
            Creates an ActivityService (self._bus) servicing
            this application.
        """
        Window.__init__(self)

        self.connect('destroy', self._destroy_cb)

        self._active = False
        self._activity_id = handle.activity_id
        self._pservice = presenceservice.get_instance()
        self._shared_activity = None
        self._share_id = None
        self._join_id = None

        shared_activity = handle.get_shared_activity()
        if shared_activity:
            # Join an existing instance of this activity on the network
            self._shared_activity = shared_activity
            self._join_id = self._shared_activity.connect("joined", self._internal_joined_cb)
            if not self._shared_activity.props.joined:
                self._shared_activity.join()
            else:
                self._internal_joined_cb(self._shared_activity, True, None)

        self._bus = ActivityService(self)

        if handle.object_id:
            self.jobject = datastore.get(handle.object_id)
            self.jobject.object_id = ''
            del self.jobject['ctime']
            del self.jobject['mtime']
        elif create_jobject:
            logging.debug('Creating a jobject.')
            self.jobject = datastore.create()
            self.jobject['title'] = '%s %s' % (get_bundle_name(), 'Activity')
            self.jobject['activity'] = self.get_service_name()
            self.jobject['icon'] = self._get_icon()
            self.jobject['keep'] = '0'
            self.jobject['buddies'] = ''
            self.jobject['preview'] = ''
            self.jobject['icon-color'] = profile.get_color().to_string()
            self.jobject.file_path = ''
            datastore.write(self.jobject,
                    reply_handler=self._internal_jobject_create_cb,
                    error_handler=self._internal_jobject_error_cb)
        else:
            self.jobject = None

    def do_set_property(self, pspec, value):
        if pspec.name == 'active':
            if self._active != value:
                self._active = value
                if not self._active and self.jobject:
                    self.save()

    def do_get_property(self, pspec):
        if pspec.name == 'active':
            return self._active

    def _internal_jobject_create_cb(self):
        pass

    def _internal_jobject_error_cb(self, err):
        logging.debug("Error creating activity datastore object: %s" % err)

    def read_file(self):
        """
        Subclasses implement this method if they support resuming objects from
        the journal. Can access the object through the jobject attribute.
        """
        raise NotImplementedError

    def write_file(self):
        """
        Subclasses implement this method if they support saving data to objects
        in the journal. Can access the object through the jobject attribute.
        """
        raise NotImplementedError

    def _internal_save_cb(self):
        pass

    def _internal_save_error_cb(self, err):
        logging.debug("Error saving activity object to datastore: %s" % err)

    def save(self):
        """Request that the activity is saved to the Journal."""
        try:
            self.jobject.file_path = os.path.join('/tmp', '%i.txt' % time.time())
            self.write_file()
        except NotImplementedError:
            self.jobject.file_path = ''
        datastore.write(self.jobject,
                reply_handler=self._internal_save_cb,
                error_handler=self._internal_save_error_cb)

    def _internal_joined_cb(self, activity, success, err):
        """Callback when join has finished"""
        self._shared_activity.disconnect(self._join_id)
        self._join_id = None
        if not success:
            logging.debug("Failed to join activity: %s" % err)
            return
        self.present()
        self.emit('joined')

    def get_service_name(self):
        """Gets the activity service name."""
        return os.environ['SUGAR_BUNDLE_SERVICE_NAME']

    def get_shared(self):
        """Returns TRUE if the activity is shared on the mesh."""
        if not self._shared_activity:
            return False
        return self._shared_activity.props.joined

    def get_id(self):
        """Get the unique activity identifier."""
        return self._activity_id

    def _internal_share_cb(self, ps, success, activity, err):
        self._pservice.disconnect(self._share_id)
        self._share_id = None
        if not success:
            logging.debug('Share of activity %s failed: %s.' % (self._activity_id, err))
            return
        logging.debug('Share of activity %s successful.' % self._activity_id)
        self._shared_activity = activity
        self.emit('shared')

    def share(self):
        """Request that the activity be shared on the network."""
        if self._shared_activity and self._shared_activity.props.joined:
            raise RuntimeError("Activity %s already shared." % self._activity_id)
        logging.debug('Requesting share of activity %s.' % self._activity_id)
        self._share_id = self._pservice.connect("activity-shared", self._internal_share_cb)
        self._pservice.share_activity(self)

    def execute(self, command, args):
        """Execute the given command with args"""
        return False

    def _destroy_cb(self, window):
        """Destroys our ActivityService and sharing service"""
        if self._bus:
            del self._bus
            self._bus = None
        if self._shared_activity:
            self._shared_activity.leave()

    def close(self):
        if self.jobject:
            try:
                self.save()
            except:
                self.destroy()
                raise
        self.destroy()

    def _get_icon(self):
        registry = bundleregistry.get_registry()
        return registry.get_bundle(self.get_service_name()).get_icon()

def get_bundle_name():
    """Return the bundle name for the current process' bundle
    """
    return os.environ['SUGAR_BUNDLE_NAME']
    
def get_bundle_path():
    """Return the bundle path for the current process' bundle
    """
    return os.environ['SUGAR_BUNDLE_PATH']
