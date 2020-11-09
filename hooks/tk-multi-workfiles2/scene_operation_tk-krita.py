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

import sgtk
from krita import Krita

__author__ = "Diego Garcia Huerta"
__contact__ = "https://www.linkedin.com/in/diegogh/"


HookClass = sgtk.get_hook_baseclass()


class SceneOperation(HookClass):
    """
    Hook called to perform an operation with the
    current scene
    """

    def execute(
        self, operation, file_path, context, parent_action, file_version, read_only, **kwargs
    ):
        """
        Main hook entry point

        :param operation:       String
                                Scene operation to perform

        :param file_path:       String
                                File path to use if the operation
                                requires it (e.g. open)

        :param context:         Context
                                The context the file operation is being
                                performed in.

        :param parent_action:   This is the action that this scene operation is
                                being executed for.  This can be one of:
                                - open_file
                                - new_file
                                - save_file_as
                                - version_up

        :param file_version:    The version/revision of the file to be opened.  If this is 'None'
                                then the latest version should be opened.

        :param read_only:       Specifies if the file should be opened read-only or not

        :returns:               Depends on operation:
                                'current_path' - Return the current scene
                                                 file path as a String
                                'reset'        - True if scene was reset to an empty
                                                 state, otherwise False
                                all others     - None
        """
        krita_app = Krita.instance()
        active_doc = Krita.instance().activeDocument()

        if operation == "current_path":
            current_project_filename = None
            if active_doc:
                current_project_filename = active_doc.fileName()

            return current_project_filename

        elif operation == "open":
            doc = krita_app.openDocument(file_path)
            krita_app.activeWindow().addView(doc)
            doc.waitForDone()

        elif operation == "save":
            if active_doc:
                active_doc.save()
                active_doc.waitForDone()

        elif operation == "save_as":
            if active_doc:
                success = active_doc.saveAs(file_path)
                active_doc.waitForDone()

                if success:
                    active_doc.setFileName(file_path)

        elif operation == "reset":
            if active_doc:
                active_doc.waitForDone()
                active_doc.close()

            return True

        elif operation == "prepare_new":
            krita_app.action("file_new").trigger()
            return True
