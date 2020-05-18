# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import sys
import cgitb
import shutil
import hashlib


import sgtk
from sgtk.platform import SoftwareLauncher, SoftwareVersion, LaunchInformation
from sgtk.pipelineconfig_utils import get_sgtk_module_path


__author__ = "Diego Garcia Huerta"
__contact__ = "https://www.linkedin.com/in/diegogh/"


ENGINE_NAME = "tk-krita"
APPLICATION_NAME = "Krita"

logger = sgtk.LogManager.get_logger(__name__)

# Let's enable cool and detailed tracebacks
cgitb.enable(format="text")


def sha256(fname):
    hash_sha256 = hashlib.sha256()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()


def samefile(file1, file2):
    return sha256(file1) == sha256(file2)


# based on:
# https://stackoverflow.com/questions/38876945/copying-and-merging-directories-excluding-certain-extensions
def copytree_multi(src, dst, symlinks=False, ignore=None):
    names = os.listdir(src)
    if ignore is not None:
        ignored_names = ignore(src, names)
    else:
        ignored_names = set()

    if not os.path.isdir(dst):
        os.makedirs(dst)

    errors = []
    for name in names:
        if name in ignored_names:
            continue
        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)

        try:
            if symlinks and os.path.islink(srcname):
                linkto = os.readlink(srcname)
                os.symlink(linkto, dstname)
            elif os.path.isdir(srcname):
                copytree_multi(srcname, dstname, symlinks, ignore)
            else:
                if os.path.exists(dstname):
                    if not samefile(srcname, dstname):
                        os.unlink(dstname)
                        shutil.copy2(srcname, dstname)
                        logger.info("File copied: %s" % dstname)
                    else:
                        # same file, so ignore the copy
                        logger.info("Same file, skipping: %s" % dstname)
                        pass
                else:
                    shutil.copy2(srcname, dstname)
        except (IOError, os.error) as why:
            errors.append((srcname, dstname, str(why)))
        except shutil.Error as err:
            errors.extend(err.args[0])
    try:
        shutil.copystat(src, dst)
    except WindowsError:
        pass
    except OSError as why:
        errors.extend((src, dst, str(why)))
    if errors:
        raise shutil.Error(errors)


def ensure_scripts_up_to_date(engine_scripts_path, scripts_folder):
    logger.info("Updating scripts...: %s" % engine_scripts_path)
    logger.info("                     scripts_folder: %s" % scripts_folder)

    copytree_multi(engine_scripts_path, scripts_folder)

    return True


class KritaLauncher(SoftwareLauncher):
    """
    Handles launching application executables. Automatically starts up
    the shotgun engine with the current context in the new session
    of the application.
    """

    # Named regex strings to insert into the executable template paths when
    # matching against supplied versions and products. Similar to the glob
    # strings, these allow us to alter the regex matching for any of the
    # variable components of the path in one place
    COMPONENT_REGEX_LOOKUP = {
        "platform": r"\(x86\)|\(x64\)",
        "platform_version": r"\(x86\)|\(x64\)",
    }

    # This dictionary defines a list of executable template strings for each
    # of the supported operating systems. The templates are used for both
    # globbing and regex matches by replacing the named format placeholders
    # with an appropriate glob or regex string.

    EXECUTABLE_TEMPLATES = {
        "darwin": ["$KRITA_BIN", "/Applications/krita/Krita/Krita.app"],
        "win32": [
            "$KRITA_BIN",
            "C:/Program Files/Krita {platform_version}/bin/krita.exe",
            "C:/Program Files {platform}/Krita {platform_version}/bin/krita.exe",
        ],
        "linux": ["$KRITA_BIN", "/usr/bin/krita"],
    }

    def prepare_launch(self, exec_path, args, file_to_open=None):
        """
        Prepares an environment to launch in that will automatically
        load Toolkit and the engine when the application starts.

        :param str exec_path: Path to application executable to launch.
        :param str args: Command line arguments as strings.
        :param str file_to_open: (optional) Full path name of a file to open on
                                            launch.
        :returns: :class:`LaunchInformation` instance
        """
        required_env = {}

        resources_plugins_path = os.path.join(self.disk_location, "resources", "extensions")

        # Run the engine's init.py file when the application starts up
        startup_path = os.path.join(self.disk_location, "startup", "init.py")
        required_env["SGTK_KRITA_ENGINE_STARTUP"] = startup_path.replace("\\", "/")

        # Prepare the launch environment with variables required by the
        # classic bootstrap approach.
        self.logger.debug(
            "Preparing %s Launch via Toolkit Classic methodology ..." % APPLICATION_NAME
        )

        required_env["SGTK_ENGINE"] = ENGINE_NAME
        required_env["SGTK_CONTEXT"] = sgtk.context.serialize(self.context)
        required_env["SGTK_MODULE_PATH"] = get_sgtk_module_path()
        required_env["__COMPAT_LAYER"] = ""

        if file_to_open:
            # Add the file name to open to the launch environment
            required_env["SGTK_FILE_TO_OPEN"] = file_to_open

        if sys.platform == "win32":
            user_plugins_path = os.path.expandvars(r"%APPDATA%\krita\pykrita")
        else:
            raise NotImplementedError

        ensure_scripts_up_to_date(resources_plugins_path, user_plugins_path)

        os.chdir(os.path.dirname(os.path.dirname(exec_path)))
        return LaunchInformation(path=exec_path, environ=required_env)

    def _icon_from_engine(self):
        """
        Use the default engine icon as the application does not supply
        an icon in their software directory structure.

        :returns: Full path to application icon as a string or None.
        """

        # the engine icon
        engine_icon = os.path.join(self.disk_location, "icon_256.png")
        return engine_icon

    def scan_software(self):
        """
        Scan the filesystem for the application executables.

        :return: A list of :class:`SoftwareVersion` objects.
        """
        self.logger.debug("Scanning for %s executables..." % APPLICATION_NAME)

        supported_sw_versions = []
        for sw_version in self._find_software():
            supported_sw_versions.append(sw_version)

        return supported_sw_versions

    def _find_software(self):
        """
        Find executables in the default install locations.
        """

        # all the executable templates for the current OS
        executable_templates = self.EXECUTABLE_TEMPLATES.get(
            "darwin"
            if sgtk.util.is_macos()
            else "win32"
            if sgtk.util.is_windows()
            else "linux"
            if sgtk.util.is_linux()
            else []
        )

        # all the discovered executables
        found = False
        sw_versions = []

        for executable_template in executable_templates:
            self.logger.debug("PreProcessing template %s.", executable_template)
            executable_template = os.path.expanduser(executable_template)
            executable_template = os.path.expandvars(executable_template)

            self.logger.debug("Processing template %s.", executable_template)

            executable_matches = self._glob_and_match(
                executable_template, self.COMPONENT_REGEX_LOOKUP
            )

            # Extract all products from that executable.
            for (executable_path, key_dict) in executable_matches:
                # extract the matched keys form the key_dict (default to None
                # if not included)
                self.logger.debug(
                    "Processing executable_path: %s | dict %s", executable_path, key_dict
                )

                # no way to extract the version from this application, so no
                # version is available to display
                executable_version = " "

                sw_versions.append(
                    SoftwareVersion(
                        executable_version,
                        APPLICATION_NAME,
                        executable_path,
                        self._icon_from_engine(),
                    )
                )
                # TBR DGH060520
                # break here if you found one executable, at least until we
                # find a way to track different versions of Krita.
                # Note that kritarunner is one of them but way too convoluted
                # for what is really worth. I welcome other ideas!
                found = True
                break

            if found:
                break

        return sw_versions
