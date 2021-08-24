
# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
from octoprint.util import RepeatedTimer
from octoprint.server import user_permission

import os.path
from os import path

import glob
import sys
import flask
import subprocess
import psutil
import re
import threading
import queue
import time

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
        self.tempCmds = {}

        self.psutilCPUHasRun = False

        # List of psu
        self.psutilList = {
            'cpup'      : ['CPU usage %'],
            'cpuf'      : ['CPU frequency in MHz'],
            'loadavg1'  : ['Average system load last 1 minute'],
            'loadavg5'  : ['Average system load last 5 minutes'],
            'loadavg15' : ['Average system load last 15 minutes'],
            'memtotal'  : ['Total physical memory (exclusive swap) in MB'],
            'memavail'  : ['Total available memory in MB'],
            'memused'   : ['Memory used in MB'],
            'memfree'   : ['Memory not being used at all in MB'],
            'memp'      : ['Memory free %'],
            'swaptotal' : ['Total swap memory in MB'],
            'swapused'  : ['Used swap memory in MB'],
            'swapfree'  : ['Free swap memory in MB'],
            'swapperc'  : ['Free swap %']
        }

        # Gcode handling
        self.gcodeQue = queue.Queue()
        self.gcodeThread = None
        # Store all the actions to be handle for out/in gcode
        self.gcodeCmds = {'gcIn' : {}, 'gcOut':{}}
        self.gcodeCheckIn = False
        self.gcodeCheckOut = False

        # base config
        # customMon is all the custom monitoring items index by "customN" - a bit of a hackish way
        # Sort order is the order how the items are displayed in the UI
        self.noTools = 10
        self.defaultConfig = {
            'firstRun' : True,
            'fahrenheit' : False,
            'leftAlignIcons' : False,
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
            'showPopover' : True,
            'hideOnNoTarget': False,
            'showTargetTemp' : True,    # not used in custom
            'showTargetArrow' : True,   # not used in custom
            'label': '',
            'width': 0,
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

        # type can be cmd, gcIn, gcOut, psutil
        self.defaultsCustom = {'cmd':'','name':'','interval': 25, 'type':'cmd', 'isTemp' : True , 'waitForPrint' : False, 'unit' : '', 'postCalc' : None}

    # ----------------------------------------------------------------------------------------------------------------
    # Lets get started
    # ----------------------------------------------------------------------------------------------------------------
    def on_after_startup(self):
        self.initCustomMon()
        self.gcodeThread = threading.Thread(target=self.gcodeRecvQworker)
        self.gcodeThread.daemon = True
        self.gcodeThread.start()
        self._logger.info("TopTemp is initialized")

    def on_shutdown(self):
        pass
        # self.gcodeQue.join()

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
        self.buildPsuUtil()

        customMon = self._settings.get(["customMon"],merged=True,asdict=True)

        # Should we update the custom mappings
        if customMon:
            self.debugOut("Fixing custom monitors")
            newCust = {}
            # parse all and merge
            for ckey in customMon:
                temp = self._merge_dictionaries(self.tempTemplate.copy(),self.defaultsCustom.copy())
                newCust[ckey] = self._merge_dictionaries(temp,customMon[ckey])
                #self.debugOut(newCust[ckey].copy())
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

        # Append default cpu monitor due to first run
        # self.tempTemplate = {
        #     'updated' : None,
        #     'show' : True,
        #     'showPopover' : True,
        #     'hideOnNoTarget': False,
        #     'showTargetTemp' : True,
        #     'showTargetArrow' : True,
        #     'label': '',
        #     'width': 0,
        #     'icon' : 'fas fa-thermometer-full',
        #     'colorIcons': True,
        #     'colorChangeLevel': 60,
        #     'noDigits': 0,
        #     'showUnit': True,
        #     'decSep': ',',
        #     'graphSettings': {
        #         'height': 50,
        #         'show': True,
        #         'opa': 0.2,
        #         'width': 1,
        #         'color' : '#000000',
        #     }
        # }

        # # type can be cmd, gcIn, gcOut
        # self.defaultsCustom = {'cmd':'','name':'','interval': 25, 'type':'cmd', 'isTemp' : True}

        for key in self.tempCmds:
            if self.tempCmds[key][1] != False:
                self.debugOut("Adding default CPU temp")
                # Make template
                temp = self._merge_dictionaries(self.tempTemplate.copy(),self.defaultsCustom.copy())
                # Assign
                newCust = {'cu0':temp}
                newCust['cu0']['cmd'] = self.tempCmds[key][0]
                newCust['cu0']['name'] = 'CPU temperature'
                newCust['cu0']['type'] = 'cmd'
                newCust['cu0']['isTemp'] = True
                newCust['cu0']['showTargetTemp'] = False
                newCust['cu0']['label'] = "CPU:"
                newCust['cu0']['icon'] = "fas fa-thermometer-full"
                newCust['cu0']['colorIcons'] = True
                newCust['cu0']['colorChangeLevel'] = 80
                newCust['cu0']['showUnit'] = True
                break

        # add default fan speed from gcode monitoring
        self.debugOut("Adding default fan speed")
        # Make template
        temp = self._merge_dictionaries(self.tempTemplate.copy(),self.defaultsCustom.copy())
        # Assign
        newCust['cu1'] = temp
        newCust['cu1']['cmd'] = "^M106.*?S([^ ]+)"
        newCust['cu1']['name'] = 'Cooling fan speed'
        newCust['cu1']['type'] = 'gcOut'
        newCust['cu1']['isTemp'] = False
        newCust['cu1']['showTargetTemp'] = False
        newCust['cu1']['label'] = "F:"
        newCust['cu1']['icon'] = "fas fa-fan"
        newCust['cu1']['colorIcons'] = False
        newCust['cu1']['showUnit'] = False
        newCust['cu1']['waitForPrint'] = True
        newCust['cu1']['postCalc'] = 'X/255*100'
        newCust['cu1']['unit'] = '%'
        self.debugOut(newCust)

        self._settings.set(["customMon"],newCust,True)

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
                    # New type
                    if 'type' in newData and custOld[ckey]['type'] != newData['type']:
                        # clean history if changing the typpe
                        self.customHistory[ckey] = []
                        newMonCmd = True
                    # New command
                    if 'cmd' in newData and custOld[ckey]['cmd'] != newData['cmd']:
                        # clean history if changing the command
                        self.customHistory[ckey] = []
                        newMonCmd = True
                    # New interval
                    if 'interval' in newData and custOld[ckey]['interval'] != newData['interval']:
                        newMonCmd = True

                    # Assign new
                    newCust[ckey] = self._merge_dictionaries(custOld[ckey].copy(),newData.copy())

            # Gcode
            if newMonCmd == True and (newCust[ckey]['type'] == "gcIn" or newCust[ckey]['type'] == "gcOut"):
                # kill any running timers
                if ckey in self.timers:
                    self.debugOut("Stopping timer: " + ckey + " type is no longer cmd")
                    self.timers[ckey].cancel()

                self.debugOut("New gcode "+newCust[ckey]['type']+" mon needed: "+ckey + ":"+newCust[ckey]['cmd'])
                self.createGCmon(ckey,newCust[ckey]['type'],newCust[ckey]['cmd'])

            # new timer needed
            elif newMonCmd == True:
                if ckey in self.gcodeCmds['gcOut']:
                    self.debugOut("Remove gcOut for : " + ckey + " type is no longer gcode - now " + newCust[ckey]['type'])
                    del self.gcodeCmds['gcOut'][ckey]
                if ckey in self.gcodeCmds['gcIn']:
                    self.debugOut("Remove gcIn for : " + ckey + " type is no longer gcode - now " + newCust[ckey]['type'])
                    del self.gcodeCmds['gcIn'][ckey]
                self.debugOut("New mon needed: "+ckey + ":"+newCust[ckey]['cmd'])
                self.createTimer(ckey,int(newCust[ckey]['interval']),newCust[ckey]['cmd'],newCust[ckey]['type'])


        # debug
        for key in newCust:
            newCust[key].pop('delThis', None)
            newCust[key].pop('new', None)
            newCust[key].pop('showTargetTemp', None)
            newCust[key].pop('showTargetArrow', None)
            # self._logger.info("%s : %s",key,newCust[key]['name'])
            # self._logger.info(newCust[key])

        del data['customMon']
        data['customMon'] = newCust.copy()
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        # Needed to write all the data - when deleting
        self._settings.set(["customMon"],newCust.copy(),True)

        # update gcode monitors
        self.setGcodeMonNeed()

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

    def buildPsuUtil(self):
        # Todo add network :)
        self.debugOut("Building psutil methods!")
        # https://psutil.readthedocs.io/en/latest/#psutil.disk_partitions
        partitions = [partition._asdict() for partition in psutil.disk_partitions()]
        count = 0
        for partition in partitions:
            self.psutilList['diskfree_'+str(count)] = ["Disk free \""+partition['mountpoint']+"\"",partition['mountpoint']]
            self.psutilList['disktotal_'+str(count)] = ["Disk total \""+partition['mountpoint']+"\"",partition['mountpoint']]
            self.psutilList['diskused_'+str(count)] = ["Disk used \""+partition['mountpoint']+"\"",partition['mountpoint']]
            self.psutilList['diskperc_'+str(count)] = ["Disk used %  \""+partition['mountpoint']+"\"",partition['mountpoint']]
            count += 1

        # temperatures
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            if temps:
                count = 0
                for name, entries in temps.items():
                    entryno = 0
                    for entry in entries:
                        # shwtemp(label='', current=54.768, high=None, critical=None)
                        if entry.label:
                            label = entry.label
                        else:
                            label = name + "-" +str(count)
                        self.psutilList['temp_'+str(count)] = ["Temperature " + label,[name,entryno]]
                        count += 1
                        entryno += 1
        # fans
        if hasattr(psutil, "sensors_fans"):
            fans = psutil.sensors_fans()
            if fans:
                count = 0
                for name, entries in fans.items():
                    entryno = 0
                    for entry in entries:
                        if entry.label:
                            label = entry.label
                        else:
                            label = name + "-" +str(count)
                        self.psutilList['fanspeed_'+str(count)] = ["Fanspeed " + label + " RPM",[name,entryno]]
                        count += 1
                        entryno += 1

        # battery
        if hasattr(psutil, "sensors_battery"):
            battery = psutil.sensors_battery()
            if battery:
                self.psutilList['batper'] = ["Battery power left %"]
                self.psutilList['batsec'] = ["Battery power left seconds"]

        self.debugOut(self.psutilList)

    # ----------------------------------------------------------------------------------------------------------------
    # check the available methods for finding CPU temp on the hw platform
    # ----------------------------------------------------------------------------------------------------------------
    def checkCpuTempMethods(self):
        self.tempCmds = {}

        self.debugOut("Building cpu methods!")

        # build list for linux
        if sys.platform.startswith("linux"):
            self.tempCmds = {
                '/opt/vc/bin/vcgencmd' :
                    [
                        '/opt/vc/bin/vcgencmd measure_temp|cut -d "=" -f2|cut -d"\'" -f1',
                        "CPU vcgencmd 1",
                        None
                    ],
                '/usr/bin/vcgencmd' :
                    [
                        '/usr/bin/vcgencmd measure_temp|cut -d "=" -f2|cut -d"\'" -f1',
                        "CPU vcgencmd 2",
                        None
                    ],
                '/usr/bin/acpi' :
                    [
                        '/usr/bin/acpi -t |cut -d "," -f2| cut -d" " -f2',
                        "CPU ACPI",
                        None
                    ],
            }

            # try and find thermal class by looking cpu-thermal temp
            code, out, err = self.runcommand("for i in /sys/class/thermal/thermal_zone*; do if grep -qi cpu-thermal $i/type && test -f $i/temp ; then echo $i/temp;exit 0; fi; done; exit 1")
            if not code and not err:
                self.tempCmds[out] = ["awk '{print $0/1000}' "+out,'CPU thermal zone',None]

            # look for DS18B20 devices
            DS18B20s = glob.glob('/sys/bus/w1/devices/28-*')
            if DS18B20s:
                for DS18B20 in DS18B20s:
                    #check slave is present /w1_slave
                    dsslave = os.path.join(DS18B20,'w1_slave')
                    if os.path.isfile(dsslave):
                        dsbase = os.path.basename(DS18B20)
                        # check for crc
                        code, out, err = self.runcommand("grep -iqP \"crc=(.*)YES\" "+dsslave)
                        if not code and not err:
                            self.tempCmds[DS18B20] = ["awk -F'[ =]' '$10==\"t\"{printf(\"%.2f\\n\",$11/1000)}' "+dsslave,'DS18B20 sensor ('+dsbase+')' ,None]

        # check all methods found
        for key in self.tempCmds:
            if (path.exists(key)):
                # self._logger.debug(self.tempCmds[key])
                code, out, err = self.runcommand(self.tempCmds[key][0])
                out = out.rstrip("\n")
                if code or err:
                    #self._logger.debug("ERROR 1:-------------------------------------------------------------%s %s",err,code)
                    pass
                else:
                    if out.replace('.','',1).isdigit():
                        #self._logger.debug("OK-------------------------------------------------------------%s",out)
                        self.tempCmds[key][2] = float(out)
                    else:
                        # self._logger.debug("ERROR 2:-------------------------------------------------------------%s",out)
                        pass
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

        # setup all the monitors
        for mon in customMon:
            if customMon[mon]['cmd']:
                # gcode regexp cmds
                if customMon[mon]['type'] == "gcIn" or customMon[mon]['type'] == "gcOut":
                    self.createGCmon(mon,customMon[mon]['type'],customMon[mon]['cmd'])

                # psutil and cmd
                else:
                    self.createTimer(mon,int(customMon[mon]['interval']),str(customMon[mon]['cmd']),customMon[mon]['type'])

        self.setGcodeMonNeed()

    # Timer for custom bash command
    def createTimer(self,indx,interval,cmd,cmdtype):
        if indx in self.timers:
            self.debugOut("Stopping timer: " + indx)
            self.timers[indx].cancel()

        self.debugOut("Setting up custom timer for \"" + cmd + "("+indx+" / "+cmdtype+") running each " + str(interval) + " seconds")
        if cmdtype == "cmd":
            self.timers[indx] = RepeatedTimer(interval,self.runCustomMon, run_first=True,args=[indx,cmd])
        else:
            self.timers[indx] = RepeatedTimer(interval,self.runPSUtil, run_first=True,args=[indx,cmd])
        self.timers[indx].start()

    def createGCmon(self,indx,ctype,pattern):
        self.debugOut("Setting up custom gcode monitor for \""+indx+"\". Type: " + ctype + " pattern: " +pattern)
        if ctype == "gcIn":
            if indx in self.gcodeCmds['gcOut']:
                self.debugOut("Deleting " + indx + " from gcOut")
                del self.gcodeCmds['gcOut'][indx]
            self.gcodeCheckIn = True
        else:
            if indx in self.gcodeCmds['gcIn']:
                self.debugOut("Deleting " + indx + " from gcIn")
                del self.gcodeCmds['gcIn'][indx]
            self.gcodeCheckIn = True

        # Assign it
        self.gcodeCmds[ctype][indx] = re.compile(pattern)

    def setGcodeMonNeed(self):
        if self.gcodeCmds['gcIn']:
            self.gcodeCheckIn = True
        else:
            self.gcodeCheckIn = False

        if self.gcodeCmds['gcOut']:
            self.gcodeCheckOut = True
        else:
            self.gcodeCheckOut = False

    # Trigger by the timer
    def runCustomMon(self,indx,cmd):
        code, out, err = self.runcommand(cmd)
        self.debugOut(cmd + " returned: " +out + " for index :"+indx)
        if code or err:
            self._plugin_manager.send_plugin_message(self._identifier, dict(success=False,error=err,returnCode=code,result=None,key=indx,type="custom"))
        else:
            self.handleCustomData(indx,out,time.time())

    # Trigger by the timer
    def runPSUtil(self,indx,cmd,returnData = False):
        # 'cpup'      : ['CPU usage percentage'],
        # 'cpuf'      : ['CPU frequency in GHz'],
        # 'loadavg1'  : ['Average system load last 1 minute'],
        # 'loadavg5'  : ['Average system load last 5 minutes'],
        # 'loadavg15' : ['Average system load last 15 minutes'],
        # 'memtotal'  : ['Total physical memory (exclusive swap)'],
        # 'memavail'  : ['Total available memory'],
        # 'memused'   : ['Memory used'],
        # 'memfree'   : ['Memory not being used at all'],
        # 'memp'      : ['Memory free percentage'],
        # 'swaptotal' : ['Total swap memory'],
        # 'swapused'  : ['Used swap memory'],
        # 'swapfree'  : ['Free swap memory'],
        # 'swapperc'  : ['Free swap percentage']
        # self.psutilList['diskfree_'+str(count)] = ["Disk free "+partition['mountpoint'],partition['mountpoint']]
        # self.psutilList['disktotal_'+str(count)] = ["Disk total "+partition['mountpoint'],partition['mountpoint']]
        # self.psutilList['diskused_'+str(count)] = ["Disk used "+partition['mountpoint'],partition['mountpoint']]
        # self.psutilList['diskperc_'+str(count)] = ["Disk used percent "+partition['mountpoint'],partition['mountpoint']]
        # self.psutilList['temp_'+str(count)] = ["Temperature " + label,[name,entryno]]
        # self.psutilList['fanspeed_'+str(count)] = ["Fanspeed " + label,[name,entryno]]
        # self.psutilList['batper'] = ["Battery power left percentage"]
        # self.psutilList['batsec'] = ["Battery power left seconds"]

        returnVal = None

        # Lazy switch

        # Cpu percentage
        if cmd == "cpup":
            if self.psutilCPUHasRun == False:
                psutil.cpu_percent(interval=None)
                self.psutilCPUHasRun = True
            returnVal = psutil.cpu_percent(interval=None)

        # Cpu freque
        if cmd == "cpuf":
            returnVal = psutil.cpu_freq(percpu=False).current

        # Load avg
        if cmd == "loadavg1":
            returnVal = psutil.getloadavg()[0]
        if cmd == "loadavg5":
            returnVal = psutil.getloadavg()[1]
        if cmd == "loadavg15":
            returnVal = psutil.getloadavg()[2]

        # Mem
        if cmd == "memtotal":
            returnVal = psutil.virtual_memory().total/1048576
        if cmd == "memavail":
            returnVal = psutil.virtual_memory().available/1048576
        if cmd == "memused":
            returnVal = psutil.virtual_memory().used/1048576
        if cmd == "memfree":
            returnVal = psutil.virtual_memory().free/1048576
        if cmd == "memp":
            returnVal = psutil.virtual_memory().percent

        # swap
        if cmd == "swaptotal":
            returnVal = psutil.swap_memory().total/1048576
        if cmd == "swapused":
            returnVal = psutil.swap_memory().used/1048576
        if cmd == "swapfree":
            returnVal = psutil.swap_memory().free/1048576
        if cmd == "swapperc":
            returnVal = psutil.swap_memory().percent

        # battery info
        if cmd == "batsec":
            if hasattr(psutil, "sensors_battery"):
                returnVal = psutil.sensors_battery().secsleft
        if cmd == "batper":
            if hasattr(psutil, "sensors_battery"):
                returnVal = psutil.sensors_battery().percent

        # Return if we found something now
        if returnVal:
            self.debugOut("psutil " + cmd + " returned: " + str(returnVal) + " for index :"+indx)
            if returnData:
                return returnVal;
            self.handleCustomData(indx,returnVal,time.time())

        # Disk
        if cmd[0:4] == "disk":
            if cmd in self.psutilList:
                diskCmd = cmd.split("_")[0]
                partion = self.psutilList[cmd][1]
                diskUsage = psutil.disk_usage(partion)
                if diskUsage:
                    if diskCmd == "diskfree":
                        returnVal = diskUsage.free/1048576
                    if diskCmd == "disktotal":
                        returnVal = diskUsage.total/1048576
                    if diskCmd == "diskused":
                        returnVal = diskUsage.used/1048576
                    if diskCmd == "diskperc":
                        returnVal = diskUsage.percent

        # Temp
        if cmd[0:4] == "temp":
            if hasattr(psutil, "sensors_temperatures"):
                if cmd in self.psutilList:
                    tempName = self.psutilList[cmd][1][0]
                    tempEntry = self.psutilList[cmd][1][1]
                    temps = psutil.sensors_temperatures()
                    if temps and tempName in temps:
                        returnVal = temps[tempName][tempEntry].current

        # Fans
        if cmd[0:8] == "fanspeed":
            if hasattr(psutil, "sensors_fans"):
                if cmd in self.psutilList:
                    fanName = self.psutilList[cmd][1][0]
                    fanEntry = self.psutilList[cmd][1][1]
                    fans = psutil.sensors_fans()
                    if fans and fanName in fans:
                        fans[fanName][fanEntry].current

        if returnVal:
            self.debugOut("psutil " + cmd + " returned: " + str(returnVal) + " for index :"+indx)
            if returnData:
                return returnVal;
            self.handleCustomData(indx,returnVal,time.time())

        if returnData:
                return None;

    def handleCustomData(self,indx,out,time):
        self.debugOut("Got custom data: " + str(out))
        # Check
        if isinstance(out,(float, int)) or str(out).replace('.','',1).isdigit():
            resultData = [time,float(out)]
            if indx not in self.customHistory:
                self.customHistory[indx] = []
            self.customHistory[indx].append(resultData)
            # slice of 300
            self.customHistory[indx] = self.customHistory[indx][-300:]

            # send to the frontend
            self.debugOut("Sending data to UI, " + indx + " : " + str(out))
            self._plugin_manager.send_plugin_message(self._identifier, dict(success=True,error=None,returnCode=0,result=resultData,key=indx,type="custom"))

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
                self.buildPsuUtil()

            self.debugOut("Sending options")
            return flask.jsonify({'cmds' : self.tempCmds,'psutil' : self.psutilList})

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
            cmdType = data["type"]
            if cmdType == "psutil":
                result = self.runPSUtil("TEST",cmdInput,True)
                if result:
                    repsonse = dict(success=True,error=None,returnCode=200,result=result)
                else:
                    repsonse = dict(success=False,error="No data returned",returnCode=404,result=None)
                return flask.jsonify(repsonse)

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
                    if isinstance(out,(float, int)) or str(out).replace('.','',1).isdigit():
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

    def gcodeRecvQworker(self):
        while True:
            item = self.gcodeQue.get()
            gcodeCmdLib = self.gcodeCmds[item['type']]
            for cKey in gcodeCmdLib:
                pattern = gcodeCmdLib[cKey]
                dataStr = item['data'].strip()
                # self.debugOut("gcode "+item['type']+" macthing : " + cKey + " for string \""+dataStr+"\"" )
                match = re.search(pattern, dataStr)
                if match:
                    # self.debugOut("----------------------------------------->>> gcode "+item['type']+" matched: " + dataStr)
                    self.handleCustomData(cKey,match.group(1),item['time'])

            # All done - next task please :)
            self.gcodeQue.task_done()


    def gCodeHandlerRecv(self, comm, line, *args, **kwargs):
        if self.gcodeCheckIn == False:
            # self.debugOut("No gcode IN check needed")
            return line

        # self.debugOut("gcode IN check needed")
        dataSet = {'time':time.time(),'type' : 'gcIn', 'data':line}
        self.gcodeQue.put(dataSet)

        return line

    def gCodeHandlerSent(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
        if self.gcodeCheckOut == False:
            # self.debugOut("No gcode OUT check needed")
            return

        # self.debugOut("gcode OUT check needed")

        # Turn off fan special handling
        if gcode and gcode == "M107":
            dataSet = {'time':time.time(), 'type' : 'gcOut', 'data': "M106 S0"}
        else:
            dataSet = {'time':time.time(),'type' : 'gcOut', 'data': cmd}

        self.gcodeQue.put(dataSet)

__plugin_name__ = "Top Temp"
__plugin_pythoncompat__ = ">=2.7,<4"

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = TopTempPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        "octoprint.comm.protocol.gcode.received": __plugin_implementation__.gCodeHandlerRecv,
        "octoprint.comm.protocol.gcode.sent": __plugin_implementation__.gCodeHandlerSent,
    }