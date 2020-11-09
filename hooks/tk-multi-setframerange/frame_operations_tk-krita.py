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
from sgtk import TankError


__author__ = "Diego Garcia Huerta"
__contact__ = "https://www.linkedin.com/in/diegogh/"


HookBaseClass = sgtk.get_hook_baseclass()

from krita import Krita


class FrameOperation(HookBaseClass):
    """
    Hook called to perform a frame operation with the
    current scene
    """

    def get_frame_range(self, **kwargs):
        """
        get_frame_range will return a tuple of (in_frame, out_frame)
        :returns: Returns the frame range in the form (in_frame, out_frame)
        :rtype: tuple[int, int]
        """

        krita_app = Krita.instance()
        active_doc = Krita.instance().activeDocument()

        current_in = 0
        current_out = 0

        if active_doc:
            current_in = int(active_doc.fullClipRangeStartTime())
            current_out = int(active_doc.fullClipRangeEndTime())

        return (current_in, current_out)

    def set_frame_range(self, in_frame=None, out_frame=None, **kwargs):
        """
        set_frame_range will set the frame range using `in_frame` and `out_frame`
        :param int in_frame: in_frame for the current context
            (e.g. the current shot, current asset etc)
        :param int out_frame: out_frame for the current context
            (e.g. the current shot, current asset etc)
        """

        krita_app = Krita.instance()
        active_doc = Krita.instance().activeDocument()

        if active_doc:
            active_doc.setFullClipRangeStartTime(int(in_frame))
            active_doc.setFullClipRangeEndTime(int(out_frame))
