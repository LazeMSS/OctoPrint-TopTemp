
# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
from octoprint.util import RepeatedTimer
from octoprint.server import user_permission

import os.path
from os import path

import sys
import flask
import subprocess
import psutil

class TopTempPlugin(octoprint.plugin.StartupPlugin,
                       octoprint.plugin.SettingsPlugin,
                       octoprint.plugin.AssetPlugin,
                       octoprint.plugin.TemplatePlugin,
                       octoprint.plugin.SimpleApiPlugin):

    def __init__(self):
        # hold all running timers
        self.timers = {}
        # holds the history data
        self.customHistory = {}
        # List of cpu temp methods found
        self.cpuTemps = {}

        # base config
        # customMon is all the custom monitoring items index by "customN" - a bit of a hackish way
        # Sort order is the order how the items are displayed in the UI
        self.noTools = 10
        self.defaultConfig = {
            'firstRun' : True,
            'fahrenheit' : False,
            'hideInactiveTemps' : True,
            'noTools' : self.noTools,
            'sortOrder': ['bed','tool0','tool1','chamber','cu0'],
            'outerMargin': 4,
            'innerMargin': 8,
            'customMon': {}
        }


        self.defaultsCustom = {'cmd':'','name':'','interval': 25}

        # Build extra config templates
        self.tempItems = {'bed' : 'fas fa-window-minimize','chamber' : 'far fa-square'}
        self.tempTemplate = {
            'updated' : None,
            'show' : True,
            'hideOnNoTarget': False,
            'showTargetTemp' : True,
            'showTargetArrow' : True,
            'label': '',
            'icon' : 'fas fa-thermometer-full',
            'colorIcons': True,
            'colorChangeLevel': 60,
            'noDigits': 0,
            'showUnit': True,
            'decSep': ',',
            'graphSettings': {
                'height': 50,
                'show': True,
                'opa': 0.2,
                'width': 1,
                'color' : '#000000',
            }
        }

    # ----------------------------------------------------------------------------------------------------------------
    # Lets get started
    # ----------------------------------------------------------------------------------------------------------------
    def on_after_startup(self):
        self.initCustomMon()
        self._logger.info("TopTemp is initialized")

    # ----------------------------------------------------------------------------------------------------------------
    # get files to be include in the UI
    # ----------------------------------------------------------------------------------------------------------------
    def get_assets(self):
        return dict(
            js=["js/TopTemp.js"],
            css=["css/TopTemp.css"],
        )

    # ----------------------------------------------------------------------------------------------------------------
    # templates include
    # ----------------------------------------------------------------------------------------------------------------
    def get_template_configs(self):
        return [
            dict(type="settings", custom_bindings=False)
        ]


    # Fix dynamic default settings for custom monitoring and fix first run
    def on_settings_initialized(self):
        # Get cpu options
        self.checkCpuTempMethods()
        customMon = self._settings.get(["customMon"],merged=True,asdict=True)

        # Should we update the custom mappings
        if customMon:
            self.debugOut("Fixing custom monitors")
            newCust = {}
            # parse all and merge
            for ckey in customMon:
                temp = self._merge_dictionaries(self.tempTemplate.copy(),self.defaultsCustom.copy())
                newCust[ckey] = self._merge_dictionaries(temp,customMon[ckey])
                self.debugOut(newCust[ckey].copy())
            # Save the new data
            self._settings.set(["customMon"],newCust.copy(),True)

        # First run chek
        firstRun = self._settings.get(["firstRun"],merged=True,asdict=True)

        # Not first run - then do nothing
        if firstRun == False:
            return

        # Remove first run
        self.debugOut("First run")
        self._settings.set(["firstRun"],False,True)

        # Append default cpu monitor
        for key in self.cpuTemps:
            if self.cpuTemps[key][1] != False:
                self.debugOut("Appeding default CPU temp")
                # Make template
                temp = self._merge_dictionaries(self.tempTemplate.copy(),self.defaultsCustom.copy())
                # Assign
                newCust = {'cu0':temp}
                newCust['cu0']['cmd'] = self.cpuTemps[key][0]
                newCust['cu0']['name'] = 'CPU temperature'
                self.debugOut(newCust)
                self._settings.set(["customMon"],newCust,True)
                break

    # Save handler - has a bit of hack to cleanup remove custom monitors
    def on_settings_save(self,data):
        # Do we have custom data in the post?
        if 'customMon' not in data:
            octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
            return

        # Get old data to use
        custOld = self._settings.get(["customMon"],merged=True,asdict=True)
        newCust = {}

        # Parse new data
        for ckey in data['customMon']:
            newMonCmd = False
            # self._logger.info("---------------------------------%s---------------------------------------------",ckey)
            newData = data['customMon'][ckey].copy()

            if 'delThis' in newData and newData['delThis'] == True:
                # self._logger.info("Deleting: %s",ckey)
                pass
            else:
                if 'new' in newData and newData['new'] == True:
                    # self._logger.info("Creating new: %s",ckey)
                    newCust[ckey] = newData
                    newMonCmd = True
                else:
                    # self._logger.info("Merging old data from: %s ",ckey)
                    newCust[ckey] = custOld[ckey].copy()
                    # New command
                    if 'cmd' in newData and custOld[ckey]['cmd'] != newData['cmd']:
                        newMonCmd = True
                    # New interval
                    if 'interval' in newData and custOld[ckey]['interval'] != newData['interval']:
                        newMonCmd = True

                    # Assign new
                    newCust[ckey].update(newData)

            # new timer need
            if newMonCmd == True:
                self.debugOut("New mon needed: "+ckey + ":"+newCust[ckey]['cmd'])
                self.startTimer(ckey,int(newCust[ckey]['interval']),newCust[ckey]['cmd'])


        # debug
        for key in newCust:
            newCust[key].pop('delThis', None)
            newCust[key].pop('new', None)
            # self._logger.info("%s : %s",key,newCust[key]['name'])
            # self._logger.info(newCust[key])

        del data['customMon']
        data['customMon'] = newCust.copy()
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        # Needed to write all the data - when deleting
        self._settings.set(["customMon"],newCust.copy(),True)
        # Save first run or not
        self._settings.set(["firstRun"],False)


    # ----------------------------------------------------------------------------------------------------------------
    # default settings
    # ----------------------------------------------------------------------------------------------------------------
    def get_settings_defaults(self):
        # Lets try and build a default monitor to add to the default settings

        # Build default settings
        for key in self.tempItems:
            self.defaultConfig[key] = self.tempTemplate.copy()
            # Fix label
            self.defaultConfig[key]['label'] = key[0:1].upper() + ": "
            self.defaultConfig[key]['icon'] = self.tempItems[key]

        # build tools
        i = 0
        while i < self.noTools:
            toolname = 'tool'+str(i)
            self.defaultConfig[toolname] = self.tempTemplate.copy()
            self.defaultConfig[toolname]['appendIconNumber'] = True
            # Fix label
            self.defaultConfig[toolname]['label'] = "T" + str(i) + ": "
            self.defaultConfig[toolname]['icon'] = "fas fa-fire"
            if i > 0:
                self.defaultConfig[toolname]['show'] = False

            i +=1
        return self.defaultConfig

    # ----------------------------------------------------------------------------------------------------------------
    # check the available methods for finding CPU temp on the hw platform
    # ----------------------------------------------------------------------------------------------------------------
    def checkCpuTempMethods(self):
        self.cpuTemps = {}

        # build list for linux
        if sys.platform.startswith("linux"):
            self.cpuTemps = {
                '/opt/vc/bin/vcgencmd' :
                    [
                        '/opt/vc/bin/vcgencmd measure_temp|cut -d "=" -f2|cut -d"\'" -f1',
                        None,
                        "CPU vcgencmd 1"
                    ],
                '/usr/bin/vcgencmd' :
                    [
                        '/usr/bin/vcgencmd measure_temp|cut -d "=" -f2|cut -d"\'" -f1',
                        None,
                        "CPU vcgencmd 2"
                    ],
                '/usr/bin/acpi' :
                    [
                        '/usr/bin/acpi -t |cut -d "," -f2| cut -d" " -f2',
                        None,
                        "CPU ACPI"
                    ],
            }

            # try and find thermal class by looking cpu-thermal temp
            code, out, err = self.runcommand("for i in /sys/class/thermal/thermal_zone*; do if grep -qi cpu-thermal $i/type && test -f $i/temp ; then echo $i/temp;exit 0; fi; done; exit 1")
            if not code and not err:
                self.cpuTemps[out] = ["cat "+out+" | sed 's/\\(.\\)..$/.\\1/'",None,'CPU thermal zone']

        # check all methods found
        for key in self.cpuTemps:
            if (path.exists(key)):
                self._logger.debug(self.cpuTemps[key])
                code, out, err = self.runcommand(self.cpuTemps[key][0])
                out = out.rstrip("\n")
                if code or err:
                    pass
                     #self._logger.debug("ERROR 1:-------------------------------------------------------------%s %s",err,code)
                else:
                    if out.replace('.','',1).isdigit():
                        self.cpuTemps[key][1] = float(out)
                        # self._logger.debug("OK-------------------------------------------------------------%s",out)
                    else:
                        pass
                        #self._logger.debug("ERROR 2:-------------------------------------------------------------%s",out)
            else:
                self._logger.debug("Not found:-------------------------------------------------------------%s",key)



    # ----------------------------------------------------------------------------------------------------------------
    # Start custom monitors
    def initCustomMon(self):
        customMon = self._settings.get(['customMon'],merged=True,asdict=True)

        # stop old timers if someone is calling us
        for timer in self.timers:
            self.timers[timer].cancel()

        # cleanup all
        self.timers = {}
        self.customHistory = {}

        # setup all the other monitors
        for mon in customMon:
            if customMon[mon]['cmd']:
                monVal = str(mon)
                monCmd = str(customMon[monVal]['cmd'])
                intVal = int(customMon[monVal]['interval'])
                self.startTimer(monVal,intVal,monCmd)


    def startTimer(self,indx,interval,cmd):
        if indx in self.timers:
            self.debugOut("Stopping timer: " + indx)
            self.timers[indx].cancel()

        self.debugOut("Setting up custom monitor for \"" + cmd + "("+indx+") running each " + str(interval) + " seconds")
        self.timers[indx] = RepeatedTimer(interval,self.runCustomMon, run_first=True,args=[indx,cmd])
        self.timers[indx].start()

    # Trigger by the timerf
    def runCustomMon(self,indx,cmd):
        code, out, err = self.runcommand(cmd)
        self.debugOut(cmd + " returned: " +out + " for index :"+indx)
        if code or err:
            self._plugin_manager.send_plugin_message(self._identifier, dict(success=False,error=err,returnCode=code,result=None,key=indx))
        else:
            # append to history
            if out.replace('.','',1).isdigit():
                if indx not in self.customHistory:
                    self.customHistory[indx] = []
                self.customHistory[indx].append(float(out))
                # slice of 200
                self.customHistory[indx] = self.customHistory[indx][-200:]

                # send to the frontend
                self._plugin_manager.send_plugin_message(self._identifier, dict(success=True,error=err,returnCode=code,result=out,key=indx))

    # Available commands and parameters
    # testCmd: will run any command
    # monitorservice - can be stop/(re)start og status
    # getCustomHistory
    # getPredefined will retrieve all the predefined monitoring options available
    def get_api_commands(self):
        return dict(
            testCmd=['cmd'],
            monitorService=[],
            getCustomHistory=[],
            getDefaultSettings=[],
            getPredefined=['reload']
        )

    # handle api calls
    def on_api_command(self, command, data):
        if not user_permission.can():
            return flask.make_response("Insufficient rights", 403)

        # Get cpu temp options found on this system - allows a reload
        if command == "getPredefined":
            if data["reload"] == True:
                self.debugOut("Reloading temperature options")
                self.checkCpuTempMethods()

            self.debugOut("Sending temperature options")
            return flask.jsonify(self.cpuTemps)

        # Get history data
        if command == "getCustomHistory":
            self.debugOut("Sending custom history")
            return flask.jsonify(self.customHistory)

        # Get template setting
        if command == "getDefaultSettings":
            template = self.tempTemplate.copy()
            template.update(self.defaultsCustom)
            return flask.jsonify(template)

         # Get history data
        if command == "testCmd":
            cmdInput = data["cmd"]
            cmd = cmdInput.split(" ", 1)
            cmdFound = True

            # try and find the file if not
            if path.exists(cmd[0]) == False:
                cmdFound = False
                # Try and locate on linux - where is foobar on windows
                if sys.platform.startswith("linux"):
                    code, out, err = self.runcommand('which '+cmd[0])
                    # We found it
                    if code == 0:
                        cmdFound = True

            # did we find it?
            if cmdFound:
                code, out, err = self.runcommand(cmdInput)
                out = out.rstrip("\n")
                if code or err:
                    repsonse = dict(success=False,error=err,returnCode=code,result=out)
                else:
                    if out.replace('.','',1).isdigit():
                        repsonse = dict(success=True,error=err,returnCode=code,result=out)
                    else:
                        repsonse = dict(success=False,error="Not an value",returnCode=code,result=out)
            else:
                repsonse = dict(success=False,error="Path/Command \""+cmd[0]+"\" not found",returnCode=1,result=None)

            return flask.jsonify(repsonse)


    def debugOut(self,msg):
        # self._logger.info(msg)
        return

    # https://karthikbhat.net/recursive-dict-merge-python/
    def _merge_dictionaries(self,dict1, dict2):
        """
        Recursive merge dictionaries.

        :param dict1: Base dictionary to merge.
        :param dict2: Dictionary to merge on top of base dictionary.
        :return: Merged dictionary
        """
        for key, val in dict1.items():
            if isinstance(val, dict):
                dict2_node = dict2.setdefault(key, {})
                self._merge_dictionaries(val, dict2_node)
            else:
                if key not in dict2:
                    dict2[key] = val

        return dict2

    # run command wrapper
    def runcommand (self,cmd):
        proc = subprocess.Popen(cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                shell=True,
                                universal_newlines=True)
        std_out, std_err = proc.communicate()
        return proc.returncode, std_out.strip(), std_err


    # Software update info
    def get_update_information(self):
        # Define the configuration for your plugin to use with the Software Update
        # Plugin here. See https://docs.octoprint.org/en/master/bundledplugins/softwareupdate.html
        # for details.
        return dict(
            toptemp=dict(
                displayName=self._plugin_name,
                displayVersion=self._plugin_version,

                # version check: github repository
                type="github_release",
                user="LazeMSS",
                repo="OctoPrint-TopTemp",
                current=self._plugin_version,

                # update method: pip
                pip="https://github.com/LazeMSS/OctoPrint-TopTemp/archive/{target_version}.zip"
            )
        )


__plugin_name__ = "Top Temp"
__plugin_pythoncompat__ = ">=2.7,<4"

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = TopTempPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }