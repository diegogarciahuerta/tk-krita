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

import sgtk
from sgtk import Hook
from sgtk import TankError

__author__ = "Diego Garcia Huerta"
__contact__ = "https://www.linkedin.com/in/diegogh/"


HookClass = sgtk.get_hook_baseclass()

from krita import Krita


class SceneOperation(HookClass):
    """
    Hook called to perform an operation with the 
    current scene
    """

    def execute(self, operation, file_path, **kwargs):
        """
        Main hook entry point

        :operation: String
                    Scene operation to perform

        :file_path: String
                    File path to use if the operation
                    requires it (e.g. open)

        :returns:   Depends on operation:
                    'current_path' - Return the current scene
                                     file path as a String
                    all others     - None
        """
        app = self.parent

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
