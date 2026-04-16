import platform
from typing import Mapping
from urllib.parse import urlencode
import xbmcaddon
import xbmcgui
import ctypes
import os
from .addonpaths import ADDON, ADDON_ID, ADDON_PATH, ADDON_VERSION
import stat
from .logger import log
import sys
import tempfile
import errno
import shutil
import filecmp
import json

addon       = xbmcaddon.Addon()
addonname   = addon.getAddonInfo('name')
basestring = (str, bytes)

def prepare_body(data):
	content_type = None
	if data:
		body = encode_params(data)
		if isinstance(data, basestring) or hasattr(data, 'read'):
				content_type = None
		else:
				content_type = 'application/x-www-form-urlencoded'
                        
		return body, content_type
                        
def encode_params(data):
	if hasattr(data, '__iter__'):
		result = []
		for k, vs in to_key_val_list(data):
				if isinstance(vs, basestring) or not hasattr(vs, '__iter__'):
						vs = [vs]
				for v in vs:
						if v is not None:
								result.append(
										(k.encode('utf-8') if isinstance(k, str) else k,
											v.encode('utf-8') if isinstance(v, str) else v))
		return urlencode(result, doseq=True)

def to_key_val_list(value):
    """Take an object and test to see if it can be represented as a
    dictionary. If it can be, return a list of tuples, e.g.,

    ::

        >>> to_key_val_list([('key', 'val')])
        [('key', 'val')]
        >>> to_key_val_list({'key': 'val'})
        [('key', 'val')]
        >>> to_key_val_list('string')
        Traceback (most recent call last):
        ...
        ValueError: cannot encode objects that are not 2-tuples

    :rtype: list
    """
    if value is None:
        return None

    if isinstance(value, (str, bytes, bool, int)):
        raise ValueError('cannot encode objects that are not 2-tuples')

    if isinstance(value, Mapping):
        value = value.items()

    return list(value)

def translatePath(path):
    try:
        from xbmcvfs import translatePath
    except ImportError:
        from xbmc import translatePath

    return translatePath(path)

def ensure_exec_perms(file_):
    st = os.stat(file_)
    os.chmod(file_, st.st_mode | stat.S_IEXEC)
    return file_

def android_get_current_appid():
    with open("/proc/%d/cmdline" % os.getpid()) as fp:
        return fp.read().rstrip("\0")
    
def read_current_version(dest_dir):
    p = os.path.join(dest_dir, "version")
    if os.path.exists(p):
        try:
            with open(p, 'r') as file:
                return file.read().replace('\n', '')
        except:
            pass
    return ""

def get_lib_binary():
    global log_path
    global custom_path
    global binary_platform

    try:
        if platform.system() == 'Windows':
            binary_platform = {
                "auto_arch": sys.maxsize > 2 ** 32 and "64-bit" or "32-bit",
                "arch": sys.maxsize > 2 ** 32 and "x64" or "x86",
                "os": "windows",
                "version": "",
                "fork": True,
                "machine": "",
                "system": "",
                "platform": ""
            }
        else:
            binary_platform = {
                "auto_arch": sys.maxsize > 2 ** 32 and "64-bit" or "32-bit",
                "arch": sys.maxsize > 2 ** 32 and "arm64" or "arm",
                "os": "android",
                "version": "",
                "fork": True,
                "machine": "",
                "system": "",
                "platform": ""
            }
    except Exception:
        binary_platform = {
            "auto_arch": sys.maxsize > 2 ** 32 and "64-bit" or "32-bit",
            "arch": sys.maxsize > 2 ** 32 and "arm64" or "arm",
            "os": "android",
            "version": "",
            "fork": True,
            "machine": "",
            "system": "",
            "platform": ""
        }
    

    #binary_platform = get_platform()

    binary = "NativeHttpClient" + (binary_platform["os"] == "windows" and ".dll" or ".so")
    binary_dir = os.path.join(ADDON_PATH, "packages", "bin", "%(os)s_%(arch)s" % binary_platform)

    if binary_platform["os"] == "android":
        log.info("Detected binary folder: %s" % binary_dir)
        binary_dir_legacy = binary_dir.replace("/storage/emulated/0", "/storage/emulated/legacy")
        if "/storage/emulated/legacy" in binary_dir_legacy and os.path.exists(binary_dir_legacy):
            binary_dir = binary_dir_legacy
            log.info("Using changed binary folder for Android: %s" % binary_dir)

        xbmc_bin = translatePath("special://xbmcbin/")
        xbmc_data_path = xbmc_bin

        if not os.path.exists(xbmc_data_path) or not is_writable(xbmc_data_path):
            app_id = android_get_current_appid()
            log.info("%s path does not exist, so using %s as xbmc_data_path" % (xbmc_data_path, os.path.join("/data", "data", app_id)))
            xbmc_data_path = os.path.join("/data", "data", app_id)

        if not os.path.exists(xbmc_data_path):
            log.info("%s path does not exist, so using %s as xbmc_data_path" % (xbmc_data_path, translatePath("special://masterprofile/")))
            xbmc_data_path = translatePath("special://masterprofile/")

        dest_binary_dir = os.path.join(xbmc_data_path, "files", ADDON_ID, "bin", "%(os)s_%(arch)s" % binary_platform)
        custom_path = os.path.join(xbmc_data_path, "files", ADDON_ID)
        log_path = os.path.join(custom_path, "foxtel.log")
    else:
        try:
            dest_binary_dir = os.path.join(translatePath(ADDON.getAddonInfo("profile")).decode('utf-8'), "bin", "%(os)s_%(arch)s" % binary_platform)
        except Exception:
            dest_binary_dir = os.path.join(translatePath(ADDON.getAddonInfo("profile")), "bin", "%(os)s_%(arch)s" % binary_platform)

    binary_path = os.path.join(binary_dir, binary)
    dest_binary_path = os.path.join(dest_binary_dir, binary)
    installed_version = read_current_version(binary_dir)

    log.info("Binary detection. Version: %s, Source: %s, Destination: %s" % (installed_version, binary_path, dest_binary_path))

    # if not os.path.exists(binary_path):
    #     try:
    #         os.makedirs(binary_dir)
    #     except OSError as e:
    #         if e.errno != errno.EEXIST:
    #             raise
            
    #     log.error("Unable to download binary to destination path")
 

    if not os.path.exists(binary_path):
        # notify((getLocalizedString(30103) + " %(os)s_%(arch)s" % PLATFORM), time=7000)
        #dialog_ok("LOCALIZE[30347];;" + "%(os)s_%(arch)s" % binary_platform)
        #system_information()
        try:
            log.info("Source directory not found (%s):\n%s" % (binary_dir, os.listdir(os.path.join(binary_dir, ".."))))
            log.info("Destination directory (%s):\n%s" % (dest_binary_dir, os.listdir(os.path.join(dest_binary_dir, ".."))))
        except Exception:
            pass
        return False, False

    if os.path.isdir(dest_binary_path):
        log.warning("Destination path is a directory, expected previous binary file, removing...")
        try:
            shutil.rmtree(dest_binary_path)
        except Exception as e:
            log.error("Unable to remove destination path for update: %s" % e)
            #system_information()
            return False, False

    if not os.path.exists(dest_binary_path) or not os.path.exists(binary_path) or not filecmp.cmp(dest_binary_path, binary_path, shallow=True):
        log.info("Updating foxtel from %s => %s ..." % (binary_dir, dest_binary_dir))
        try:
            os.makedirs(dest_binary_dir)
        except OSError:
            pass
        try:
            shutil.rmtree(dest_binary_dir)
        except Exception as e:
            log.error("Unable to remove destination path for update: %s" % e)
            #system_information()
            pass
        try:
            shutil.copytree(binary_dir, dest_binary_dir)
        except Exception as e:
            log.error("Unable to copy to destination path for update: %s" % e)
            #system_information()
            return False, False

    # Clean stale files in the directory, as this can cause headaches on
    # Android when they are unreachable
    dest_files = set(os.listdir(dest_binary_dir))
    orig_files = set(os.listdir(binary_dir))
    log.info("Deleting stale files %s" % (dest_files - orig_files))
    for file_ in (dest_files - orig_files):
        path = os.path.join(dest_binary_dir, file_)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    log.info("Binary detection: [ Source: %s, Destination: %s ]" % (binary_path, dest_binary_path))
    return dest_binary_dir, ensure_exec_perms(dest_binary_path)

def is_writable(path):
    try:
        testfile = tempfile.TemporaryFile(dir=path)
        testfile.close()
    except:
        return False
    return True