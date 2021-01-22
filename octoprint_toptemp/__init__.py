
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

        # Make sure we dont init twice
        self.configLoaded = False

        # base config
        # customMon is all the custom monitoring items index by "customN" - a bit of a hackish way
        # Sort order is the order how the items are displayed in the UI
        self.noTools = 10
        self.defaultConfig = {
            'fahrenheit' : False,
            'hideInactiveTemps' : True,
            'noTools' : self.noTools,
            'sortOrder': ['bed','tool0','tool1','chamber','cu0'],
            'outerMargin': 4,
            'innerMargin': 8,
            'customMon': {}
        }

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
                'show': True,
                'opa': 0.2,
                'width': 1,
                'color' : '#000000'
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
                    if 'cmd' in newData and custOld[ckey]['cmd'] != newData['cmd']:
                        newMonCmd = True
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


    # ----------------------------------------------------------------------------------------------------------------
    # default settings
    # ----------------------------------------------------------------------------------------------------------------
    def get_settings_defaults(self):
        # Lets try and build a default monitor to add to the default settings
        if self.configLoaded == False:
            self.configLoaded = True
            self.checkCpuTempMethods()
            for key in self.cpuTemps:
                if self.cpuTemps[key][1] != False:
                    # append a default 0 monitor
                    # self.defaultConfig['customMon']['cu0'] = {'cmd':self.cpuTemps[key][0],'name':'CPU temperature','interval': 10}
                    # self.defaultConfig['customMon']['cu0'].update(self.tempTemplate.copy())
                    # self.defaultConfig['customMon']['cu0']['label'] = 'CPU: '
                    # self.defaultConfig['customMon']['cu0']['icon'] = 'fas fa-microchip'

                    # debug - add a random version
                    # self.defaultConfig['customMon']['custom1'] = {'cmd':'/usr/bin/shuf -i 1-25 -n 1','name':'Random','interval': 5}
                    # self.defaultConfig['custom1'] = self.tempTemplate.copy()
                    # self.defaultConfig['custom1']['label'] = 'R: '
                    # self.defaultConfig['custom1']['icon'] = 'fas fa-random'
                    break

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
        custoMon = self._settings.get(['customMon'],merged=True,asdict=True)

        # stop old timers if someone is calling us
        for timer in self.timers:
            self.timers[timer].cancel()

        # cleanup all
        self.timers = {}
        self.customHistory = {}

        # setup all the other monitors
        for mon in custoMon:
            if custoMon[mon]['cmd']:
                monVal = str(mon)
                monCmd = str(custoMon[monVal]['cmd'])
                intVal = int(custoMon[monVal]['interval'])
                self.startTimer(monVal,intVal,monCmd)


    def startTimer(self,indx,interval,cmd):
        if indx in self.timers:
            self.debugOut("Stopping timer: " + indx)
            self.timers[indx].cancel()

        self.debugOut("Setting up custom monitor for \"" + cmd + "("+indx+") running each " + str(interval) + " seconds")
        self.timers[indx] = RepeatedTimer(interval,self.runCustoMon, run_first=True,args=[indx,cmd])
        self.timers[indx].start()

    # Trigger by the timerf
    def runCustoMon(self,indx,cmd):
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
                self.customHistory[indx][-200:]

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
            return flask.jsonify(self.tempTemplate)

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