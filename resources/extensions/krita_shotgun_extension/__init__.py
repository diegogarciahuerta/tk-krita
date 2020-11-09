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

from .shotgun_bridge import ShotgunBridge

__author__ = "Diego Garcia Huerta"
__contact__ = "https://www.linkedin.com/in/diegogh/"


# And add the extension to Krita's list of extensions:
app = Krita.instance()

# Instantiate your class:
extension = ShotgunBridge(parent=app)
app.addExtension(extension)
