# Copyright (c) 2017 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.
import os
from functools import partial

import sgtk
from sgtk import TankError
from sgtk.util.filesystem import create_valid_filename

from krita import Krita

__author__ = "Diego Garcia Huerta"
__contact__ = "https://www.linkedin.com/in/diegogh/"


HookBaseClass = sgtk.get_hook_baseclass()


class KritaSessionCollector(HookBaseClass):
    """
    Collector that operates on the krita session. Should inherit from the basic
    collector hook.
    """

    @property
    def settings(self):
        """
        Dictionary defining the settings that this collector expects to receive
        through the settings parameter in the process_current_session and
        process_file methods.

        A dictionary on the following form::

            {
                "Settings Name": {
                    "type": "settings_type",
                    "default": "default_value",
                    "description": "One line description of the setting"
            }

        The type string should be one of the data types that toolkit accepts as
        part of its environment configuration.
        """

        # grab any base class settings
        collector_settings = super(KritaSessionCollector, self).settings or {}

        # settings specific to this collector
        krita_session_settings = {
            "Work Template": {
                "type": "template",
                "default": None,
                "description": "Template path for artist work files. Should "
                "correspond to a template defined in "
                "templates.yml. If configured, is made available"
                "to publish plugins via the collected item's "
                "properties. ",
            },
            "Publish Layers as Folder": {
                "type": "bool",
                "default": True,
                "description": "Publish Image Layers as a single folder."
                "If true (default) layers will be all exported"
                " together as a folder publish."
                "If false, each layer will be exported and"
                " published as each own version stream.",
            },
        }

        # update the base settings with these settings
        collector_settings.update(krita_session_settings)

        return collector_settings

    def process_current_session(self, settings, parent_item):
        """
        Analyzes the current session open in Krita and parents a subtree of
        items under the parent_item passed in.

        :param dict settings: Configured settings for this collector
        :param parent_item: Root item instance

        """
        items = []

        # create an item representing the current krita session
        session_item = self.collect_current_krita_session(settings, parent_item)
        if session_item:
            items.append(session_item)

            # check if there are any layers to publish
            publish_as_folder_setting = settings.get("Publish Layers as Folder")
            if publish_as_folder_setting and publish_as_folder_setting.value:
                layer_items = self.collect_krita_layers_as_folder(settings, session_item)
            else:
                layer_items = self.collect_krita_layers(settings, session_item)

            items.append(layer_items)
        return items

    def collect_current_krita_session(self, settings, parent_item):
        """
        Creates an item that represents the current krita session.

        :param parent_item: Parent Item instance

        :returns: Item of type krita.session
        """

        publisher = self.parent

        # get the path to the current file
        path = _session_path()

        if not path:
            # no document is active, so nothing to see here!
            return

        # determine the display name for the item
        if path:
            file_info = publisher.util.get_file_path_components(path)
            display_name = file_info["filename"]
        else:
            display_name = "Current Krita Session"

        # create the session item for the publish hierarchy
        session_item = parent_item.create_item("krita.session", "Krita Session", display_name)

        # get the icon path to display for this item
        icon_path = os.path.join(self.disk_location, os.pardir, "icons", "krita.png")
        session_item.set_icon_from_path(icon_path)

        # if a work template is defined, add it to the item properties so
        # that it can be used by attached publish plugins
        work_template_setting = settings.get("Work Template")
        if work_template_setting:

            work_template = publisher.engine.get_template_by_name(work_template_setting.value)

            # store the template on the item for use by publish plugins. we
            # can't evaluate the fields here because there's no guarantee the
            # current session path won't change once the item has been created.
            # the attached publish plugins will need to resolve the fields at
            # execution time.
            session_item.properties["work_template"] = work_template
            session_item.properties["publish_type"] = "Krita Document"
            self.logger.debug("Work template defined for Krita collection.")

        self.logger.info("Collected current Krita scene")

        return session_item

    def _recurse_layers(self, parentNode, fn=None, results=None):
        if results is None:
            results = []

        # if no function is passed, let's assume the identity
        if fn is None:

            def fn(x):
                return x

        for node in parentNode.childNodes():
            results.append(fn(node))
            if node.childNodes():
                self._recurse_layers(node, fn=fn, results=results)

        return results

    def create_node_layer_item(
        self, settings, parent_item, node, display_name=None, icon_name=None, is_header=False
    ):
        publisher = self.parent

        if display_name is None:
            display_name = node.name()

        # create the layers item for the publish hierarchy
        layer_item = parent_item.create_item("krita.layer", "Krita Layer", display_name)

        # get the icon path to display for this item
        if icon_name is None:
            icon_name = "krita_layer.png"

        icon_path = os.path.join(self.disk_location, os.pardir, "icons", icon_name)

        layer_item.set_icon_from_path(icon_path)
        layer_item.properties["node"] = node
        layer_item.properties["node_name"] = create_valid_filename(node.name())
        layer_item.properties["publish_name"] = create_valid_filename(display_name)
        layer_item.properties["publish_type"] = "Krita Layer"
        layer_item.properties["is_header"] = is_header

        if is_header:
            layer_item.type_spec = "krita.layer.header"

        # if a work template is defined, add it to the item properties so
        # that it can be used by attached publish plugins
        work_template = None
        work_template_setting = settings.get("Work Template")

        if work_template_setting:
            work_template = publisher.engine.get_template_by_name(work_template_setting.value)
            if not work_template:
                raise TankError(
                    "Missing Work Template in templates.yml: %s " % work_template_setting.value
                )

        layer_item.properties["work_template"] = work_template

        return layer_item

    def collect_krita_layers(self, settings, parent_item):
        """
        Creates the items that represent the current document layers.

        :param parent_item: Parent Item instance

        :returns: Item of type krita.layer
        """

        # get the path to the current file
        path = _session_path()

        if not path:
            # no document is active, so nothing to see here!
            return

        layer_items = []
        layer_names = []

        krita_app = Krita.instance()
        doc = krita_app.activeDocument()

        if doc:
            parent_node = doc.rootNode()
            layer_names = self._recurse_layers(parent_node, fn=lambda x: x.name())

            if len(layer_names) > 1:
                self.logger.info("Found %s layers: %s" % (len(layer_names), layer_names))

                top_layer_item = self.create_node_layer_item(
                    settings,
                    parent_item,
                    parent_node,
                    display_name="Document Layers",
                    icon_name="krita_layers.png",
                    is_header=True,
                )

                layer_item_fn = partial(self.create_node_layer_item, settings, top_layer_item)

                layer_items = self._recurse_layers(parent_node, fn=layer_item_fn)
                self.logger.info("Collected current document Layers")

        return layer_items

    def collect_krita_layers_as_folder(self, settings, parent_item):
        """
        Creates an item that represents the current document krita layers

        :param parent_item: Parent Item instance

        :returns: Item of type krita.layers
        """
        self.logger.debug("Collecting current document Layers as folder")

        layer_item = None

        publisher = self.parent

        krita_app = Krita.instance()
        doc = krita_app.activeDocument()

        if doc:
            parent_node = doc.rootNode()
            layer_nodes = self._recurse_layers(parent_node, fn=lambda x: x)

            if len(layer_nodes) > 1:
                display_name = "Document Layers (Folder)"

                # create the layers item for the publish hierarchy
                layer_item = parent_item.create_item(
                    "krita.layers", "Krita Layers", display_name
                )

                # get the icon path to display for this item
                icon_path = os.path.join(
                    self.disk_location, os.pardir, "icons", "krita_layers.png"
                )

                layer_item.properties["nodes"] = layer_nodes
                layer_item.set_icon_from_path(icon_path)

                layer_item.properties["publish_type"] = "Krita Layers"

                # if a work template is defined, add it to the item properties so
                # that it can be used by attached publish plugins
                self.logger.debug("Checking Work template...")

                work_template = None
                work_template_setting = settings.get("Work Template")

                if work_template_setting:
                    work_template = publisher.engine.get_template_by_name(
                        work_template_setting.value
                    )
                    if not work_template:
                        raise TankError(
                            "Missing Work Template in templates.yml: %s "
                            % work_template_setting.value
                        )

                layer_item.properties["work_template"] = work_template

                if work_template:
                    self.logger.debug(
                        "Work template defined for the layers as folder: %s " % work_template
                    )
                else:
                    self.logger.debug("No work template defined for the layers as folder.")
                self.logger.info("Collected current document Layers as folder")

        return layer_item


def _session_path():
    """
    Return the path to the current session
    :return:
    """
    path = None

    krita_app = Krita.instance()
    active_doc = krita_app.activeDocument()
    if active_doc:
        path = active_doc.fileName()

    return path
