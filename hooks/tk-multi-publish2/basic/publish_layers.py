# ----------------------------------------------------------------------------
# Copyright (c) 2019-2020, Diego Garcia Huerta.
#
# Your use of this software as distributed in this GitHub repository, is 
# governed by the BSD 3-clause License.
#
# Your use of the Shotgun Pipeline Toolkit is governed by the applicable license
# agreement between you and Autodesk / Shotgun.
#
# The full license is in the file LICENSE, distributed with this software.
# ----------------------------------------------------------------------------

import os
import traceback
import contextlib
import tempfile

import sgtk
from sgtk import TankError
from sgtk.util.filesystem import copy_folder, ensure_folder_exists
from sgtk.platform.qt import QtCore
from sgtk.util.version import is_version_older
from sgtk.util.filesystem import create_valid_filename as sanitize_node_name

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


class KritaLayersPublishPlugin(HookBaseClass):
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
        Publishes the file layers to Shotgun. A <b>Publish</b> entry will be
        created in Shotgun which will include a reference to the folder where
        the current file layers are on disk. If a publish template is
        configured, a copy of the layers will be copied to the publish template
        path folder. Other users will be able to access the published layers
        ia the <b><a href='%s'>Loader</a></b> so long as they have access to
        he folder's location on disk.

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
        base_settings = super(KritaLayersPublishPlugin, self).settings or {}

        # settings specific to this class
        krita_publish_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": (
                    "Template path for published layers as folder. "
                    "Should correspond to a template defined in templates.yml."
                ),
            }
        }

        krita_export_settings = {
            "Export Template": {
                "type": "template",
                "default": None,
                "description": (
                    "Template path for exporting layers as folder. "
                    " Should correspond to a template defined in templates.yml."
                    "If not specified, a folder 'layers' will be used inside the"
                    " location of the work file."
                ),
            }
        }

        krita_layer_name_settings = {
            "Layer Name Template": {
                "type": "template",
                "default": None,
                "description": (
                    "Template path for naming the layers inside the folder. "
                    "Should correspond to a template defined in templates.yml."
                    "If not specified, 'kritalayer_<layer_name>.png' will be used"
                    " as layer name.",
                ),
            }
        }

        # update the base settings
        base_settings.update(krita_publish_settings)
        base_settings.update(krita_export_settings)
        base_settings.update(krita_layer_name_settings)

        return base_settings

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.

        Only items matching entries in this list will be presented to the
        accept() method. Strings can contain glob patters such as *, for example
        ["krita.*", "file.krita"]
        """
        return ["krita.layers"]

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

        self.logger.info("Krita '%s' plugin accepted publishing Krita layers." % (self.name,))
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

    def get_layer_name_template(self, settings, item):
        """
        Retrieves and and validates the Layer Name Template, used to build
        a name for the individual layers that will be published.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process

        :returns: A template representing the Layer Name template of the item or
            None if no template could be identified.
        """
        publisher = self.parent

        layer_name_template = item.get_property("layer_name_template")
        if layer_name_template:
            return layer_name_template

        layer_name_template = None
        layer_name_template_setting = settings.get("Layer Name Template")

        if layer_name_template_setting and layer_name_template_setting.value:
            layer_name_template = publisher.engine.get_template_by_name(
                layer_name_template_setting.value
            )
            if not layer_name_template:
                raise TankError(
                    "Missing Layer Name Template in templates.yml: %s "
                    % layer_name_template_setting.value
                )

        # cache it for later use
        item.properties["layer_name_template"] = layer_name_template

        return layer_name_template

    def get_path_from_work_template(self, settings, item, template, extra_fields=None):
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

        session_path = item.properties.get("session_path")
        work_template = item.properties.get("work_template")

        # a bit of spaghetti code here, but we need to be throughout with
        # the way we report to the artists.
        if work_template and template:
            template_name = template.name

            if work_template.validate(session_path):
                work_fields = work_template.get_fields(session_path)

                if extra_fields:
                    work_fields.update(extra_fields)

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

            export_path = os.path.join(session_path_dir, "layers", session_filename_file)

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
        publish_path = self.get_publish_path(settings, item)
        return os.path.basename(publish_path)

    def get_publish_version(self, settings, item):
        """
        Get the publish version for the supplied settings and item.
        :param settings: This plugin instance's configured settings
        :param item: The item to determine the publish version for
        Extracts the publish version via the configured work template if
        possible. Will fall back to using the path info hook.
        """

        # publish version explicitly set or defined on the item
        publish_version = item.get_property("publish_version")
        if publish_version:
            return publish_version

        # fall back to the template/path_info logic
        publisher = self.parent
        path = item.properties.get("session_path")

        work_template = item.properties.get("work_template")
        work_fields = None
        publish_version = None

        if work_template:
            if work_template.validate(path):
                self.logger.debug("Work file template configured and matches file.")
                work_fields = work_template.get_fields(path)

        if work_fields:
            # if version number is one of the fields, use it to populate the
            # publish information
            if "version" in work_fields:
                publish_version = work_fields.get("version")
                self.logger.debug("Retrieved version number via work file template.")

        else:
            self.logger.debug("Using path info hook to determine publish version.")
            publish_version = publisher.util.get_version_number(path)
            if publish_version is None:
                publish_version = 1

        return publish_version

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
            self.logger.warning("No Export template defined for the layers as folder.")

        # Layer Name Template
        layer_name_template = self.get_layer_name_template(settings, item)
        if layer_name_template:
            self.logger.debug("Layer Name template: %s " % layer_name_template)
        else:
            self.logger.warning("No Layer Name template defined for the layers as folder.")

        # publish template
        publish_template = self.get_publish_template(settings, item)
        if publish_template:
            self.logger.debug("Publish template: %s " % publish_template)
        else:
            self.logger.warning("No Publish template defined for the layers as folder.")

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

        publisher = self.parent

        self.session_validate(settings, item)
        self.templates_validate(settings, item)

        # set a nice thumbnail for this item so the publish also has one for free
        doc_thumbnail = self.get_document_thumbnail(settings, item)
        if os.path.getsize(doc_thumbnail) > 0:
            item.set_thumbnail_from_path(doc_thumbnail)

        # figure out the export path
        export_path = self.get_export_path(settings, item)

        # and the publish path
        publish_path = self.get_publish_path(settings, item)

        # run the base class validation
        return super(KritaLayersPublishPlugin, self).validate(settings, item)

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

    def get_document_thumbnail(self, settings, item):
        active_doc = item.properties.get("session_document")
        root = active_doc.rootNode()
        temp_path = tempfile.NamedTemporaryFile(
            suffix=".png", prefix="sgtk_thumb", delete=False
        ).name

        with _batch_mode(True):
            self._export_layer(root, temp_path, active_doc)

        return temp_path

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

        nodes = item.properties.get("nodes")
        session_path = item.properties.get("session_path")
        active_doc = item.properties.get("session_document")

        # export the actual layers

        # this is a default extension in case a 'krita_layer_name' template
        # string was not defined. We allow this environment variable to allow
        # some sort of customization when it comes to choosing the extension.
        default_extension = os.environ.get("SGTK_KRITA_LAYER_DEFAULT_EXTENSION", "png")

        layer_name_template = item.properties.get("layer_name_template")
        if not layer_name_template:
            self.logger.warning(
                "No template string 'Layer Name Template' was defined for "
                "naming the layer files. Layers will be exported with the "
                "default layer name and '%s' extension." % default_extension
            )

        export_path = self.get_export_path(settings, item)
        ensure_folder_exists(export_path)

        # we export in batch mode
        with _batch_mode(True):
            for node in nodes:
                node_name = sanitize_node_name(node.name())

                layer_name = None
                if layer_name_template:
                    layer_name = self.get_path_from_work_template(
                        settings, item, layer_name_template, extra_fields={"name": node_name}
                    )

                if not layer_name:
                    # create one ourselves if no template was defined
                    layer_name = "%s.%s" % (node_name, default_extension)

                export_layer_path = os.path.join(export_path, layer_name)

                # finally export he layer
                self._export_layer(node, export_layer_path, active_doc)

        item.set_thumbnail_from_path(export_layer_path)

        # note that this is a folder
        publish_path = self.get_publish_path(settings, item)

        # if the publish path is different that were the layer was exported
        # copy the file over
        if not os.path.normpath(publish_path) == os.path.normpath(export_path):
            ensure_folder_exists(publish_path)

            # copy the file
            try:
                copy_folder(export_path, publish_path)
                self.logger.debug(
                    "Copied exported files '%s' to publish folder '%s'."
                    % (export_path, publish_path)
                )

            except Exception:
                raise TankError(
                    "Failed to copy exported files from '%s' to '%s'.\n%s"
                    % (export_path, publish_path, traceback.format_exc())
                )

        else:
            self.logger.debug("Skipping copy folder to publish location.")

        # this is so the publisher picks the right location for this layer
        item.properties.path = publish_path
        item.set_thumbnail_from_path(publish_path)

    def get_publish_dependencies(self, settings, item):
        """
        Find additional dependencies from the session
        """
        dependencies = super(KritaLayersPublishPlugin, self).get_publish_dependencies(
            settings, item
        )

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
