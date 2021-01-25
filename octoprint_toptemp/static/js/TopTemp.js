/* TopTemp START */
/*
Notes:
Monitors:
    - USE psutil python like: https://plugins.octoprint.org/plugins/resource_monitor/
        Cpu percentage etc.
    - Wifi signal
    - Disk space
    - Fan speed

- Scroll/cycle view for multiple tools ?

- Popover with more info

Settings:
    - Icons: https://github.com/LazeMSS/OctoPrint-TopTemp/issues/5
    - small fonts options
    - Set lowpoint for graph
    - max width for graph/display
    - thousand seperator option
    - Custom option to set as not a temperature (no fahrenheit conversion and check for number)
    - Custom option postfix label (rpm etc)

- icon color?
*/

$(function() {
    function TopTempViewModel(parameters) {
        var self = this;

        self.settingsViewModel = parameters[0];
        self.tempModel = parameters[1];
        self.settings = {};

        // Settings window open
        self.settingsOpen = false;
        self.settingsSaved = false;
        self.previewOn = false;

        self.tempNewCust = [];
        self.deleteCust = {};

        // Pause updating of the UI
        self.updatePaused = false;

        self.mainTypes = ['bed','chamber'];

        self.cusPrefix = 'cu';

        self.customHistory = {};

        // Process data and format it
        self.FormatTempHTML = function(name, data, customType){
            if (self.updatePaused){
                return;
            }
            $('#navbar_plugin_toptemp_'+name).removeClass('TopTempLoad');

            // Setting lookup
            var iSettings = self.getSettings(name);

            // Do know this or want it shown
            if (typeof iSettings == "undefined" || iSettings.show() == false || data.actual == null || data.actual == undefined || (data.target == 0 && iSettings.hideOnNoTarget()) || (!customType && self.settings.hideInactiveTemps() && self.tempModel.isOperational() !== true)){
                $('#navbar_plugin_toptemp_'+name).hide();
                return;
            }else{
                $('#navbar_plugin_toptemp_'+name).show();
            }

            // Create if not found
            var targetE = $('#navbar_plugin_toptemp_'+name+'_text');

            // Show a graph
            var graphE = $('#TopTempGraph_'+name+'_graph');
            if (!iSettings.graphSettings.show() || graphE.length == 0){
                graphE.hide();
            }else{
                graphE.show();

                // Update the styles if settings are open
                if (self.settingsOpen && self.previewOn){
                    self.setGraphStyle(name,iSettings.graphSettings);
                }

                // Plot the graph
                var graphData = null;
                if (customType){
                    if (name in self.customHistory && self.customHistory[name].length > 0){
                        graphData =  {'series' : [self.customHistory[name]]};
                    }
                }else{
                    graphData = {'series' : [OctoPrint.coreui.viewmodels.temperatureViewModel.temperatures[name].actual.slice(-50).map(function(val,i){return val[1]})]};
                }
                // DO we have what we need
                if (graphData != null && typeof Chartist == "object"){
                    new Chartist.Line('#TopTempGraph_'+name+'_graph', graphData,
                    {
                        axisX:{
                            showLabel:false,
                            showGrid: false,
                            padding: 0,
                            offset: 0
                        },
                        axisY:{
                            showLabel:false,
                            showGrid: false,
                            low: 0, // Todo - add support setting low point
                            padding: 0,
                            offset: 0
                        },
                        showPoint: false,
                        lineSmooth: false,
                        showGridBackground: false,
                        chartPadding: 0,
                        labelOffset: 0
                    });
                }
            }

            // Start output
            var outputstr = ''
            if ($.trim(iSettings.label()) != ""){
                outputstr += iSettings.label();
            }

            // Append actual data
            outputstr +=  self.formatTempLabel(name,data.actual,iSettings);

            // Append target if not custom type, we have a target and told to show it
            if (!customType && typeof data.target != undefined && data.target > 0){
                var offsetL = data.target - 0.5;
                var offsetU = data.target + 0.5;
                var ontarget = false;

                // show arrows between temps
                if (iSettings.showTargetArrow()){
                    // Inside target margin
                    if (data.actual >= offsetL && data.actual <= offsetU){
                        ontarget = true;
                    }else if (data.actual < offsetL){
                        outputstr += '<i class="fas fa-caret-up TopTempArrow"></i>';
                    }else if (data.actual > offsetU){
                        outputstr += '<i class="fas fa-caret-down TopTempArrow"></i>';
                    }
                }

                // Show checkered if on target
                if (ontarget){
                    outputstr += '<i class="fas fa-flag-checkered leftPad"></i>';
                }else if (iSettings.showTargetTemp()){
                    // No arrow to seperate then we use text
                    if (!iSettings.showTargetArrow()){
                        outputstr += "/";
                    }
                    outputstr += self.formatTempLabel(name,data.target,iSettings);
                }

            }

            // Should we add an icon
            if ($.trim(iSettings.icon()) !== ""){
                iconcolor = '';
                if (iSettings.colorIcons()){
                    iconcolor = ' muted';
                    if (data.actual >= iSettings.colorChangeLevel()){
                        iconcolor = ' text-error';
                    }
                }
                if (iSettings.appendIconNumber != undefined && iSettings.appendIconNumber() === true && typeof data.toolindx !== undefined){
                    outputstr = '<i class="'+iSettings.icon() + iconcolor+' TopTempIcon"><span class="TopTempIconNo">'+data.toolindx+'</span></i>' + outputstr;
                }else{
                    outputstr = '<i class="'+iSettings.icon() + iconcolor+' TopTempIcon"></i>' + outputstr;
                }
            }
            // Now output
            targetE.html(outputstr);
        }

        // Pretty format a temperature label
        self.formatTempLabel = function(name,value,iSettings){
            if (value == null){
                return value;
            }
            var formatSymbol = "C";
            if (self.settings.fahrenheit()){
                value = (value * 1.8) + 32;
                formatSymbol = "F";
            }
            value = Number.parseFloat(value).toFixed(iSettings.noDigits());
            value = value.replace(".",iSettings.decSep());
            if (iSettings.showUnit()){
                value += '&#176;'+formatSymbol;
            }
            return value;
        }

        // Get updated data from the "feeds"
        self.fromCurrentData = function(data){
            if (self.updatePaused){
                return;
            }

            if (!data.temps.length){
                return;
            }

            if (self.tempModel.hasBed() && data.temps[0].bed != undefined){
                self.FormatTempHTML('bed',data.temps[0].bed,false);
            }
            if (self.tempModel.hasChamber() && data.temps[0].chamber != undefined){
                self.FormatTempHTML('chamber',data.temps[0].chamber,false);
            }
            if (self.tempModel.hasTools()){
                $.each(self.tempModel.tools(),function(indx,val){
                    self.FormatTempHTML('tool'+indx,{'actual' : val.actual(),'target' : val.target(),'name' : val.name(), 'toolindx': indx},false);
                });
            }
        }

        // CPU Temps
        self.onDataUpdaterPluginMessage = function(plugin, data) {
            if (plugin != "toptemp"){
                return;
            }

            if (!('success' in data) || data.success == false){
                return;
            }
            if (!(data.key in self.customHistory)){
                self.customHistory[data.key] = [];
            }
            self.customHistory[data.key].push(data.result);
            self.FormatTempHTML(data.key,{'actual' : data.result},true);
        }

        self.onSettingsBeforeSave = function(){
            if (self.settingsOpen){
                self.settingsSaved = true;
                $('div.modal-backdrop').css('transition','');
                $('div.modal-backdrop').css('top','');

                // Cleanup and prepare settings
                // Append not deleted to the start to clean up indexes
                $.each(self.settings.customMon,function(i,v){
                    if (!(i in self.deleteCust)){
                        if ('new' in self.settings.customMon[i] && self.settings.customMon[i]['new']()){
                            // console.log("Creating: " + i);
                        }else{
                            // console.log("Updating: " + i);
                        }
                        self.settings.customMon[i]['updated'](new Date().getTime());
                        self.settings.customMon[i]['delThis'](false);
                    }
                });
                // put deleted at the end
                $.each(self.settings.customMon,function(i,v){
                    // Remove from sort
                    $('#TopTempSortList >div[data-sortid="'+i+'"]').remove();
                    if (i in self.deleteCust){
                        // console.log("Deleting: " + i);
                        self.settings.customMon[i]['delThis'](true);
                        self.settings.customMon[i]['updated'](new Date().getTime());
                    }
                });
                self.settings.sortOrder($('#TopTempSortList >div').map(function(){return $(this).data('sortid')}).get());
            }
        }

        self.onSettingsHidden = function() {
            // Remove all custom observers
            $('#settings_plugin_toptemp').find('input[data-customMon]').off('change.toptemp');
            $('#settings_plugin_toptemp').find('input[data-settings]').off('change.toptemp');
            // Cleanup preview
            $('div.modal-backdrop').css('transition','');
            $('div.modal-backdrop').css('top','');
            $('#TopTempSortList').data('sorter').destroy();
            $('#TopTempSortList').removeData('sorter');
            self.settingsOpen = false;
            self.previewOn = false;

            // Clean the UI always to get it recreated
            $.each(self.tempNewCust,function(i,v){
                // console.log("CLEAN UP UI TEMP: "+v);
                $('#TopTempSortList >div[data-sortid="'+v+'"]').remove();
                $('#settings_toptemp_'+v).remove();
            });

            // Cleanup settings variable if not saved
            if (!self.settingsSaved){
                // Delete temporay items if not saving
                $.each(self.tempNewCust,function(i,v){
                    // console.log("DELETE TEMP CREATED: "+v);
                    delete self.settings[v];
                    delete self.settings.customMon[v];
                });
            }
            self.tempNewCust = [];
            // Clean ui for deletion
            $.each(self.deleteCust,function(i,v){
                // console.log("CLEAN UP DELETE: "+i);
                $('#TopTempSortList >div[data-sortid="'+i+'"]').remove();
                $('#settings_toptemp_'+i).remove();
            });
            self.deleteCust = {};

            // Match up with the settings saved
            $.each(self.settings.customMon,function(i,v){
                if ('delThis' in v && v['delThis']()){
                    // console.log("deleting from setting : " + i)
                    delete self.settings.customMon[i];
                }else{
                    if ('new' in v){
                        self.settings.customMon[i]['new'](false)
                    }
                }
            });

            // Rebuild it all
            self.settingsSaved = false;
            self.buildContainers(false);
        }


        // Build the sorted list
        self.buildIconOrder = function(){
            var allItems = [...self.mainTypes];
            var notools = self.settings.noTools();
            var no = 0;
            while (no < notools){
                allItems.push('tool'+no);
                no++;
            }
            // Append all custom tools
            $.each(self.settings.customMon,function(idx,val){
                allItems.push(idx);
            });
            var finalList = [];
            $.each(self.settings.sortOrder(),function(idx,val){
                // Remove from full list if found
                var inArray = $.inArray(val,allItems);
                if (inArray != -1){
                    finalList.push(val);
                    allItems.splice(inArray,1);
                }
            });
            finalList.push(...allItems);
            return finalList;
        }

        // Rebuild custom settings
        self.buildCustomSettings = function(){
             // build custom monitors - poor mans dynamic ko
            $('#TopTempSettingCustomMenu ul.dropdown-menu > li.TopTempCustMenu').remove();
            var template = $($('#settings_toptemp_customTemplate').wrap('p').parent().clone().html())
            if (Object.keys(self.settings.customMon).length){
                $('#TopTempSettingCustomMenu ul.dropdown-menu li.divider').show();
            }else{
                $('#TopTempSettingCustomMenu ul.dropdown-menu li.divider').hide();
            }
            $.each(self.settings.customMon,function(idx,val){
                var newId = 'settings_toptemp_'+idx;
                if (!$('#'+newId).length){
                    template.attr('id',newId);
                    template.attr('data-toptempcustomid',idx);
                    $('#settings_plugin_toptemp div.tab-content').append(template.wrap('p').parent().clone().html());
                }

                $('#'+newId).find('h4:first').text(val.name()+" main settings");

                // Observer input and set
                $('#'+newId).find('input[data-settings]').each(function(){
                    var $this = $(this);
                    var settingID = $this.data('settings');
                    // Recursive lookup the value
                    var curItem = settingID.split('.').reduce((p,c)=>p&&p[c]||null, self.settings.customMon[idx]);
                    var curVal = curItem();

                    // Handle checkbox vs input
                    if ($this.is(':checkbox')){
                        $this.prop('checked', curVal);
                        if (curVal){
                            $('#'+newId+' div[data-visible="'+settingID+'"]').show();
                        }else{
                            $('#'+newId+' div[data-visible="'+settingID+'"]').hide();
                        }
                        $this.off('change.toptemp').on('change.toptemp',function(){
                            curItem($(this).prop('checked'));
                            // Hide/show related
                            if ($(this).prop('checked')){
                                $('#'+newId+' div[data-visible="'+settingID+'"]').show();
                            }else{
                                $('#'+newId+' div[data-visible="'+settingID+'"]').hide();
                            }
                        });
                    }else{
                        $this.val(curVal);
                        if (curVal == ""){
                            $('#'+newId+' div[data-visible="'+settingID+'"]').hide();
                        }else{
                            $('#'+newId+' div[data-visible="'+settingID+'"]').show();
                        }
                        // Fix icon selector
                        if (settingID == "icon"){
                            $this.next().find('i').attr('class',curVal);
                        }
                        $this.off('change.toptemp').on('change.toptemp',function(){
                            curItem($(this).val());
                            // Fix icon selector
                            if (settingID == "icon"){
                                $this.next().find('i').attr('class',$(this).val());
                            }
                            // Hide/show related
                            if ($(this).val() == ""){
                                $('#'+newId+' div[data-visible="'+settingID+'"]').hide();
                            }else{
                                $('#'+newId+' div[data-visible="'+settingID+'"]').show();
                            }
                        });
                    }
                })

                // Observe custom mon fields
                $('#'+newId).find('input[data-custommon]').each(function(){
                    var settingID = $(this).data('custommon');
                    // Recursive lookup the value
                    var curItem = self.settings.customMon[idx][settingID];
                    var curVal = curItem();
                    if ($(this).is(':checkbox')){
                        $(this).prop('checked', curVal);
                        $(this).off('change.toptemp').on('change.toptemp',function(){
                            curItem($(this).prop('checked'));
                        });
                    }else{
                        $(this).val(curVal);
                        $(this).off('change.toptemp').on('change.toptemp',function(){
                            // Set namee
                            if (settingID == "name"){
                                var tabPane = $(this).closest('div.tab-pane');
                                var tabPID = tabPane.attr('id');
                                if ($(this).val() == ""){
                                    $('#TopTempSettingCustomMenu a[href="#'+tabPID+'"]').text(idx);
                                    tabPane.find('h4:first').text(idx+" main settings");
                                }else{
                                    $('#TopTempSettingCustomMenu a[href="#'+tabPID+'"]').text($(this).val());
                                    tabPane.find('h4:first').text($(this).val()+" main settings");
                                }
                            }
                            curItem($(this).val());
                        });
                    }
                })
                // Add menu item
                $('#TopTempSettingCustomMenu ul.dropdown-menu').prepend('<li class="TopTempCustMenu"><a data-toggle="tab" href="#'+newId+'">'+val.name()+'</a></li>')
            });


            // Test a command
            $('#settings_plugin_toptemp a.toptempTestCMD').off('click.toptem').on('click.toptem',function(){
                var $this = $(this);
                var cmdRun = $this.closest('div.input-append').find('input').val();
                var outputCon = $this.closest('div.tab-pane').find('div.toptempTestCMDOutContainer');
                var output = outputCon.find('div.toptempTestCMDOutput');
                if ($.trim(cmdRun) == ""){
                    return;
                }
                $this.attr( "disabled", true );
                output.html('<div class="alert alert-info"><strong>Wait...</strong></div>');
                OctoPrint.simpleApiCommand("toptemp", "testCmd", {'cmd':cmdRun}).done(function(response) {
                    if (!('success' in response) || response.success == false){
                        output.html('<div class="alert alert-error"><strong>Error</strong><br><pre>Error:\n<span class="text-error">  '+response.error+'</span>\nResult:\n<span class="text-error">  '+response.result+'</span>\nCode:\n<span class="text-error">  '+response.returnCode+'</span>\n</pre></div>');
                    }else{
                        output.html('<div class="alert alert-success"><strong>Success</strong><br>Returned: <code>'+response.result+'</code></div>');
                    }
                    if (outputCon.is(':hidden')){
                        outputCon.slideDown();
                    }
                    $this.attr('disabled',false);
                });
            });

            // Get cpu options
            OctoPrint.simpleApiCommand("toptemp", "getPredefined", {'reload':true}).done(function(response) {
                $('#settings_plugin_toptemp .topTempPreDefCmds li').remove();
                $.each(response,function(idx,val){
                    if (val[1] == null){
                        return;
                    }
                    var item = $('<li><a href="#" data->'+val[2]+'</a></li>');
                    item.on('click',function(){
                        $(this).closest('div.input-append').find('input').val(val[0]).trigger('change');
                    });
                    $('#settings_plugin_toptemp .topTempPreDefCmds').append(item);
                })
            });

            // Delete prev sorter
            if ($('#TopTempSortList').data('sorter') != null){
                $('#TopTempSortList').data('sorter').destroy();
            }

            // Build sorter
            $('#TopTempSortList').html('');
            var allItems = self.buildIconOrder();
            $.each(allItems,function(i,name){
                var settings = self.getSettings(name);
                if (self.isCustom(name)){
                    var prettyName = settings.name();
                }else{
                    var prettyName = name.replace("tool", "Tool ");
                    prettyName = prettyName.charAt(0).toUpperCase() + prettyName.slice(1);
                }
                // Skip non active - hackish
                var classNameHide = '';
                var iconVis = 'fa-eye';
                if (!settings.show()){
                    iconVis = 'fa-eye-slash';
                }
                if ((name == "chamber" && !self.tempModel.hasChamber()) || (name == "bed" && !self.tempModel.hasBed()) || (!self.tempModel.hasTools() && name[0] == "t") || (name[0] == "t" && (name.slice(-1)*1) > self.tempModel.tools().length-1) ){
                    return true;
                    // classNameHide = 'muted';
                }
                $('#TopTempSortList').append('<div class="accordion-group '+classNameHide+'" data-sortid="'+name+'"><div class="accordion-heading"><button class="btn btn-small" type="button" title="Sort item"><i class="fas fa-arrows-alt-v"></i></button>'+prettyName+'<i class="TopIconVisSort fas pull-right '+iconVis+'"></i></div></div>');
            });

            var sorter = Sortable.create($('#TopTempSortList')[0],{
                group: 'TopTempSortList',
                draggable: 'div.accordion-group',
                delay: 200,
                delayOnTouchOnly: true,
                sort: true,
                chosenClass: 'alert-info',
                direction: 'vertical',
                dragoverBubble: false,
                onStart: function(){
                    $('#drop_overlay').addClass('UICHideHard');
                },
                onEnd: function(evt){
                    $('#drop_overlay').removeClass('UICHideHard in');
                    if (self.previewOn){
                        var sortlist = $('#TopTempSortList >div').map(function(){return $(this).data('sortid')}).get();
                        $.each(sortlist,function(i,val){
                            $('#navbar_plugin_toptemp').append($('#navbar_plugin_toptemp_'+val));
                        });
                        self.fixMargins();
                    }

                }
            });

            // Store so we can destroy
            $('#TopTempSortList').data('sorter',sorter);

            // Add icon picker from UI Customizer if present
            if ('uICustomizerViewModel' in OctoPrint.coreui.viewmodels){
                // Cleanup
                $('#settings_plugin_toptemp .UICShowIconPicker').popover('destroy').removeAttr('title').removeData('original-title').removeAttr('data-original-title');
                $('#settings_plugin_toptemp .UICShowIconPicker').each(function(){
                    var $this = $(this);
                    var targetCon = $this.closest('div.tab-pane');
                    var targetID = targetCon.attr('id').replace('settings_toptemp_','');
                    $(this).popover(OctoPrint.coreui.viewmodels.uICustomizerViewModel.iconSearchPopover($this.find('i'),function(newicon,newcolor){
                        if (self.isCustom(targetID)){
                            // Update using the view
                            if (newicon !== false){
                                $this.find('i').attr('class',newicon);
                                $this.prev().val(newicon);
                                self.settings.customMon[targetID].icon(newicon);
                            }else{
                                $this.find('i').attr('class','');
                                $this.prev().val('');
                                self.settings.customMon[targetID].icon('');
                            }
                        }else{
                            // Update using the view
                            if (newicon !== false){
                                self.settings[targetID].icon(newicon);
                            }else{
                                self.settings[targetID].icon('');
                            }
                        }
                    },true,false,false,targetCon,'left')).attr('title','Click to change icon');
                });
            }else{
                $('#settings_plugin_toptemp .UICShowIconPicker').off('click.TopTempPlugin').on('click.TopTempPlugin',function(event){
                    new PNotify({
                        title: 'Instal UI Customizer',
                        text: 'In order to use the icon picker please install my UI Customizer plugin.<br><a target="_new" href="https://github.com/LazeMSS/OctoPrint-UICustomizer/">More...</a>',
                        type: "notice",
                        hide: false
                    });
                });
            }

            // Copy settings to all other items
            $('button.TopTempCopyToAll,button.TopTempCopyToTools').off('click.TopTempPlugin').on('click.TopTempPlugin',function(event){
                var src = $(this).closest('div.tab-pane').attr('id').replace('settings_toptemp_','');
                // Clone tools only?
                if (!$(this).hasClass('TopTempCopyToTools')){
                    $.each(self.mainTypes, function(id,target){
                        if (target != src){
                            self.cloneSettings(src,target);
                        }
                    });
                }
                var no = self.settings.noTools()-1;
                while (no >= 0){
                    var target = 'tool'+no;
                    if (target != src){
                        self.cloneSettings(src,target);
                    }
                    no--;
                }
            });

            $('button.TopTempDelete').off('click.TopTempPlugin').on('click.TopTempPlugin',function(event){
                var tabPane = $(this).closest('div.tab-pane');
                // Toggle
                $(this).toggleClass('btn-danger btn-success');
                $(this).find('i').toggleClass('fa-trash fa-undo');

                // Undo delete
                if (!$(this).hasClass('btn-success')){
                    tabPane.find('div.alert-danger.toptempWarn').remove();
                    $(this).find('span').text('Delete');
                    delete self.deleteCust[tabPane.data('toptempcustomid')];
                    return;
                }

                tabPane.find('h4:first').before('<div class="alert alert-danger toptempWarn"><i class="fas fa-exclamation-triangle pull-right"></i><strong>Marked for deletion</strong><br>Clicking save will delete this custom monitor.</div>');
                self.deleteCust[tabPane.data('toptempcustomid')] = true;
                $(this).find('span').text('Undo delete');
            });
        }

        // Init show
        self.onSettingsShown = function() {
            self.settingsSaved = false;
            self.settingsOpen = true;

            // Delete temporay items just to make sure
            self.tempNewCust = [];

            // Build custom settings
            self.buildCustomSettings();

            // Revert active delete
            $('button.TopTempDelete.btn-success').trigger('click');
            $('div.alert.toptempWarn').remove();

            // Add a new custom settings
            $('#settings_plugin_toptemp_newCustom').off('click').on('click',function(){
                var cmindex = Object.keys(self.settings.customMon).length;
                var newid = 'cu'+cmindex;
                while (newid in self.settings.customMon){
                    cmindex++;
                    newid = 'cu'+cmindex;
                }
                OctoPrint.simpleApiCommand("toptemp", "getDefaultSettings", {}).done(function(response) {
                    self.tempNewCust.push(newid);
                    self.settings.customMon[newid] = ko.mapping.fromJS({...{'new' :  ko.observable(true), 'delThis' :  ko.observable(false)}, ...response });
                    self.settings.customMon[newid]['name']('Custom '+cmindex);
                    // Build it all again
                    self.buildCustomSettings();
                    // Show an alert
                    $('#settings_toptemp_cu'+cmindex+' h4:first').before('<div class="alert alert-info toptempWarn"><strong>Not saved yet!</strong><br>Will be deleted if you close settings without saving.</div>');
                    $('#settings_toptemp_cu'+cmindex+' button.TopTempDelete').parent().remove();
                    // Show the new item
                    $('#TopTempSettingCustomMenu a[href="#settings_toptemp_cu'+cmindex+'"]').trigger('click');
                });
            });

            // Monitor padding/margin
            $('#settings_toptemp_outerm,#settings_toptemp_innerm').off("change.toptemp").on("change.toptemp",function(){
                self.fixMargins();
            });

            // Preview
            $('#TopTempTogglePreview i').removeClass('fa-check-square').addClass('fa-square');
            $('#TopTempTogglePreview').removeClass('active');
            $('#TopTempTogglePreview').off('click.TopTempPlugin').on('click.TopTempPlugin',function(event){
                $(this).find('i').toggleClass('fa-check-square fa-square');
                $(this).toggleClass('active');
                $('div.modal-backdrop').css('transition','top 0.1s linear');
                self.previewOn = !self.previewOn;
                if (self.previewOn){
                    // Sort them to update preview
                    var sortlist = $('#TopTempSortList >div').map(function(){return $(this).data('sortid')}).get();
                    $.each(sortlist,function(i,val){
                        $('#navbar_plugin_toptemp').append($('#navbar_plugin_toptemp_'+val));
                    });
                    self.fixMargins();
                    $('div.modal-backdrop').css('top',$('#navbar').outerHeight()+'px');
                }else{
                    // Restore sort order
                    $.each(self.settings.sortOrder(),function(i,val){
                        $('#navbar_plugin_toptemp').append($('#navbar_plugin_toptemp_'+val));
                    });
                    self.fixMargins();
                    $('div.modal-backdrop').css('top','0px');
                }
            });


            // Settings top icons
            $('#TopTempSettingsBar a').not('#TopTempTogglePreview').off('click.TopTempPlugin').on('click.TopTempPlugin',function(event){
                // fix visibily icon
                if ($(this).attr('href') == '#settings_toptemp_general'){
                    // Update the sorter display of hidden/shown
                    var allItems = self.buildIconOrder();
                    $.each(allItems,function(i,name){
                        var settings = self.getSettings(name);
                        var iconVis = 'fa-eye';
                        if (!settings.show()){
                            iconVis = 'fa-eye-slash';
                        }
                        $('#TopTempSortList div[data-sortid="'+name+'"] i.TopIconVisSort').removeClass('fa-eye fa-eye-slash').addClass(iconVis);
                    });
                }
                // Hide popover
                $('.UICShowIconPicker').popover('hide');
            });

            // Click general to make sure its always shown
            $('#settings_plugin_toptemp a[href="#settings_toptemp_general"]').trigger('click')

            // Cleanup ui and hide unwanted items
            if (self.tempModel.hasBed()){
                $('#settings_plugin_toptemp a[href="#settings_toptemp_bed"]').show();
            }else{
                $('#settings_plugin_toptemp a[href="#settings_toptemp_bed"]').hide();
            }
            if (self.tempModel.hasChamber()){
                $('#settings_plugin_toptemp a[href="#settings_toptemp_chamber"]').show();
            }else{
                $('#settings_plugin_toptemp a[href="#settings_toptemp_chamber"]').hide();
            }

            // Hide all tools
            $('.TopTempHideTool').hide();
            $('#TopTempSettingXtraTools').hide();
            if (self.tempModel.hasTools()){
                // Should we show the drop down for the rest of the tools
                if (OctoPrint.coreui.viewmodels.temperatureViewModel.tools().length == 1){
                    // Show only tool 0
                    $('#settings_plugin_toptemp a[href="#settings_toptemp_tool0"]').show();
                }else{
                    // Show the menu anc show each tool
                    $('#TopTempSettingXtraTools').show();
                    $.each(self.tempModel.tools(),function(indx,val){
                        $('#settings_plugin_toptemp a[href="#settings_toptemp_tool'+indx+'"]').show();
                    });
                }
            }
        }

        // Clone settings
        self.cloneSettings = function(source,target){
            var setClone = function(clonetarget,newVal,lvl1,lvl2){
                // skipe cloning basic
                if ($.inArray(lvl1,['label','icon']) != -1){
                    return;
                }
                // Skip unsupported shared settings
                if (OctoPrint.coreui.viewmodels.topTempViewModel.settings[clonetarget][lvl1] == undefined){
                    return;
                }
                if (lvl2 != null){
                    // Skip unsupported shared settings
                    if (OctoPrint.coreui.viewmodels.topTempViewModel.settings[clonetarget][lvl1][lvl2] == undefined){
                        return
                    }
                    OctoPrint.coreui.viewmodels.topTempViewModel.settings[clonetarget][lvl1][lvl2](newVal)
                }else{
                    OctoPrint.coreui.viewmodels.topTempViewModel.settings[clonetarget][lvl1](newVal)
                }
            }
            // Only two layers deep could not be bother to do a recursive
            $.each(OctoPrint.coreui.viewmodels.topTempViewModel.settings[source],function(idx1,val1){
                if (typeof val1 == "object"){
                    $.each(val1,function(idx2,val2){
                        setClone(target,val2(),idx1,idx2);
                    });
                }else{
                    setClone(target,val1(),idx1,null);
                }
            })

        }

        // UI ready
        self.onAllBound = function(){
            // Include chartist if not included by others
            if (typeof Chartist != "object"){
                $('head').append('<link rel="stylesheet" href="/plugin/toptemp/static/css/chartist.min.css">');
                $.getScript('/plugin/toptemp/static/js/chartist.min.js');
            }
            if (typeof Sortable != "function"){
                $.getScript('/plugin/toptemp/static/js/Sortable.min.js');
            }

            // Wait for the temperature model to be ready
            var initSub = self.tempModel.isOperational.subscribe(function(state){
                self.buildContainers(true);
                // Remove ourselves
                initSub.dispose();
            })

            // Main sub
            self.tempModel.isOperational.subscribe(function(state){
                if (state){
                    $('#navbar_plugin_toptemp div.TopTempPrinter').show();
                }else if(self.settings.hideInactiveTemps()){
                    $('#navbar_plugin_toptemp div.TopTempPrinter').hide();
                }
            });

            // Get history
            OctoPrint.simpleApiCommand("toptemp", "getCustomHistory", {}).done(function(response) {
                self.customHistory = response;
            });
        }

        // Build containers
        self.buildContainers = function(firstRun){
            $('#navbar_plugin_toptemp').html('');
            var allItems = self.buildIconOrder();
            // Build containers
            $.each(allItems, function(id,name){
                // Skip inactive
                if ( (name == "chamber" && !self.tempModel.hasChamber()) || (name == "bed" && !self.tempModel.hasBed()) || (name[0] == "t" && (name.slice(-1)*1) > self.tempModel.tools().length-1) ){
                    return true;
                }
                if (self.isCustom(name)){
                    self.buildContainer(name,'TopTempCustom TopTempLoad');
                }else{
                    self.buildContainer(name,'TopTempPrinter TopTempLoad');
                }
            });
            self.fixMargins();
            // Get data from history
            $.each(self.customHistory,function(k,v){
                if ($('#navbar_plugin_toptemp_'+k).length){
                    self.FormatTempHTML(k,{'actual' : v[v.length-1]},true);
                }
            });
            // Hide all non operationel
            if (!firstRun && self.settings.hideInactiveTemps() && self.tempModel.isOperational() !== true){
                $('#navbar_plugin_toptemp div.TopTempPrinter').hide();
            }
        }

        self.isCustom = function(string){
            if (string.slice(0,2) == "cu"){
                return true;
            }else{
                return false;
            }
        }

        self.getSettings = function(id){
            if (self.isCustom(id)){
                return self.settings.customMon[id];
            }else{
                return self.settings[id];
            }
        }

        self.fixMargins = function(){
            $('#navbar_plugin_toptemp').css({'margin-right' : self.settings.outerMargin()+'px','margin-left' : self.settings.outerMargin()+'px'});
            $('#navbar_plugin_toptemp >div').css('margin-right',self.settings.innerMargin()+'px');
            $('#navbar_plugin_toptemp >div:visible:last').css('margin-right','0px');
        }

        // Build a single container
        self.buildContainer = function(name,className){
            var elname = 'navbar_plugin_toptemp_'+name;
            var settings = self.getSettings(name);
            if (self.isCustom(name)){
                var prettyName = settings.name();
            }else{
                var prettyName = name.replace("tool", "Tool ");
                prettyName = prettyName.charAt(0).toUpperCase() + prettyName.slice(1);
            }

            if (self.settings.leftAlignIcons()){
                className += " IconsLeft";
            }
            // Remove old
            $('#'+elname).remove();
            // Build new
            $('#navbar_plugin_toptemp').append('<div title="'+prettyName+'" id="'+elname+'" class="'+className+'"><div id="TopTempGraph_'+name+'_graph" class="TopTempGraph"></div><div id="navbar_plugin_toptemp_'+name+'_text" class="TopTempText"></div></div>');
            if (!settings.show()){
                $('#'+elname).hide();
            }
            self.setGraphStyle(name,settings.graphSettings);
            return elname;
        }

        // Add CSS for the graphs
        self.setGraphStyle = function(name,settings){
            // Remove old
            $('#TopTempGraph_'+name+'_style').remove();
            // Build new
            $('head').append('<style id="TopTempGraph_'+name+'_style">\n#TopTempGraph_'+name+'_graph{\nheight:'+settings.height()+'%\n}\n#TopTempGraph_'+name+'_graph.TopTempGraph > svg >g .ct-line{\nstroke-width: '+settings.width()+'px;\nstroke-opacity: '+settings.opa()+';\nstroke: '+settings.color()+';\n}\n</style>'    );
            // Show the graph?
            if (settings.show){
                $('#TopTempGraph_'+name+'_graph').show();
            }else{
                $('#TopTempGraph_'+name+'_graph').hide();
            }
        }

        // Bind the settings to an easier variable
        self.onBeforeBinding = function () {
            self.settings = self.settingsViewModel.settings.plugins.toptemp;
            $.each(self.settings.customMon,function(i,v){
                self.settings.customMon[i]['new'] = ko.observable(false);
                self.settings.customMon[i]['updated'] = ko.observable(0);
                self.settings.customMon[i]['delThis'] = ko.observable(false);
            });
        };
    }

    // This is how our plugin registers itself with the application, by adding some configuration information to
    // the global variable ADDITIONAL_VIEWMODELS
    OCTOPRINT_VIEWMODELS.push([
        // This is the constructor to call for instantiating the plugin
        TopTempViewModel,

        // This is a list of dependencies to inject into the plugin, the order which you request here is the order
        // in which the dependencies will be injected into your view model upon instantiation via the parameters
        // argument
        ["settingsViewModel","temperatureViewModel"],

        // Finally, this is the list of all elements we want this view model to be bound to.
        []
    ]);
});

/* TopTemp END */
