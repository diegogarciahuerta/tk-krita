import os
import imp
import sys

from krita import Extension, qWarning

__author__ = "Diego Garcia Huerta"
__contact__ = "https://www.linkedin.com/in/diegogh/"


EXTENSION_ID = "pykrita_shotgun_bridge"
MENU_ENTRY = "Shotgun"

SGTK_MODULE_PATH = os.environ.get("SGTK_MODULE_PATH")
if SGTK_MODULE_PATH and SGTK_MODULE_PATH not in sys.path:
    sys.path.insert(0, SGTK_MODULE_PATH)


class ShotgunBridge(Extension):
    """
    Basic Krita extension to trigger the toolkit startup once Krita has
    been initialized.
    """

    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        pass

    def createActions(self, window):
        # only bootstrap if we are in a shotgun environment
        if SGTK_MODULE_PATH:
            self.bootstrap()
        else:
            qWarning(
                "Krita was not run within a Shotgun Environment. "
                "Skipping ShotgunBridge Extension."
            )

    def bootstrap(self):
        engine_startup_path = os.environ.get("SGTK_KRITA_ENGINE_STARTUP")
        engine_startup = imp.load_source("sgtk_krita_engine_startup", engine_startup_path)

        # Fire up Toolkit and the environment engine when there's time.
        engine_startup.start_toolkit()
