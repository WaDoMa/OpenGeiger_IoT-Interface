#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# Initially published in 2011 by Lionel Bergeret under the CC0 license.
# Gratefully adopted and advanced by WaDoMan in 2015.
#
# ----------------------------------------------------------------
# The contents of this file are distributed under the CC0 license.
# See http://creativecommons.org/publicdomain/zero/1.0/
# ----------------------------------------------------------------

# pyusb module
import usb.util
import usb.legacy

# HTTP modules
import httplib, urllib, urllib2

# System modules
import time, datetime
import ConfigParser
import subprocess
import os

# SMTP protocol client module
import smtplib

# Multiprocess
from multiprocessing import Pool

# opengeiger usb device information
ID_VENDOR = 0x20a0
ID_PRODUCT = 0x4176

# opengeiger requests definition
GM01A_RequestGetCPMperUsvh    = 0x00
GM01A_RequestGetCPM           = 0x01
GM01A_RequestGetTotalCount    = 0x02
GM01A_RequestGetIntervalCount = 0x03

GM01A_RequestGetHVVolt 			= 0x80
GM01A_RequestGetBattVolt 		= 0x81
GM01A_RequestGetPFMOn 			= 0x82
GM01A_RequestGetPFMCycle 		= 0x83
GM01A_RequestGetStackCount 		= 0x84
GM01A_RequestGetRandom		 	= 0x90
GM01A_RequestStartRandomStream	= 0x91
GM01A_RequestStopRandomStream	= 0x92

# geiger tube convertion factor
usvh_per_cpm = 150.0 # Cs-137 1uSv/h (25cps/mR/h)

# CSV backup file update
def UpdateCSVBackup(field1, field2):
    # Write to file
    receiveTime = time.strftime('%Y-%m-%d %H:%M',time.localtime()) 
    csvfile = open('opengeiger.csv', 'a')
    csvfile.write("%s,%d,%.3f\n" % (receiveTime, field1, field2))
    csvfile.close()

# ThingSpeak stream update
def UpdateThingspeak(apikey, field1, field2):
    params = urllib.urlencode({'field1': field1, 'field2': field2,'key': apikey})
    headers = {"Content-type": "application/x-www-form-urlencoded","Accept": "text/plain"}
    conn = httplib.HTTPConnection("api.thingspeak.com:80")
    conn.request("POST", "/update", params, headers)
    response = conn.getresponse()
    print ">", response.status, response.reason
    data = response.read()
    conn.close()

# Pachube stream update
def UpdatePachube(feedid, apikey, field1, field2):
    # Pachube API V2 and CSV data format
    opener = urllib2.build_opener(urllib2.HTTPHandler)
    request = urllib2.Request('http://api.pachube.com/v2/feeds/'+feedid+'/datastreams/0.csv?_method=put', "%d" % (field1))
    request.add_header('Host','api.pachube.com')
    request.add_header('X-PachubeApiKey', apikey)
    url = opener.open(request)
    request = urllib2.Request('http://api.pachube.com/v2/feeds/'+feedid+'/datastreams/1.csv?_method=put', "%0.3f" % (field2))
    request.add_header('Host','api.pachube.com')
    request.add_header('X-PachubeApiKey', apikey)
    url = opener.open(request)

# RRDTool
create = """%s create %s --step '60' 'DS:cpm:GAUGE:120:0:10000' 'DS:microsievert:GAUGE:120:0:100' 'RRA:LAST:0.5:1:288' 'RRA:AVERAGE:0.5:1:2880' 'RRA:AVERAGE:0.5:10:4464' 'RRA:MIN:0.5:10:4464' 'RRA:MAX:0.5:10:4464'"""
update = "%s update %s N:%d:%.3f"
graph = """%s graph %s-%s.png --start -%s --end now --width=620 --height=200 --vertical-label "CPM" DEF:average1=%s:cpm:AVERAGE 'DEF:average1wk=%s:cpm:AVERAGE:start=-1w' DEF:average2=%s:microsievert:AVERAGE LINE2:average1#00FF00:'CPM'"""
graphPrints = """'GPRINT:average1:MIN:Min\: %2.0lf CPM' 'GPRINT:average1:MAX:Max\: %2.0lf CPM' 'GPRINT:average1:LAST:Last\: %2.0lf CPM' 'GPRINT:average2:LAST:Last\: %2.3lf uSv/h\j'"""
graphTrend = """'VDEF:D2=average1,LSLSLOPE' 'VDEF:H2=average1,LSLINT' 'CDEF:avg1=average1,POP,D2,COUNT,*,H2,+' 'LINE2:avg1#FFBB00:Trend since %s:dashes=10'"""
graphTrend1wk = """'VDEF:D3=average1wk,LSLSLOPE' 'VDEF:H3=average1wk,LSLINT' 'CDEF:avg1wk=average1wk,POP,D3,COUNT,*,H3,+' 'LINE:avg1wk#0077FF:Trend since 1w:dashes=10'"""

def GenerateGraph(rrdtool, rrddb, rrdpng, period):
    cmd = graph % (rrdtool, rrdpng, period, period, rrddb, rrddb, rrddb)
    cmd += " "+graphPrints
    cmd += " "+graphTrend % period
    cmd += " "+graphTrend1wk
    subprocess.call(cmd, shell=True)

def UpdateRRDTool(rrdtool, rrddb, rrdpng, field1, field2):
    cmd = update % (rrdtool, rrddb, field1, field2)
    subprocess.call(cmd, shell=True)

    GenerateGraph(rrdtool, rrddb, rrdpng, "1h")
    GenerateGraph(rrdtool, rrddb, rrdpng, "6h")
    GenerateGraph(rrdtool, rrddb, rrdpng, "12h")
    GenerateGraph(rrdtool, rrddb, rrdpng, "1d")

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == '__main__':  #Checks, if program is being run directly. Do nothing, if being just importet into another module.
    dev = usb.core.find(idVendor = ID_VENDOR, idProduct = ID_PRODUCT)
    # Check if opengeiger device is available
    if dev is None:
        raise ValueError('Device not found')

    # Load config settings
    config = ConfigParser.ConfigParser()
    config.read(".pyopengeiger")

    # Make sure rrd database is ready (if needed)
    if "rrdtool" in config.sections():
        rrdtool = config.get('rrdtool', 'rrdTool')
        rrddb = config.get('rrdtool', 'rrdDb')
        rrdpng = config.get('rrdtool', 'rrdPng')
        if not os.path.exists(rrddb):
            cmd = create % (rrdtool, rrddb)
            subprocess.call(cmd, shell=True)

    # Create the thread pool
    pool = Pool()
       
    # Start measurements
    while (True):
        # Collect the raw data
        result = dev.ctrl_transfer((usb.legacy.ENDPOINT_IN | usb.legacy.RECIP_DEVICE | usb.legacy.TYPE_VENDOR),
              GM01A_RequestGetCPM, 0, 0, 1, timeout = 5000)
        if len(result) != 1:
            continue
        result2 = dev.ctrl_transfer((usb.legacy.ENDPOINT_IN | usb.legacy.RECIP_DEVICE | usb.legacy.TYPE_VENDOR),
              GM01A_RequestGetCPMperUsvh, 0, 0, 1, timeout = 5000)
        if len(result2) != 1:
            continue
        CUSV = result2.tolist()[0]
        print "%d" %CUSV
        # Extract CPM and compute usv/h
        CPM = result.tolist()[0]
        usvh = float(CPM/usvh_per_cpm)

        # Update streams
        print "%s - %d CPM %0.3f µSv/h" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), CPM, usvh)
        time.sleep(1)                
        try:
            UpdateCSVBackup(CPM, usvh)


            if "thingspeak" in config.sections():
                thingspeakAPIKey = config.get('thingspeak', 'apiKey')
                UpdateThingspeak(thingspeakAPIKey, CPM, usvh)
                pool.apply_async(UpdateThingspeak, (thingspeakAPIKey, CPM, usvh))

            if "pachube" in config.sections():
                pachubeFeedID = config.get('pachube', 'feedID')
                pachubeAPIKey = config.get('pachube', 'apiKey')
                UpdatePachube(pachubeFeedID, pachubeAPIKey, CPM, usvh)
                pool.apply_async(UpdatePachube, (pachubeFeedID, pachubeAPIKey, CPM, usvh))

            if "rrdtool" in config.sections():
                UpdateRRDTool(rrdtool, rrddb, rrdpng, CPM, usvh)
                pool.apply_async(UpdateRRDTool, (rrdtool, rrddb, rrdpng, CPM, usvh))

            if "email" in config.sections() and "alarm" in config.sections() and (usvh >= float(config.get('alarm', 'threshold'))):
                emailserverurl = config.get('email', 'serverurl')
                emaillogin = config.get('email', 'login') 
                emailpassword = config.get('email', 'password')
                emailsender = config.get('email', 'sender')
                emailrecipients = config.get('email', 'recipients')
                emailmessage = "From: %s\nTo: %s\nSubject: Radiation level: %0.3f µSv/h\n\nThe radiation level on %s at %s was %0.3f µSv/h and therefore %0.2f times the alerting threshold level of %0.3f µSv/h." % (emailsender, emailrecipients, usvh, datetime.datetime.now().strftime("%Y-%m-%d"), datetime.datetime.now().strftime("%H:%M:%S"), usvh, usvh / float(config.get('alarm', 'threshold')), float(config.get('alarm', 'threshold')))
                server = smtplib.SMTP(emailserverurl)
                server.starttls()
                server.login(emaillogin,emailpassword)
                server.sendmail(emailsender, emailrecipients.split(","), emailmessage)  #Note: comma-delimited string from config-file needs to be converted to list by str.split method for being a parameter of sendmail method
                server.quit()
                print "\nThe following email alert was triggered by a threshold exeedance:\n\n%s\n\n" % emailmessage

            time.sleep(60)
        except:
            print "Failed to update servers, retry in 1 second ..."
            time.sleep(1)
            pass

    # Wait the pool to be completed
    pool.close()
    pool.join()




