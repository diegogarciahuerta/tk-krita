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

"""
Hook that loads defines all the available actions, broken down by publish type.
"""

import os
import sgtk
import bisect

from krita import Krita

__author__ = "Diego Garcia Huerta"
__contact__ = "https://www.linkedin.com/in/diegogh/"


HookBaseClass = sgtk.get_hook_baseclass()


# up to date as of 28/02/2020
# a quite impressive list of format, I must say!
KRITA_SUPPORTED_FORMATS = (
    ".pdf",
    ".exr",
    ".kra",
    ".kpp",
    ".bmp",
    ".dib",
    ".gif",
    ".jpg",
    ".jpeg",
    ".jpe",
    ".ora",
    ".psd",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".psd",
    ".ico",
    ".webp",
    ".exr",
    ".gbr",
    ".vbr",
    ".gih",
    ".bay",
    ".bmq",
    ".cr2",
    ".crw",
    ".cs1",
    ".dc2",
    ".dcr",
    ".dng",
    ".erf",
    ".fff",
    ".hdr",
    ".k25",
    ".kdc",
    ".mdc",
    ".mos",
    ".mrw",
    ".nef",
    ".orf",
    ".pef",
    ".pxn",
    ".raf",
    ".raw",
    ".rdc",
    ".sr2",
    ".srf",
    ".x3f",
    ".arw",
    ".3fr",
    ".cine",
    ".ia",
    ".kc2",
    ".mef",
    ".nrw",
    ".qtk",
    ".rw2",
    ".sti",
    ".rwl",
    ".srw",
    ".psd",
    ".pbm",
    ".pgm",
    ".ppm",
    ".psb",
    ".psd",
    ".r16",
    ".r32",
    ".r8",
    ".tga",
    ".icb",
    ".tpic",
    ".vda",
    ".vst",
    ".xbm",
    ".xcf",
    ".xpm",
    ".csv",
)


# used to figure out the frame numbers out of image sequences
SEQUENCE_FIELD = "SEQ"


class KritaActions(HookBaseClass):
    # public interface - to be overridden by deriving classes

    def generate_actions(self, sg_publish_data, actions, ui_area):
        """
        Returns a list of action instances for a particular publish.
        This method is called each time a user clicks a publish somewhere in
        the UI.
        The data returned from this hook will be used to populate the actions
        menu for a publish.

        The mapping between Publish types and actions are kept in a different
        place (in the configuration) so at the point when this hook is called,
        the loader app has already established *which* actions are appropriate
        for this object.

        The hook should return at least one action for each item passed in via
        the actions parameter.

        This method needs to return detailed data for those actions, in the
        form of a list of dictionaries, each with name, params, caption and
        description keys.

        Because you are operating on a particular publish, you may tailor the
        output  (caption, tooltip etc) to contain custom information suitable
        for this publish.

        The ui_area parameter is a string and indicates where the publish is to
        be shown.
        - If it will be shown in the main browsing area, "main" is passed.
        - If it will be shown in the details area, "details" is passed.
        - If it will be shown in the history area, "history" is passed.

        Please note that it is perfectly possible to create more than one
        action "instance" for an action! You can for example do scene
        introspection - if the action passed in is "character_attachment"
        you may for example scan the scene, figure out all the nodes
        where this object can be attached and return a list of action
        instances:
        "attach to left hand", "attach to right hand" etc. In this case,
        when more than one object is returned for an action, use the params
        key to pass additional data into the run_action hook.

        :param sg_publish_data: Shotgun data dictionary with all the standard
                                publish fields.
        :param actions: List of action strings which have been defined in the
                        app configuration.
        :param ui_area: String denoting the UI Area (see above).
        :returns List of dictionaries, each with keys name, params, caption and
         description
        """
        app = self.parent
        app.log_debug(
            "Generate actions called for UI element %s. "
            "Actions: %s. Publish Data: %s" % (ui_area, actions, sg_publish_data)
        )

        action_instances = []

        if "open_image" in actions:
            action_instances.append(
                {
                    "name": "open_image",
                    "params": None,
                    "caption": "Open Image as new Document",
                    "description": ("This file will be opened as a new Document"),
                }
            )

        if "open_as_layer" in actions:
            action_instances.append(
                {
                    "name": "open_as_layer",
                    "params": None,
                    "caption": "Open Image as Layer",
                    "description": (
                        "This file will be opened as a new layer in the current document"
                    ),
                }
            )

        if "import_animation_frames" in actions:
            action_instances.append(
                {
                    "name": "import_animation_frames",
                    "params": None,
                    "caption": "Import as animated frames",
                    "description": (
                        "Import the Image Sequence as animated frames into the current document inserting frames from the current time onwards"
                    ),
                }
            )

        return action_instances

    def execute_multiple_actions(self, actions):
        """
        Executes the specified action on a list of items.

        The default implementation dispatches each item from ``actions`` to
        the ``execute_action`` method.

        The ``actions`` is a list of dictionaries holding all the actions to
        execute.
        Each entry will have the following values:

            name: Name of the action to execute
            sg_publish_data: Publish information coming from Shotgun
            params: Parameters passed down from the generate_actions hook.

        .. note::
            This is the default entry point for the hook. It reuses the
            ``execute_action`` method for backward compatibility with hooks
            written for the previous version of the loader.

        .. note::
            The hook will stop applying the actions on the selection if an
            error is raised midway through.

        :param list actions: Action dictionaries.
        """
        app = self.parent
        for single_action in actions:
            app.log_debug("Single Action: %s" % single_action)
            name = single_action["name"]
            sg_publish_data = single_action["sg_publish_data"]
            params = single_action["params"]

            self.execute_action(name, params, sg_publish_data)

    def execute_action(self, name, params, sg_publish_data):
        """
        Execute a given action. The data sent to this be method will
        represent one of the actions enumerated by the generate_actions method.

        :param name: Action name string representing one of the items returned
                     by generate_actions.
        :param params: Params data, as specified by generate_actions.
        :param sg_publish_data: Shotgun data dictionary with all the standard
                                publish fields.
        :returns: No return value expected.
        """
        app = self.parent
        app.log_debug(
            "Execute action called for action %s. "
            "Parameters: %s. Publish Data: %s" % (name, params, sg_publish_data)
        )

        # resolve path
        # toolkit uses utf-8 encoded strings internally and Krita API expects
        # unicode so convert the path to ensure filenames containing complex
        # characters are supported
        path = self.get_publish_path(sg_publish_data).replace(os.path.sep, "/")

        if name == "open_image":
            if not self._is_a_supported_extension(path, sg_publish_data):
                raise Exception("Unsupported file extension for '%s'!" % path)

            self._open_as_document(path, sg_publish_data)

        if name == "open_as_layer":
            if not self._is_a_supported_extension(path, sg_publish_data):
                raise Exception("Unsupported file extension for '%s'!" % path)

            self._open_as_layer(path, sg_publish_data)

        if name == "import_animation_frames":
            if not self._is_a_supported_extension(path, sg_publish_data):
                raise Exception("Unsupported file extension for '%s'!" % path)

            self._import_animation_frames(path, sg_publish_data)

    def _is_a_supported_extension(self, path, sg_publish_data):
        _, ext = os.path.splitext(path)
        return ext.lower() in KRITA_SUPPORTED_FORMATS

    # it opens the image as a new layer of the current document
    def _open_as_layer(self, path, sg_publish_data):
        krita_app = Krita.instance()
        doc = krita_app.activeDocument()
        if not doc:
            return False

        filename_file = os.path.basename(path)
        filename_filename, _ = os.path.splitext(filename_file)
        layer_name = filename_filename
        layer_node = doc.createNode(layer_name, "paintlayer")
        doc.rootNode().addChildNode(layer_node, None)

        # load as a different doc
        layer_doc = krita_app.openDocument(path)
        layer_doc.waitForDone()
        pixel_data = layer_doc.pixelData(0, 0, layer_doc.width(), layer_doc.height())

        # paste pixel info
        layer_node.setPixelData(pixel_data, 0, 0, layer_doc.width(), layer_doc.height())
        doc.waitForDone()

        doc.setActiveNode(layer_node)
        doc.refreshProjection()
        doc.waitForDone()

        # no need anymore
        layer_doc.close()

    # creates a new document and import the sequence of images as animated frames
    def _import_animation_frames(self, path, sg_publish_data):
        krita_app = Krita.instance()
        doc = krita_app.activeDocument()
        if not doc:
            return False

        app = self.parent
        template = app.sgtk.template_from_path(path)
        fields = template.get_fields(path)

        images = app.sgtk.paths_from_template(template, fields, skip_keys=[SEQUENCE_FIELD])

        # a quick way to get the images sorted by frame, as this matters when
        # we insert them in the layer
        frame_images = []
        for image in images:
            fields = template.get_fields(image)
            frame = int(fields[SEQUENCE_FIELD])
            bisect.insort(frame_images, (frame, image))

        sorted_images = [frame_image[1] for frame_image in frame_images]

        # current time
        t = doc.currentTime()

        # insert from the current time onwards
        doc.importAnimation(sorted_images, t, 1)
        doc.waitForDone()

    # it opens the image as a new document
    def _open_as_document(self, path, sg_publish_data):
        """
        Opens the image as a new document

        :param path: Path to file.
        :param sg_publish_data: Shotgun data dictionary with all the standard
                                publish fields.
        """
        krita_app = Krita.instance()
        doc = krita_app.openDocument(path)
        krita_app.activeWindow().addView(doc)
        doc.waitForDone()
