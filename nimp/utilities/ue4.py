# -*- coding: utf-8 -*-

#-------------------------------------------------------------------------------
import socket
import random
import string
import time
import contextlib
import shutil
import os

from nimp.utilities.build import *
from nimp.utilities.deployment import *
from nimp.utilities.file_mapper import *
from nimp.utilities.perforce import *
from nimp.utilities.system import *


#---------------------------------------------------------------------------
def ue4_build(env):
    if not env.ue4_build_configuration:
        log_error("Invalid empty value for configuration")
        return False

    if env.disable_unity:
        os.environ['UBT_bUseUnityBuild'] = 'false'

    # Bootstrap if necessary
    if hasattr(env, 'bootstrap') and env.bootstrap:
        # The project file generation requires RPCUtility and Ionic.Zip.Reduced very early
        if not vsbuild('Engine/Source/Programs/RPCUtility/RPCUtility.sln',
                       'Any CPU', 'Development', None, '11', 'Build'):
            log_error("Could not build RPCUtility")
            return False

        # HACK: For some reason nothing copies this file on OS X
        if platform.system() == 'Darwin':
            robocopy('Engine/Binaries/ThirdParty/Ionic/Ionic.Zip.Reduced.dll',
                     'Engine/Binaries/DotNET/Ionic.Zip.Reduced.dll')

        # Now generate project files
        if _ue4_generate_project() != 0:
            log_error("Error generating UE4 project files")
            return False

    # The Durango XDK does not support Visual Studio 2013 yet, so if UE4
    # detected it, it created VS 2012 project files and we have to use that
    # version to build the tools instead.
    vs_version = '12'
    try:
        for line in open(env.solution):
            if '# Visual Studio 2012' in line:
                vs_version = '11'
                break
    except:
        pass

    # We’ll try to build all tools even in case of failure
    result = True

    # List of tools to build
    tools = []

    if env.target == 'tools':

        tools += [ 'UnrealFrontend',
                   'UnrealFileServer',
                   'ShaderCompileWorker', ]

        if env.platform != 'mac':
            tools += [ 'UnrealLightmass', ] # doesn’t build (yet?)

        if env.platform == 'linux':
            tools += [ 'CrossCompilerTool', ]

        if env.platform == 'win64':
            tools += [ 'DotNETUtilities',
                       'AutomationTool',
                       'PS4DevKitUtil',
                       'PS4MapFileUtil',
                       'XboxOnePDBFileUtil',
                       'SymbolDebugger', ]

    # Some tools are necessary even when not building tools...
    if env.platform == 'ps4':
        if 'PS4MapFileUtil' not in tools: tools += [ 'PS4MapFileUtil' ]

    if env.platform == 'xboxone':
        if 'XboxOnePDBFileUtil' not in tools: tools += [ 'XboxOnePDBFileUtil' ]

    # Build tools from the main solution
    for tool in tools:
        if not _ue4_build_project(env.solution, tool,
                                  'Win64', 'Development', vs_version, 'Build'):
            log_error("Could not build %s" % (tool, ))
            result = False

    # Build tools from other solutions or with other flags
    if env.target == 'tools':

        if not vsbuild('Engine/Source/Programs/NetworkProfiler/NetworkProfiler.sln',
                       'Any CPU', 'Development', None, vs_version, 'Build'):
            log_error("Could not build NetworkProfiler")
            result = False

        if env.platform != 'mac':
            # This also builds AgentInterface.dll, needed by SwarmInterface.sln
            if not vsbuild('Engine/Source/Programs/UnrealSwarm/UnrealSwarm.sln',
                           'Any CPU', 'Development', None, vs_version, 'Build'):
                log_error("Could not build UnrealSwarm")
                result = False

            if not vsbuild('Engine/Source/Editor/SwarmInterface/DotNET/SwarmInterface.sln',
                           'Any CPU', 'Development', None, vs_version, 'Build'):
                log_error("Could not build SwarmInterface")
                result = False

        # These tools seem to be Windows only for now
        if env.platform == 'win64':

            if not _ue4_build_project(env.solution, 'BootstrapPackagedGame',
                                      'Win64', 'Shipping', vs_version, 'Build'):
                log_error("Could not build BootstrapPackagedGame")
                result = False

            if not vsbuild('Engine/Source/Programs/XboxOne/XboxOnePackageNameUtil/XboxOnePackageNameUtil.sln',
                           'x64', 'Development', None, '11', 'Build'):
                log_error("Could not build XboxOnePackageNameUtil")
                result = False

    if not result:
        return result

    if env.target == 'game':
        if not _ue4_build_project(env.solution, env.game, env.ue4_build_platform,
                                  env.ue4_build_configuration, vs_version, 'Build'):
            return False

    if env.target == 'editor':
        if not _ue4_build_project(env.solution, env.game, env.ue4_build_platform,
                                  env.ue4_build_configuration + ' Editor', vs_version, 'Build'):
            return False

    return True


#
# Generate UE4 project files
#

def _ue4_generate_project():
    if is_msys():
        return call_process('.', ['./GenerateProjectFiles.bat'])
    else:
        return call_process('.', ['/bin/sh', 'GenerateProjectFiles.sh'])


#
# Helper commands for configuration sanitising
#

def get_ue4_build_config(config, ignored = None): # TODO: make sure the 2nd argument is no longer used by callers
    d = { "debug"    : "Debug",
          "devel"    : "Development",
          "test"     : "Test",
          "shipping" : "Shipping", }
    if config not in d:
        log_warning('Unsupported UE4 build config “%s”' % (config))
        return None
    return d[config]

def get_ue4_build_platform(platform):
    d = { "ps4"     : "PS4",
          "xboxone" : "XboxOne",
          "win64"   : "Win64",
          "win32"   : "Win32",
          "linux"   : "Linux",
          "mac"     : "Mac", }
    if platform not in d:
        log_warning('Unsupported UE4 build platform “%s”' % (platform))
        return None
    return d[platform]

def get_ue4_cook_platform(platform):
    d = { "ps4"     : "FIXME",
          "xboxone" : "FIXME",
          "win64"   : "FIXME",
          "win32"   : "FIXME",
          "linux"   : "FIXME", }
    if platform not in d:
        log_warning('Unsupported UE4 cook platform “%s”' % (platform))
        return None
    return d[platform]


#---------------------------------------------------------------------------
def _ue4_build_project(sln_file, project, build_platform,
                       configuration, vs_version, target = 'Rebuild'):

    if is_msys():
        return vsbuild(sln_file, build_platform, configuration,
                       project, vs_version, target)

    elif platform.system() == 'Darwin':
        return call_process('.', ['/bin/sh', 'Engine/Build/BatchFiles/Mac/Build.sh',
                                   project, 'Mac', configuration]) == 0

    else:
        project_name = project
        if configuration not in ['Development', 'Development Editor']:
            project_name += '-Linux-' + configuration
        elif configuration == 'Development Editor':
            project_name += 'Editor'
        return call_process('.', ['make', project_name]) == 0


#---------------------------------------------------------------------------
def ue4_commandlet(env, commandlet, *args):
    cmdline = [ "Engine/Binaries/Win64/UE4Editor.exe",
                env.game,
                "-run=%s" % commandlet]

    cmdline += list(args)
    cmdline += ['-nopause', '-buildmachine', '-forcelogflush', '-unattended', '-noscriptcheck']

    return call_process(".", cmdline) == 0

