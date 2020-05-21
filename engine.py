# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

"""A Krita engine for Tank.
https://en.wikipedia.org/wiki/Krita_(software)
"""

import os
import sys
import time
import inspect
import logging
import traceback

import tank
from tank.log import LogManager
from tank.platform import Engine
from tank.util.pyside2_patcher import PySide2Patcher
from tank.util import is_windows, is_linux, is_macos

import tank.platform.framework
import krita


__author__ = "Diego Garcia Huerta"
__contact__ = "https://www.linkedin.com/in/diegogh/"


ENGINE_NAME = "tk-krita"
APPLICATION_NAME = "Krita"


# environment variable that control if to show the compatibility warning dialog
# when Krita software version is above the tested one.
SHOW_COMP_DLG = "SGTK_COMPATIBILITY_DIALOG_SHOWN"

# this is the absolute minimum Krita version for the engine to work. Actually
# the one the engine was developed originally under, so change it at your
# own risk if needed.
MIN_COMPATIBILITY_VERSION = 4.0

# this is a place to put our persistent variables between different documents
# opened
if not hasattr(krita, "shotgun"):
    krita.shotgun = lambda: None

# Although the engine has logging already, this logger is needed for logging
# where an engine may not be present.
logger = LogManager.get_logger(__name__)


# logging functionality
def show_error(msg):
    from PyQt5.QtWidgets import QMessageBox

    batch_mode = krita.Krita.instance().batchmode()
    if not batch_mode:
        QMessageBox.critical(None, "Shotgun Error | %s engine" % APPLICATION_NAME, msg)
    else:
        display_error(msg)


def show_warning(msg):
    from PyQt5.QtWidgets import QMessageBox

    batch_mode = krita.Krita.instance().batchmode()
    if not batch_mode:
        QMessageBox.warning(None, "Shotgun Warning | %s engine" % APPLICATION_NAME, msg)
    else:
        display_warning(msg)


def show_info(msg):
    from PyQt5.QtWidgets import QMessageBox

    batch_mode = False
    if not batch_mode:
        QMessageBox.information(None, "Shotgun Info | %s engine" % APPLICATION_NAME, msg)
    else:
        display_info(msg)


def display_error(msg):
    krita.qCritical(msg)
    t = time.asctime(time.localtime())
    message = "%s - Shotgun Error | %s engine | %s " % (t, APPLICATION_NAME, msg)
    print(message)


def display_warning(msg):
    krita.qWarning(msg)
    t = time.asctime(time.localtime())
    message = "%s - Shotgun Warning | %s engine | %s " % (t, APPLICATION_NAME, msg)
    print(message)


def display_info(msg):
    # Krita 4.0.0 did not have qInfo yet, so use debug instead
    if hasattr(krita, "qInfo"):
        krita.qInfo(msg)
    else:
        krita.qDebug(msg)
    t = time.asctime(time.localtime())
    message = "%s - Shotgun Information | %s engine | %s " % (t, APPLICATION_NAME, msg)
    print(message)


def display_debug(msg):
    if os.environ.get("TK_DEBUG") == "1":
        krita.qDebug(msg)
        t = time.asctime(time.localtime())
        message = "%s - Shotgun Debug | %s engine | %s " % (t, APPLICATION_NAME, msg)
        print(message)


# methods to support the state when the engine cannot start up
# for example if a non-tank file is loaded in Krita we load the project
# context if exists, so we give a chance to the user to at least
# do the basics operations.
def refresh_engine():
    """
    refresh the current engine
    """

    logger.debug("Refreshing the engine")

    engine = tank.platform.current_engine()

    if not engine:
        # If we don't have an engine for some reason then we don't have
        # anything to do.
        logger.debug(
            "%s Refresh_engine | No currently initialized engine found; aborting the refresh of the engine\n"
            % APPLICATION_NAME
        )
        return

    _fix_tk_multi_pythonconsole(logger)

    active_doc_path = None
    active_doc = krita.Krita.instance().activeDocument()
    if active_doc:
        # determine the tk instance and context to use:
        active_doc_path = active_doc.fileName()

    if not active_doc_path:
        logger.debug("File has not been saved yet, aborting the refresh of the engine.")
        return

    # make sure path is normalized
    active_doc_path = os.path.abspath(active_doc_path)

    # we are going to try to figure out the context based on the
    # active document
    current_context = tank.platform.current_engine().context

    ctx = current_context

    # this file could be in another project altogether, so create a new
    # API instance.
    try:
        # and construct the new context for this path:
        tk = tank.sgtk_from_path(active_doc_path)
        logger.debug("Extracted sgtk instance: '%r' from path: '%r'", tk, active_doc_path)

    except tank.TankError:
        # could not detect context from path, will use the project context
        # for menus if it exists
        message = (
            "Shotgun %s Engine could not detect the context\n"
            "from the active document. Shotgun menus will be  \n"
            "stay in the current context '%s' "
            "\n" % (APPLICATION_NAME, ctx)
        )
        display_warning(message)
        return

    ctx = tk.context_from_path(active_doc_path, current_context)
    logger.debug(
        "Given the path: '%s' the following context was extracted: '%r'", active_doc_path, ctx
    )

    # default to project context in worse case scenario
    if not ctx:
        project_name = engine.context.project.get("name")
        ctx = tk.context_from_entity_dictionary(engine.context.project)
        logger.debug(
            (
                "Could not extract a context from the current active project "
                "path, so we revert to the current project '%r' context: '%r'"
            ),
            project_name,
            ctx,
        )

    # Only change if the context is different
    if ctx != current_context:
        try:
            engine.change_context(ctx)
        except tank.TankError:
            message = (
                "Shotgun %s Engine could not change context\n"
                "to '%r'. Shotgun menu will be disabled!.\n"
                "\n" % (APPLICATION_NAME, ctx)
            )
            display_warning(message)
            engine.create_shotgun_menu(disabled=True)


# TBR: DGH290420
# This is an interesting one. It is the only way I found I could fix the
# python console. Other ideas are welcomed. I could have gone the deeper
# route introspecting engine.apps but this ultimately felt simpler.
# the main issue is that PyQt5 behaves differently when returning from a
# keyPressEvent. While in PySide(2) the accepted behaviour is to return True
# or False to indicate that we want to propagate the event, in PyQt5 seems
# that a simple return indicates no propagation, whereas if we want to propagate
# the event we should simply pass it on to our parent class. I could be wrong
# in this as a general PyQt5 rule, but that is what I experienced.


def _fix_tk_multi_pythonconsole(logger):
    PythonTabWidget = None
    for module_name in sys.modules.keys():
        if "app.console" in module_name:
            module = sys.modules[module_name]
            if hasattr(module, "PythonTabWidget"):
                PythonTabWidget = module.PythonTabWidget

    if PythonTabWidget:
        try:

            def keyPressEvent(self, event):
                """
                Adds support for tab creation and navigation via hotkeys.
                """

                if bool(module.QtCore.Qt.ControlModifier & event.modifiers()):
                    # Ctrl+T to add a new tab
                    if event.key() == module.QtCore.Qt.Key_T:
                        self.add_tab()
                        return

                    # Ctrl+Shift+[ or Ctrl+Shift+] to navigate tabs
                    if bool(module.QtCore.Qt.ShiftModifier & event.modifiers()):
                        if event.key() in [module.QtCore.Qt.Key_BraceLeft]:
                            self.goto_tab(-1)
                        elif event.key() in [module.QtCore.Qt.Key_BraceRight]:
                            self.goto_tab(1)

                return super(PythonTabWidget, self).keyPressEvent(event)

            PythonTabWidget.keyPressEvent = keyPressEvent
            logger.debug(
                "Applied tk-krita fix to tk-multi-python console. Class:%s" % PythonTabWidget
            )
        except Exception:
            logger.warning(
                "Could not apply tk-krita fix to multi python console. Class: %s"
                % PythonTabWidget
            )


class PyQt5Patcher(PySide2Patcher):
    """
    Patches PyQt5 so it can be API compatible with PySide 1.
    .. code-block:: python
        from PyQt5 import QtGui, QtCore, QtWidgets
        import PyQt5
        PyQt5Patcher.patch(QtCore, QtGui, QtWidgets, PyQt5)
    """

    # Flag that will be set at the module level so that if an engine is reloaded
    # the PySide 2 API won't be monkey patched twice.

    # Note: not sure where this is in use in SGTK, but wanted to make sure
    # nothing breaks
    _TOOLKIT_COMPATIBLE = "__toolkit_compatible"

    @classmethod
    def patch(cls, QtCore, QtGui, QtWidgets, PyQt5):
        """
        Patches QtCore, QtGui and QtWidgets
        :param QtCore: The QtCore module.
        :param QtGui: The QtGui module.
        :param QtWidgets: The QtWidgets module.
        :param PyQt5: The PyQt5 module.
        """

        # Add this version info otherwise it breaks since tk_core v0.19.9
        # PySide2Patcher is now checking the version of PySide2 in a way
        # that PyQt5 does not like: __version_info__ is not defined in PyQt5
        version  = list(map(int, QtCore.PYQT_VERSION_STR.split(".")))
        PyQt5.__version_info__ = version

        QtCore, QtGui = PySide2Patcher.patch(QtCore, QtGui, QtWidgets, PyQt5)

        def SIGNAL(arg):
            """
            This is a trick to fix the fact that old style signals are not
            longer supported in pyQt5
            """
            return arg.replace("()", "")

        class QLabel(QtGui.QLabel):
            """
            Unfortunately in some cases sgtk sets the pixmap as None to remove
            the icon. This behaviour is not supported in PyQt5 and requires
            an empty instance of QPixmap.
            """

            def setPixmap(self, pixmap):
                if pixmap is None:
                    pixmap = QtGui.QPixmap()
                return super(QLabel, self).setPixmap(pixmap)

        class QPixmap(QtGui.QPixmap):
            """
            The following method is obsolete in PyQt5 so we have to provide
            a backwards compatible solution.
            https://doc.qt.io/qt-5/qpixmap-obsolete.html#grabWindow
            """

            def grabWindow(self, window, x=0, y=0, width=-1, height=-1):
                screen = QtGui.QApplication.primaryScreen()
                return screen.grabWindow(window, x=x, y=y, width=width, height=height)

        class QAction(QtGui.QAction):
            """
            From the docs:
            https://www.riverbankcomputing.com/static/Docs/PyQt5/incompatibilities.html#qt-signals-with-default-arguments

            Explanation:
            https://stackoverflow.com/questions/44371451/python-pyqt-qt-qmenu-qaction-syntax

            A lot of cases in tk apps where QAction triggered signal is
            connected with `triggered[()].connect` which in PyQt5 is a problem
            because triggered is an overloaded signal with two signatures,
            triggered = QtCore.pyqtSignal(bool)
            triggered = QtCore.pyqtSignal()
            If you wanted to use the second overload, you had to use the
            `triggered[()]` approach to avoid the extra boolean attribute to
            trip you in the callback function.
            The issue is that in PyQt5.3+ this has changed and is no longer
            allowed as only the first overloaded function is implemented and
            always called with the extra boolean value.
            To avoid this normally we would have to decorate our slots with the
            decorator:
            @QtCore.pyqtSlot
            but changing the tk apps is out of the scope of this engine.
            To fix this we implement a new signal and rewire the connections so
            it is available once more for tk apps to be happy.
            """

            triggered_ = QtCore.pyqtSignal([bool], [])

            def __init__(self, *args, **kwargs):
                super(QAction, self).__init__(*args, **kwargs)
                super(QAction, self).triggered.connect(lambda checked: self.triggered_[()])
                super(QAction, self).triggered.connect(self.triggered_[bool])
                self.triggered = self.triggered_
                self.triggered.connect(self._onTriggered)

            def _onTriggered(self, checked=False):
                self.triggered_[()].emit()

        class QAbstractButton(QtGui.QAbstractButton):
            """ See QAction above for explanation """

            clicked_ = QtCore.pyqtSignal([bool], [])
            triggered_ = QtCore.pyqtSignal([bool], [])

            def __init__(self, *args, **kwargs):
                super(QAbstractButton, self).__init__(*args, **kwargs)
                super(QAbstractButton, self).clicked.connect(lambda checked: self.clicked_[()])
                super(QAbstractButton, self).clicked.connect(self.clicked_[bool])
                self.clicked = self.clicked_
                self.clicked.connect(self._onClicked)

                super(QAction, self).triggered.connect(lambda checked: self.triggered_[()])
                super(QAction, self).triggered.connect(self.triggered_[bool])
                self.triggered = self.triggered_
                self.triggered.connect(self._onTriggered)

            def _onClicked(self, checked=False):
                self.clicked_[()].emit()

        class QObject(QtCore.QObject):
            """
            QObject no longer has got the connect method in PyQt5 so we have to
            reinvent it here...
            https://doc.bccnsoft.com/docs/PyQt5/pyqt4_differences.html#old-style-signals-and-slots
            """

            def connect(sender, signal, method, connection_type=QtCore.Qt.AutoConnection):
                if hasattr(sender, signal):
                    getattr(sender, signal).connect(method, connection_type)

        class QCheckBox(QtGui.QCheckBox):
            """
            PyQt5 no longer allows anything but an QIcon as an argument. In some
            cases sgtk is passing a pixmap, so we need to intercept the call to
            convert the pixmap to an actual QIcon.
            """

            def setIcon(self, icon):
                return super(QCheckBox, self).setIcon(QtGui.QIcon(icon))

        class QTabWidget(QtGui.QTabWidget):
            """
            For whatever reason pyQt5 is returning the name of the Tab
            including the key accelerator, the & that indicates what key is
            the shortcut. This is tripping dialog.py in tk-multi-loaders2
            """

            def tabText(self, index):
                return super(QTabWidget, self).tabText(index).replace("&", "")

        class QPyTextObject(QtCore.QObject, QtGui.QTextObjectInterface):
            """
            PyQt4 implements the QPyTextObject as a workaround for the inability
            to define a Python class that is sub-classed from more than one Qt
            class. QPyTextObject is not implemented in PyQt5
            https://doc.bccnsoft.com/docs/PyQt5/pyqt4_differences.html#qpytextobject
            """

            pass

        class QStandardItem(QtGui.QStandardItem):
            """
            PyQt5 no longer allows anything but an QIcon as an argument. In some
            cases sgtk is passing a pixmap, so we need to intercept the call to
            convert the pixmap to an actual QIcon.
            """

            def setIcon(self, icon):
                icon = QtGui.QIcon(icon)
                return super(QStandardItem, self).setIcon(icon)

        class QTreeWidgetItem(QtGui.QTreeWidgetItem):
            """
            PyQt5 no longer allows anything but an QIcon as an argument. In some
            cases sgtk is passing a pixmap, so we need to intercept the call to
            convert the pixmap to an actual QIcon.
            """

            def setIcon(self, column, icon):
                icon = QtGui.QIcon(icon)
                return super(QTreeWidgetItem, self).setIcon(column, icon)

        class QTreeWidgetItemIterator(QtGui.QTreeWidgetItemIterator):
            """
            This fixes the iteration over QTreeWidgetItems. It seems that it is
            no longer iterable, so we create our own.
            """

            def __iter__(self):
                value = self.value()
                while value:
                    yield self
                    self += 1
                    value = self.value()

        # hot patch the library to make it work with pyside code
        QtCore.SIGNAL = SIGNAL
        QtCore.Signal = QtCore.pyqtSignal
        QtCore.Slot = QtCore.pyqtSlot
        QtCore.Property = QtCore.pyqtProperty
        QtCore.__version__ = QtCore.PYQT_VERSION_STR

        # widgets and class fixes
        QtGui.QLabel = QLabel
        QtGui.QPixmap = QPixmap
        QtGui.QAction = QAction
        QtCore.QObject = QObject
        QtGui.QCheckBox = QCheckBox
        QtGui.QTabWidget = QTabWidget
        QtGui.QStandardItem = QStandardItem
        QtGui.QPyTextObject = QPyTextObject
        QtGui.QTreeWidgetItem = QTreeWidgetItem
        QtGui.QTreeWidgetItemIterator = QTreeWidgetItemIterator

        return QtCore, QtGui


class KritaEngine(Engine):
    """
    Toolkit engine for Krita.
    """

    def __init__(self, *args, **kwargs):
        """
        Engine Constructor
        """

        # Add instance variables before calling our base class
        # __init__() because the initialization may need those
        # variables.
        self._dock_widgets = []

        tank.platform.Engine.__init__(self, *args, **kwargs)

    def _define_qt_base(self):
        """
        This will be called at initialization time and will allow
        a user to control various aspects of how QT is being used
        by Toolkit. The method should return a dictionary with a number
        of specific keys, outlined below.
        * qt_core - the QtCore module to use
        * qt_gui - the QtGui module to use
        * dialog_base - base class for to use for Toolkit's dialog factory
        :returns: dict
        """
        if not self.has_ui:
            return {}

        # Proxy class used when QT does not exist on the system.
        # this will raise an exception when any QT code tries to use it

        class QTProxy(object):
            def __getattr__(self, name):
                raise tank.TankError(
                    "Looks like you are trying to run an App that uses a QT "
                    "based UI, however the engine could not find a "
                    "PyQt installation!"
                )

        base = {"qt_core": QTProxy(), "qt_gui": QTProxy(), "dialog_base": None}
        try:
            from PyQt5 import QtCore, QtGui, QtWidgets
            import PyQt5

        except ImportError as e:
            self.log_warning(
                "Error setting up PyQt. PyQt based UI support will not be available: %s" % e
            )
            self.log_debug(traceback.format_exc())
            return base

        QtCore, QtGui = PyQt5Patcher.patch(QtCore, QtGui, QtWidgets, PyQt5)

        base["qt_core"] = QtCore
        base["qt_gui"] = QtGui
        base["dialog_base"] = QtWidgets.QDialog
        logger.debug(
            "Successfully initialized PyQt '{0}' located in {1}.".format(
                QtCore.PYQT_VERSION_STR, PyQt5.__file__
            )
        )

        return base

    def has_qt5(self):
        return True

    @property
    def context_change_allowed(self):
        """
        Whether the engine allows a context change without the need for a restart.
        """
        return True

    @property
    def host_info(self):
        """
        :returns: A dictionary with information about the application hosting this engine.

        The returned dictionary is of the following form on success:

            {
                "name": "Krita",
                "version": "4.2.8",
            }

        The returned dictionary is of following form on an error preventing
        the version identification.

            {
                "name": "Krita",
                "version: "unknown"
            }
        """

        host_info = {"name": APPLICATION_NAME, "version": "unknown"}
        try:
            krita_ver = krita.Krita.instance().version()
            host_info["version"] = krita_ver
        except Exception:
            # Fallback to 'Krita' initialized above
            pass
        return host_info

    def _on_active_doc_timer(self):
        """
        Refresh the engine if the current document has changed since the last
        time we checked.
        """
        active_doc = krita.Krita.instance().activeDocument()
        if self.active_doc != active_doc:
            self.active_doc = active_doc
            refresh_engine()

    def pre_app_init(self):
        """
        Runs after the engine is set up but before any apps have been
        initialized.
        """
        from tank.platform.qt import QtCore

        # unicode characters returned by the shotgun api need to be converted
        # to display correctly in all of the app windows
        # tell QT to interpret C strings as utf-8
        utf8 = QtCore.QTextCodec.codecForName("utf-8")
        QtCore.QTextCodec.setCodecForCStrings(utf8)
        self.logger.debug("set utf-8 codec for widget text")

        # We use a timer instead of the notifier API as the API does not
        # inform us when the user changes views, only when they are created
        # cloned, or closed.
        # Since the restart of the engine every time a view is chosen is an
        # expensive operation, we will offer this functionality as am option
        # inside the context menu.
        self.active_doc = None
        self.active_doc_timer = QtCore.QTimer()
        self.active_doc_timer.timeout.connect(self._on_active_doc_timer)

    def init_engine(self):
        """
        Initializes the Krita engine.
        """
        self.logger.debug("%s: Initializing...", self)

        # check that we are running a supported OS
        if not any([is_windows(), is_linux(), is_macos()]):
            raise tank.TankError(
                "The current platform is not supported!"
                " Supported platforms "
                "are Mac, Linux 64 and Windows 64."
            )

        # check that we are running an ok version of Krita
        krita_build_version = krita.Krita.instance().version()
        krita_ver = float(".".join(krita_build_version.split(".")[:2]))

        if krita_ver < MIN_COMPATIBILITY_VERSION:
            msg = "Shotgun integration is not compatible with %s versions older than %s" % (
                APPLICATION_NAME,
                MIN_COMPATIBILITY_VERSION,
            )
            show_error(msg)
            raise tank.TankError(msg)

        if krita_ver > MIN_COMPATIBILITY_VERSION + 1:
            # show a warning that this version of Krita isn't yet fully tested
            # with Shotgun:
            msg = (
                "The Shotgun Pipeline Toolkit has not yet been fully "
                "tested with %s %s.  "
                "You can continue to use Toolkit but you may experience "
                "bugs or instability."
                "\n\n" % (APPLICATION_NAME, krita_ver)
            )

            # determine if we should show the compatibility warning dialog:
            show_warning_dlg = self.has_ui and SHOW_COMP_DLG not in os.environ

            if show_warning_dlg:
                # make sure we only show it once per session
                os.environ[SHOW_COMP_DLG] = "1"

                # split off the major version number - accommodate complex
                # version strings and decimals:
                major_version_number_str = krita_build_version.split(".")[0]
                if major_version_number_str and major_version_number_str.isdigit():
                    # check against the compatibility_dialog_min_version
                    # setting
                    min_ver = self.get_setting("compatibility_dialog_min_version")
                    if int(major_version_number_str) < min_ver:
                        show_warning_dlg = False

            if show_warning_dlg:
                # Note, title is padded to try to ensure dialog isn't insanely
                # narrow!
                show_info(msg)

            # always log the warning to the script editor:
            self.logger.warning(msg)

            # In the case of Windows, we have the possibility of locking up if
            # we allow the PySide shim to import QtWebEngineWidgets.
            # We can stop that happening here by setting the following
            # environment variable.

            # Note that prior PyQt5 v5.12 this module existed, after that it has
            # been separated and would not cause any issues. Since it is no
            # harm if the module is not there, we leave it just in case older
            # versions of Krita were using previous versions of PyQt
            # https://www.riverbankcomputing.com/software/pyqtwebengine/intro
            if is_windows():
                self.logger.debug(
                    "This application on Windows can deadlock if QtWebEngineWidgets "
                    "is imported. Setting "
                    "SHOTGUN_SKIP_QTWEBENGINEWIDGETS_IMPORT=1..."
                )
                os.environ["SHOTGUN_SKIP_QTWEBENGINEWIDGETS_IMPORT"] = "1"

        # check that we can load the GUI libraries
        self._init_pyside()

        # default menu name is Shotgun but this can be overriden
        # in the configuration to be Sgtk in case of conflicts
        self._menu_name = "Shotgun"
        if self.get_setting("use_sgtk_as_menu_name", False):
            self._menu_name = "Sgtk"

    def __get_active_document_context_switch(self):
        """
        Returns the status of the automatic context switch.
        """
        if not hasattr(krita.shotgun, "active_document_context_switch"):
            krita.shotgun.active_document_context_switch = self.get_setting(
                "active_document_context_switch", False
            )

        return krita.shotgun.active_document_context_switch

    def __set_active_document_context_switch(self, value):
        """
        Sets the status of the automatic context switch.
        """
        krita.shotgun.active_document_context_switch = value

        self.log_info("set_active_document_context_switch: %s" % value)

        if not value:
            self.active_doc_timer.stop()
        else:
            self.active_doc_timer.start(1000)

    active_document_context_switch = property(
        __get_active_document_context_switch, __set_active_document_context_switch
    )

    def toggle_active_document_context_switch(self):
        """
        Toggles the automatic switch context when the view is changed. If the
        filename of the view is different than the current one, we restart the
        engine with a new context if different than the current.
        """
        self.active_document_context_switch = not self.active_document_context_switch

        return self.active_document_context_switch

    def create_shotgun_menu(self, disabled=False):
        """
        Creates the main shotgun menu in Krita.
        Note that this only creates the menu, not the child actions
        :return: bool
        """

        # only create the shotgun menu if not in batch mode and menu doesn't
        # already exist
        if self.has_ui:
            # create our menu handler
            tk_krita = self.import_module("tk_krita")
            if tk_krita.can_create_menu():
                self.logger.debug("Creating shotgun menu...")
                self._menu_generator = tk_krita.MenuGenerator(self, self._menu_name)
                self._menu_generator.create_menu(disabled=disabled)
            else:
                self.logger.debug("Waiting for menu to be created...")
                from sgtk.platform.qt import QtCore

                QtCore.QTimer.singleShot(200, self.create_shotgun_menu)
            return True

        return False

    def post_app_init(self):
        """
        Called when all apps have initialized
        """
        tank.platform.engine.set_current_engine(self)

        # create the shotgun menu
        self.create_shotgun_menu()

        # let's close the windows created by the engine before exiting the
        # application
        from sgtk.platform.qt import QtGui

        app = QtGui.QApplication.instance()
        app.aboutToQuit.connect(self.destroy_engine)

        # apply a fix to multi python console if loaded
        pythonconsole_app = self.apps.get("tk-multi-pythonconsole")
        if pythonconsole_app:
            _fix_tk_multi_pythonconsole(self.logger)

        # Run a series of app instance commands at startup.
        self._run_app_instance_commands()

    def post_context_change(self, old_context, new_context):
        """
        Runs after a context change. The Krita event watching will be stopped
        and new callbacks registered containing the new context information.

        :param old_context: The context being changed away from.
        :param new_context: The new context being changed to.
        """

        # apply a fix to multi python console if loaded
        pythonconsole_app = self.apps.get("tk-multi-pythonconsole")
        if pythonconsole_app:
            _fix_tk_multi_pythonconsole(self.logger)

        if self.get_setting("automatic_context_switch", True):
            # finally create the menu with the new context if needed
            if old_context != new_context:
                self.create_shotgun_menu()

    def _run_app_instance_commands(self):
        """
        Runs the series of app instance commands listed in the
        'run_at_startup' setting of the environment configuration YAML file.
        """

        # Build a dictionary mapping app instance names to dictionaries of
        # commands they registered with the engine.
        app_instance_commands = {}
        for (cmd_name, value) in self.commands.items():
            app_instance = value["properties"].get("app")
            if app_instance:
                # Add entry 'command name: command function' to the command
                # dictionary of this app instance.
                cmd_dict = app_instance_commands.setdefault(app_instance.instance_name, {})
                cmd_dict[cmd_name] = value["callback"]

        # Run the series of app instance commands listed in the
        # 'run_at_startup' setting.
        for app_setting_dict in self.get_setting("run_at_startup", []):
            app_instance_name = app_setting_dict["app_instance"]

            # Menu name of the command to run or '' to run all commands of the
            # given app instance.
            setting_cmd_name = app_setting_dict["name"]

            # Retrieve the command dictionary of the given app instance.
            cmd_dict = app_instance_commands.get(app_instance_name)

            if cmd_dict is None:
                self.logger.warning(
                    "%s configuration setting 'run_at_startup' requests app"
                    " '%s' that is not installed.",
                    self.name,
                    app_instance_name,
                )
            else:
                if not setting_cmd_name:
                    # Run all commands of the given app instance.
                    for (cmd_name, command_function) in cmd_dict.items():
                        msg = (
                            "%s startup running app '%s' command '%s'.",
                            self.name,
                            app_instance_name,
                            cmd_name,
                        )
                        self.logger.debug(msg)

                        command_function()
                else:
                    # Run the command whose name is listed in the
                    # 'run_at_startup' setting.
                    command_function = cmd_dict.get(setting_cmd_name)
                    if command_function:
                        msg = (
                            "%s startup running app '%s' command '%s'.",
                            self.name,
                            app_instance_name,
                            setting_cmd_name,
                        )
                        self.logger.debug(msg)

                        command_function()
                    else:
                        known_commands = ", ".join("'%s'" % name for name in cmd_dict)
                        self.logger.warning(
                            "%s configuration setting 'run_at_startup' "
                            "requests app '%s' unknown command '%s'. "
                            "Known commands: %s",
                            self.name,
                            app_instance_name,
                            setting_cmd_name,
                            known_commands,
                        )

    def destroy_engine(self):
        """
        Let's close the windows created by the engine before exiting the
        application
        """
        self.logger.debug("%s: Destroying...", self)
        self.close_windows()

    def _init_pyside(self):
        """
        Checks if we can load PyQt5 in this application
        """

        # import QtWidgets first or we are in trouble
        try:
            import PyQt5.QtWidgets
        except Exception as e:
            traceback.print_exc()
            self.logger.error(
                "PyQt5 could not be imported! Apps using UI"
                " will not operate correctly!"
                "Error reported: %s",
                e,
            )

    def _get_dialog_parent(self):
        """
        Get the QWidget parent for all dialogs created through
        show_dialog & show_modal.
        """
        import PyQt5.QtWidgets
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        for widget in app.topLevelWidgets():
            if isinstance(widget, PyQt5.QtWidgets.QMainWindow):
                return widget

    def show_panel(self, panel_id, title, bundle, widget_class, *args, **kwargs):
        """
        Docks an app widget in a Krita Docket, (conveniently borrowed from the
        tk-3dsmax engine)
        :param panel_id: Unique identifier for the panel, as obtained by register_panel().
        :param title: The title of the panel
        :param bundle: The app, engine or framework object that is associated with this window
        :param widget_class: The class of the UI to be constructed. 
                             This must derive from QWidget.
        Additional parameters specified will be passed through to the widget_class constructor.
        :returns: the created widget_class instance
        """
        from sgtk.platform.qt import QtGui, QtCore

        dock_widget_id = "sgtk_dock_widget_" + panel_id

        main_window = self._get_dialog_parent()
        dock_widget = main_window.findChild(QtGui.QDockWidget, dock_widget_id)

        if dock_widget is None:
            # The dock widget wrapper cannot be found in the main window's
            # children list so that means it has not been created yet, so create it.
            widget_instance = widget_class(*args, **kwargs)
            widget_instance.setParent(self._get_dialog_parent())
            widget_instance.setObjectName(panel_id)

            class DockWidget(QtGui.QDockWidget):
                """
                Widget used for docking app panels that ensures the widget is closed when the 
                dock is closed
                """

                closed = QtCore.pyqtSignal(QtCore.QObject)

                def closeEvent(self, event):
                    widget = self.widget()
                    if widget:
                        widget.close()
                    self.closed.emit(self)

            dock_widget = DockWidget(title, parent=main_window)
            dock_widget.setObjectName(dock_widget_id)
            dock_widget.setWidget(widget_instance)
            # Add a callback to remove the dock_widget from the list of open
            # panels and delete it
            dock_widget.closed.connect(self._remove_dock_widget)

            # Remember the dock widget, so we can delete it later.
            self._dock_widgets.append(dock_widget)
        else:
            # The dock widget wrapper already exists, so just get the
            # shotgun panel from it.
            widget_instance = dock_widget.widget()

        # apply external style sheet
        self._apply_external_stylesheet(bundle, widget_instance)

        if not main_window.restoreDockWidget(dock_widget):
            # The dock widget cannot be restored from the main window's state,
            # so dock it to the right dock area and make it float by default.
            main_window.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock_widget)
            dock_widget.setFloating(True)

        dock_widget.show()
        return widget_instance

    def _remove_dock_widget(self, dock_widget):
        """
        Removes a docked widget (panel) opened by the engine
        """
        self._get_dialog_parent().removeDockWidget(dock_widget)
        self._dock_widgets.remove(dock_widget)
        dock_widget.deleteLater()

    @property
    def has_ui(self):
        """
        Detect and return if Krita is running in batch mode
        """
        batch_mode = krita.Krita.instance().batchmode()
        return not batch_mode

    def _emit_log_message(self, handler, record):
        """
        Called by the engine to log messages in Krita script editor.
        All log messages from the toolkit logging namespace will be passed to
        this method.

        :param handler: Log handler that this message was dispatched from.
                        Its default format is "[levelname basename] message".
        :type handler: :class:`~python.logging.LogHandler`
        :param record: Standard python logging record.
        :type record: :class:`~python.logging.LogRecord`
        """
        # Give a standard format to the message:
        #     Shotgun <basename>: <message>
        # where "basename" is the leaf part of the logging record name,
        # for example "tk-multi-shotgunpanel" or "qt_importer".
        if record.levelno < logging.INFO:
            formatter = logging.Formatter("Debug: Shotgun %(basename)s: %(message)s")
        else:
            formatter = logging.Formatter("Shotgun %(basename)s: %(message)s")

        msg = formatter.format(record)

        # Select Krita display function to use according to the logging
        # record level.
        if record.levelno >= logging.ERROR:
            fct = display_error
        elif record.levelno >= logging.WARNING:
            fct = display_warning
        elif record.levelno >= logging.INFO:
            fct = display_info
        else:
            fct = display_debug

        # Display the message in Krita script editor in a thread safe manner.
        self.async_execute_in_main_thread(fct, msg)

    def close_windows(self):
        """
        Closes the various windows (dialogs, panels, etc.) opened by the
        engine.
        """
        self.logger.debug("Closing all engine dialogs...")

        # Make a copy of the list of Tank dialogs that have been created by the
        # engine and are still opened since the original list will be updated
        # when each dialog is closed.
        opened_dialog_list = self.created_qt_dialogs[:]

        # Loop through the list of opened Tank dialogs.
        for dialog in opened_dialog_list:
            dialog_window_title = dialog.windowTitle()
            try:
                # Close the dialog and let its close callback remove it from
                # the original dialog list.
                dialog.close()
            except Exception as exception:
                traceback.print_exc()
                self.logger.error("Cannot close dialog %s: %s", dialog_window_title, exception)

        # Close all dock widgets previously added.
        for dock_widget in self._dock_widgets[:]:
            dock_widget.close()
