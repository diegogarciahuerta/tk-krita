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
import traceback
import contextlib

import sgtk
from sgtk import TankError
from tempfile import NamedTemporaryFile
from sgtk.util.version import is_version_older
from sgtk.util.filesystem import copy_file, ensure_folder_exists

from krita import Krita, InfoObject

__author__ = "Diego Garcia Huerta"
__contact__ = "https://www.linkedin.com/in/diegogh/"


HookBaseClass = sgtk.get_hook_baseclass()


@contextlib.contextmanager
def _batch_mode(state):
    """
    A handy context for running things in Krita in batch mode
    """
    krita_app = Krita.instance()
    current_state = krita_app.batchmode()
    krita_app.setBatchmode(state)

    try:
        yield
    finally:
        krita_app.setBatchmode(current_state)


class KritaLayerPublishPlugin(HookBaseClass):
    """
    Plugin for publishing an open krita session.

    This hook relies on functionality found in the base file publisher hook in
    the publish2 app and should inherit from it in the configuration. The hook
    setting for this plugin should look something like this::

        hook: "{self}/publish_file.py:{engine}/tk-multi-publish2/basic/publish_session.py"

    """

    # NOTE: The plugin icon and name are defined by the base file plugin.

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """

        loader_url = "https://support.shotgunsoftware.com/hc/en-us/articles/219033078"

        return """
        Publishes the an image layer to Shotgun. A <b>Publish</b> entry will be
        created in Shotgun which will include a reference to the current file
        layer on disk. If a publish template is configured, a copy of the layer
        will be copied to the publish template. Other users will be able to
        access the published layer ia the <b><a href='%s'>Loader</a></b> so
        long as they have access to the layer's location on disk.

        If the session file has not been saved, validation will fail and a
        button will be provided in the logging output to save the file.

        The <code>version</code> field of the resulting <b>Publish</b> in
        Shotgun will also reflect the version number identified in the filename.
        The basic worklfow recognizes the following version formats by default:

        <ul>
        <li><code>filename.v###.ext</code></li>
        <li><code>filename_v###.ext</code></li>
        <li><code>filename-v###.ext</code></li>
        </ul>

        <br><br><i>NOTE: any amount of version number padding is supported. for
        non-template based workflows.</i>

        <h3>Overwriting an existing publish</h3>
        In non-template workflows, a file can be published multiple times,
        however only the most recent publish will be available to other users.
        Warnings will be provided during validation if there are previous
        publishes.
        """ % (
            loader_url,
        )

    @property
    def settings(self):
        """
        Dictionary defining the settings that this plugin expects to receive
        through the settings parameter in the accept, validate, publish and
        finalize methods.

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

        # inherit the settings from the base publish plugin
        base_settings = super(KritaLayerPublishPlugin, self).settings or {}

        # settings specific to this class
        krita_publish_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published work files. Should"
                "correspond to a template defined in "
                "templates.yml.",
            }
        }

        krita_export_settings = {
            "Export Template": {
                "type": "template",
                "default": None,
                "description": (
                    "Template path for exporting a layer. This will be the export"
                    " location where the layer will be exported."
                    " Should correspond to a template defined in templates.yml."
                    "If not specified, a folder 'layers' will be used inside the"
                    " location of the work file and 'kritalayer_<layer_name>.png'"
                    " will be used as layer name."
                ),
            }
        }

        # update the base settings
        base_settings.update(krita_publish_settings)
        base_settings.update(krita_export_settings)

        return base_settings

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.

        Only items matching entries in this list will be presented to the
        accept() method. Strings can contain glob patters such as *, for example
        ["krita.*", "file.krita"]
        """
        return ["krita.layer"]

    def accept(self, settings, item):
        """
        Method called by the publisher to determine if an item is of any
        interest to this plugin. Only items matching the filters defined via the
        item_filters property will be presented to this method.

        A publish task will be generated for each item accepted here. Returns a
        dictionary with the following booleans:

            - accepted: Indicates if the plugin is interested in this value at
                all. Required.
            - enabled: If True, the plugin will be enabled in the UI, otherwise
                it will be disabled. Optional, True by default.
            - visible: If True, the plugin will be visible in the UI, otherwise
                it will be hidden. Optional, True by default.
            - checked: If True, the plugin will be checked in the UI, otherwise
                it will be unchecked. Optional, True by default.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process

        :returns: dictionary with boolean keys accepted, required and enabled
        """

        # if a publish template is configured, disable context change. This
        # is a temporary measure until the publisher handles context switching
        # natively.
        publish_template = self.get_publish_template(settings, item)
        if publish_template:
            item.context_change_allowed = False

        node = item.properties["node"]

        self.logger.info(
            "Krita '%s' plugin accepted publishing Krita '%s' layer."
            % (self.name, node.name())
        )
        return {"accepted": True, "checked": True}

    def get_publish_template(self, settings, item):
        """
        Retrieves and and validates the publish template from the settings.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process

        :returns: A template representing the publish path of the item or
            None if no template could be identified.
        """
        publisher = self.parent

        publish_template = item.get_property("publish_template")
        if publish_template:
            return publish_template

        publish_template = None
        publish_template_setting = settings.get("Publish Template")

        if publish_template_setting and publish_template_setting.value:
            publish_template = publisher.engine.get_template_by_name(
                publish_template_setting.value
            )
            if not publish_template:
                raise TankError(
                    "Missing Publish Template in templates.yml: %s "
                    % publish_template_setting.value
                )

        # cache it for later use
        item.properties["publish_template"] = publish_template

        return publish_template

    def get_export_template(self, settings, item):
        """
        Retrieves and and validates the export template from the settings.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process

        :returns: A template representing the export path of the item or
            None if no template could be identified.
        """
        publisher = self.parent

        export_template = item.get_property("export_template")
        if export_template:
            return export_template

        export_template = None
        export_template_setting = settings.get("Export Template")

        if export_template_setting and export_template_setting.value:
            export_template = publisher.engine.get_template_by_name(
                export_template_setting.value
            )
            if not export_template:
                raise TankError(
                    "Missing Export Template in templates.yml: %s "
                    % export_template_setting.value
                )

        # cache it for later use
        item.properties["export_template"] = export_template

        return export_template

    def get_path_from_work_template(self, settings, item, template):
        """
        Handy method to use the work template to resolve a different template.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        :param template: Target template to apply fields for.

        :returns: resolved path given the target template
        """
        path = None

        node_name = item.properties["node_name"]
        session_path = item.properties["session_path"]
        work_template = item.properties.get("work_template")

        # a bit of spaghetti code here, but we need to be throughout with
        # the way we report to the artists.
        if work_template and template:
            template_name = template.name

            if work_template.validate(session_path):
                work_fields = work_template.get_fields(session_path)
                work_fields["name"] = node_name

                missing_keys = template.missing_keys(work_fields, skip_defaults=True)
                if not missing_keys:
                    # best case, we have everything we need to export using a template
                    path = template.apply_fields(work_fields)
                else:
                    self.logger.warning(
                        "Work file '%s' missing keys required for the '%s' "
                        "template: %s." % (session_path, template_name, missing_keys)
                    )
            else:
                self.logger.warning(
                    "Work file '%s' did not match work template '%s'. "
                    % (session_path, template_name)
                )

        return path

    def get_export_path(self, settings, item):
        """
        Retrieves the path to export eh layer before it gets copied to the 
        publish location. This is handy if you use a different location for
        wip files than publish files.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process

        :returns: the location where the layer will be export before it is 
            published
        """
        publisher = self.parent

        export_path = item.get_property("export_path")
        if export_path:
            return export_path

        # apply the work file fields to the export template to figure out the
        # export path
        export_template = self.get_export_template(settings, item)
        export_path = self.get_path_from_work_template(settings, item, export_template)

        # we define a default export location if the path could not be resolved
        if not export_path:
            node_name = item.properties["node_name"]
            session_path = item.properties["session_path"]
            session_dir, session_filename = os.path.split(session_path)
            session_filename_file = os.path.basename(session_filename)

            # We allow this environment variable to allow some sort of customization
            # when it comes to choosing the default export extension.
            default_extension = os.environ.get("SGTK_KRITA_LAYER_DEFAULT_EXTENSION", "png")

            layer_name = "%s.%s" % (node_name, default_extension)
            export_path = os.path.join(
                session_path_dir, "layers", session_filename_file, layer_name
            )

        self.logger.debug("Export path will be: %s" % export_path)

        # cache for use it later
        item.properties["export_path"] = export_path

        return export_path

    def get_publish_path(self, settings, item):
        # publish path explicitly set or defined on the item
        publish_path = item.get_property("publish_path")
        if publish_path:
            return publish_path

        # ensure templates are available
        work_session_template = item.properties.get("work_template")
        publish_template = self.get_publish_template(settings, item)

        publish_path = self.get_path_from_work_template(settings, item, publish_template)
        if not publish_path:
            publish_path = self.get_export_path(settings, item)
            self.logger.debug(
                "Could not validate a publish template. Publishing will happen in place."
            )

        # cache in case we use it later
        item.properties["publish_path"] = publish_path

        return publish_path

    def get_publish_name(self, settings, item):
        """
        Get the publish name for the supplied settings and item.
        :param settings: This plugin instance's configured settings
        :param item: The item to determine the publish version for
        Extracts the publish name from the publish file path.
        """
        publish_path = self.get_publish_path(settings, item)
        return os.path.basename(publish_path)

    def session_validate(self, settings, item):
        document = _session_document()
        if not document:
            error_msg = "There is no active document opened in Krita. Publishing Canceled."
            self.logger.error(error_msg)
            raise Exception(error_msg)

        session_path = document.fileName()

        if not session_path:
            # the session has not been saved before (no path determined).
            # provide a save button. the session will need to be saved before
            # validation will succeed.
            error_msg = (
                "The Krita session has not been saved. Please save your session "
                "before publishing."
            )
            self.logger.error(error_msg, extra=_get_save_as_action())
            raise Exception(error_msg)

        if document.modified():
            # the session has been modified, so we should let the user know.
            self.logger.warn(
                (
                    "The Krita session has been modified. Please save your session "
                    "before publishing."
                ),
                extra=_get_save_as_action(),
            )

        # get the path in a normalized state. no trailing separator,
        # separators are appropriate for current OS, no double separators,
        # etc.
        session_path = sgtk.util.ShotgunPath.normalize(session_path)
        item.properties["session_path"] = session_path
        item.properties["session_document"] = document

        # set the session path on the item for use by the base plugin validation
        # step. NOTE: this path could change prior to the publish phase.
        item.properties["path"] = session_path

        self.logger.debug("Session Path: %s " % session_path)

    def templates_validate(self, settings, item):
        session_path = item.properties.get("session_path")

        # if the session item has a known work template, see if the path
        # matches. if not, warn the user and provide a way to save the file to
        # a different path

        self.logger.debug("Checking Work template...")

        work_template = item.properties.get("work_template")
        if work_template:
            if not work_template.validate(session_path):
                self.logger.warning(
                    (
                        "The current session does not match the configured work file "
                        "template. Please save your session before publishing."
                    ),
                    extra=_get_save_as_action(),
                )
            else:
                self.logger.debug("Work template configured and matches session file.")
        else:
            self.logger.debug("No work template configured.")

        # export template
        export_template = self.get_export_template(settings, item)
        if export_template:
            self.logger.debug("Export template: %s " % export_template)
        else:
            self.logger.warning("No Export template defined for the layer.")

        # publish template
        publish_template = self.get_publish_template(settings, item)
        if publish_template:
            self.logger.debug("Publish template: %s " % publish_template)
        else:
            self.logger.warning("No Publish template defined for the layer.")

    def validate(self, settings, item):
        """
        Validates the given item to check that it is ok to publish. Returns a
        boolean to indicate validity.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        :returns: True if item is valid, False otherwise.
        """

        node_name = item.properties["node_name"]
        self.logger.debug("Validating layer: %s" % node_name)

        publisher = self.parent

        self.session_validate(settings, item)
        self.templates_validate(settings, item)

        # figure out the export path
        export_path = self.get_export_path(settings, item)

        # and the publish path
        publish_path = self.get_publish_path(settings, item)

        # run the base class validation
        return super(KritaLayerPublishPlugin, self).validate(settings, item)

    def _export_layer(self, node, export_layer_path, active_doc):
        krita_app = Krita.instance()
        active_doc_bounds = active_doc.rootNode().bounds()

        # old versions of Krita had a different signature for this function
        # unfortunately since this function is not a python one we cannot
        # inspect it, so we do have to check the Krita version to know
        # how to approach this export
        if is_version_older(krita_app.version(), "4.2.0"):
            node.save(export_layer_path, active_doc.width(), active_doc.height())
        else:
            node.save(
                export_layer_path,
                active_doc.width(),
                active_doc.height(),
                InfoObject(),
                active_doc_bounds,
            )

    def _copy_work_to_publish(self, settings, item):
        """
        This method handles exporting a layer and copying it to a designated
        publish location.
        This method requires a "publish_template" be set on the supplied item.
        The method will not attempt to copy files if any of the above
        requirements are not met. If the requirements are met, the file will
        ensure the publish path folder exists and then copy the file to that
        location.
        """

        krita_app = Krita.instance()

        node = item.properties["node"]
        session_path = item.properties["session_path"]
        active_doc = item.properties.get("session_document")

        export_path = self.get_export_path(settings, item)
        export_path_folder = os.path.dirname(export_path)
        ensure_folder_exists(export_path_folder)

        # this is so the publisher picks the right location for this layer
        item.properties.path = export_path

        # export the layer
        with _batch_mode(True):
            self._export_layer(node, export_path, active_doc)

        publish_path = self.get_publish_path(settings, item)

        # if the publish path is different that were the layer was exported
        # copy the file over
        if not os.path.normpath(publish_path) == os.path.normpath(export_path):
            publish_folder = os.path.dirname(publish_path)
            ensure_folder_exists(publish_folder)

            # copy the file to the publish location
            try:
                copy_file(export_path, publish_path)
                self.logger.debug(
                    "Copied exported files '%s' to publish folder '%s'."
                    % (export_path, publish_path)
                )
            except Exception:
                raise TankError(
                    "Failed to copy exported file from '%s' to '%s'.\n%s"
                    % (export_path, publish_path, traceback.format_exc())
                )
        else:
            self.logger.debug("Skipping copy file to publish location.")

        # this is so the publisher picks the right location for this layer
        item.properties.path = publish_path
        item.set_thumbnail_from_path(publish_path)

    def get_publish_dependencies(self, settings, item):
        """
        Find additional dependencies from the session
        """
        dependencies = super(KritaLayerPublishPlugin, self).get_publish_dependencies(
            settings, item
        )

        # in our case, we created this "fake" group layer item to encapsulate nicely all the
        # layers in the UI. One side effect of the fact that this is a bogus item and does
        # not get published, is that we loose the dependency to the actual session
        # publish. We sort it out here by accessing the ancestor of this group layer item
        top_layer_item = item.parent
        if (
            top_layer_item
            and top_layer_item.properties.get("is_header", False)
            and top_layer_item.parent
        ):
            if "sg_publish_data" in top_layer_item.parent.properties:
                dependencies.append(
                    top_layer_item.parent.properties.sg_publish_data["path"]["local_path"]
                )

        self.logger.debug("Dependencies: %s" % dependencies)

        # Perhaps here we can see if we could figure out reference Layers and
        # if they represent a publish

        return dependencies


def _session_document():
    """
    Return the current active document
    :return:
    """
    krita_app = Krita.instance()
    active_doc = krita_app.activeDocument()
    return active_doc


def _session_path():
    """
    Return the path to the current session
    :return:
    """
    path = None

    active_doc = _session_document()
    if active_doc:
        path = active_doc.fileName()

    return path


# TODO: method duplicated in all the krita hooks
def _get_save_as_action():
    """
    Simple helper for returning a log action dict for saving the session
    """

    engine = sgtk.platform.current_engine()

    callback = _save_as

    # if workfiles2 is configured, use that for file save
    if "tk-multi-workfiles2" in engine.apps:
        app = engine.apps["tk-multi-workfiles2"]
        if hasattr(app, "show_file_save_dlg"):
            callback = app.show_file_save_dlg

    return {
        "action_button": {
            "label": "Save As...",
            "tooltip": "Save the current session",
            "callback": callback,
        }
    }


def _save_as():
    krita_app = Krita.instance()
    krita_app.action("file_save_as").trigger()
