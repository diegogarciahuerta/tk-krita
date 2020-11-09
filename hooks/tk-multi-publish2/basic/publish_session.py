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
import tempfile
import contextlib

import sgtk
from sgtk.util.filesystem import ensure_folder_exists
from sgtk.util.version import is_version_older

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


class KritaSessionPublishPlugin(HookBaseClass):
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
        Publishes the file to Shotgun. A <b>Publish</b> entry will be
        created in Shotgun which will include a reference to the file's current
        path on disk. If a publish template is configured, a copy of the
        current session will be copied to the publish template path which
        will be the file that is published. Other users will be able to access
        the published file via the <b><a href='%s'>Loader</a></b> so long as
        they have access to the file's location on disk.

        If the session has not been saved, validation will fail and a button
        will be provided in the logging output to save the file.

        <h3>File versioning</h3>
        If the filename contains a version number, the process will bump the
        file to the next version after publishing.

        The <code>version</code> field of the resulting <b>Publish</b> in
        Shotgun will also reflect the version number identified in the filename.
        The basic worklfow recognizes the following version formats by default:

        <ul>
        <li><code>filename.v###.ext</code></li>
        <li><code>filename_v###.ext</code></li>
        <li><code>filename-v###.ext</code></li>
        </ul>

        After publishing, if a version number is detected in the work file, the
        work file will automatically be saved to the next incremental version
        number. For example, <code>filename.v001.ext</code> will be published
        and copied to <code>filename.v002.ext</code>

        If the next incremental version of the file already exists on disk, the
        validation step will produce a warning, and a button will be provided in
        the logging output which will allow saving the session to the next
        available version number prior to publishing.

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
        base_settings = super(KritaSessionPublishPlugin, self).settings or {}

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

        # update the base settings
        base_settings.update(krita_publish_settings)

        return base_settings

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.

        Only items matching entries in this list will be presented to the
        accept() method. Strings can contain glob patters such as *, for example
        ["krita.*", "file.krita"]
        """
        return ["krita.session"]

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

        # if we validate the session , we can accept it
        self.session_validate(settings, item)

        # set a nice thumbnail for this item so the publish also has one for free
        doc_thumbnail = self.get_document_thumbnail(settings, item)
        if os.path.getsize(doc_thumbnail) > 0:
            item.set_thumbnail_from_path(doc_thumbnail)

        self.logger.info(
            "Krita '%s' plugin accepted the current Krita session." % (self.name,)
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

        # publish template
        publish_template = self.get_publish_template(settings, item)
        if publish_template:
            self.logger.debug("Session Publish template: %s " % publish_template)
        else:
            self.logger.warning("No Publish template defined for the session.")

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

        path = item.properties["session_path"]

        # ---- see if the version can be bumped post-publish

        # check to see if the next version of the work file already exists on
        # disk. if so, warn the user and provide the ability to jump to save
        # to that version now
        (next_version_path, version) = self._get_next_version_info(path, item)
        if next_version_path and os.path.exists(next_version_path):

            # determine the next available version_number. just keep asking for
            # the next one until we get one that doesn't exist.
            while os.path.exists(next_version_path):
                (next_version_path, version) = self._get_next_version_info(
                    next_version_path, item
                )

            error_msg = "The next version of this file already exists on disk."
            self.logger.error(
                error_msg,
                extra={
                    "action_button": {
                        "label": "Save to v%s" % (version,),
                        "tooltip": "Save to the next available version number, "
                        "v%s" % (version,),
                        "callback": lambda: _save_session(next_version_path),
                    }
                },
            )
            raise Exception(error_msg)

        # run the base class validation
        return super(KritaSessionPublishPlugin, self).validate(settings, item)

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        # get the path in a normalized state. no trailing separator, separators
        # are appropriate for current os, no double separators, etc.
        path = sgtk.util.ShotgunPath.normalize(_session_path())

        # ensure the session is saved
        _save_session(path)

        # update the item with the saved session path
        item.properties["path"] = path

        # add dependencies for the base class to register when publishing
        item.properties["publish_dependencies"] = _krita_find_additional_session_dependencies()

        # let the base class register the publish
        super(KritaSessionPublishPlugin, self).publish(settings, item)

    def finalize(self, settings, item):
        """
        Execute the finalization pass. This pass executes once all the publish
        tasks have completed, and can for example be used to version up files.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        # do the base class finalization
        super(KritaSessionPublishPlugin, self).finalize(settings, item)

        # bump the session file to the next version
        self._save_to_next_version(item.properties["path"], item, _save_session)


def _krita_find_additional_session_dependencies():
    """
    Find additional dependencies from the session
    """
    # Figure out what read nodes are known to the engine and use them
    # as dependencies

    return []


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


def _save_session(path):
    """
    Save the current session to the supplied path.
    """

    # Ensure that the folder is created when saving
    folder = os.path.dirname(path)
    ensure_folder_exists(folder)

    active_doc = _session_document()
    success = active_doc.saveAs(path)
    active_doc.waitForDone()

    if success:
        active_doc.setFileName(path)


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
