import time
import sys
import importlib
import common
importlib.reload(common)
import numpy as np
from threading import Thread
import os
import pandas as pd






TESTER_IP = '192.168.1.99'
# Create rsa driver and
rsa = common.RSaDriver()
# Create Tester driver
tester = common.Imx6Controller(IP=TESTER_IP, mode='TESTER')
tester.load_params()
# create DUT driver

# find DUT IP address by MAC ADDRESS
common.update_arp('192.168.1')
code = False

while not code:
    mac = input("Please insert device MAC Address (type 0 for EXIT):")
    code = common.check_user_input(mac, 'MAC')

# mac = 'd0:63:b4:02:86:27'
DUT_IP = common.find_ip_by_mac(mac.lower().replace(':', '-'))

# DUT_IP = '192.168.1.101'

dut = common.Imx6Controller(IP=DUT_IP, mode='DUT')
dut.load_params()

common.kill_novelda_app(DUT_IP, 'root', 'E5#C4*TnzRog')
common.kill_novelda_app(TESTER_IP, 'root', 'tester')

# get return value
mac = [None]
thread_dut = Thread(target=common.run_imx_app, kwargs=dict(mode='DUT', ip=DUT_IP, username='root', password='E5#C4*TnzRog', mac=mac))
thread_tester = Thread(target=common.run_imx_app, kwargs=dict(mode='TESTER', ip=TESTER_IP, username='root', password='tester', mac=[]))

thread_dut.start()
thread_tester.start()
time.sleep(2)
# Check connectivity
connectionThreads = [Thread(target=rsa.connect), Thread(target=tester.connect), Thread(target=dut.connect)]

for t in connectionThreads:
    t.start()
for t in connectionThreads:
    t.join()

mac = mac[0]

if not rsa.isConnected or not dut.isConnected or not tester.isConnected:
    input("Press 'ENTER' to exit...")
    sys.exit()

code = False

# user input - SERIAL NUMBER
while not code:

    sn = input("Please insert device serial number (type 0 for EXIT):")
    code = common.check_user_input(sn, 'SN')
# basic config for rsa
rsa.config()
# create calculator class
calc = common.Calculator()
# create excel handler class
exHdlr = common.ExcelHandler()

dutRev = '3.1'
dutSerialNumber = sn
deviceMAC = mac
deviceInfo = [dutRev, dutSerialNumber, mac["eth0"], mac["wlan0"]]

exHdlr.set_device_info(deviceInfo)

# load tx setup
rsa.load_setup('tx')
# change to full transmit gain
dut.change_transmition_gain(3)


for i in range(8):
    rsa.refresh_trace()
    tester.switch('tx', i)
    time.sleep(0.1)

    # transmit for long time (3sec)
    for n in range(50):
        dut.switch('tx', i)

    spectrum = rsa.get_spectrum_curve()
    p = calc.measures(spectrum)

    exHdlr.txDf["8.3GHz [dBm]"][i] = p[0]
    exHdlr.txDf["8.58GHz [dBm]"][i] = p[1]
    exHdlr.txDf["8.9GHz [dBm]"][i] = p[2]
    print("### Done Tx #" + str(i), end='\r')

# clear buffer
dut.clear_buffer()
# load tx setup
rsa.load_setup('rx')
# change to full transmit gain
dut.change_transmition_gain(0)

for i in range(32):
    # SNR test
    tester.switch('rx', i)
    time.sleep(0.1)
    # transmit for 1 second
    for n in range(10):
        data = dut.switch('rx', i)
        calc.snr(data)

    SNR = calc.mean_snr_db()

    exHdlr.rxDf["SNR [dB]"][i] = SNR

    exHdlr.save()

    # cross SNR test
    tester.switch('rx', (i+1) % 32)
    time.sleep(0.1)
    # transmit for 1 second
    for n in range(10):
        data = dut.switch('rx', i)
        calc.snr(data)

    SNR = calc.mean_snr_db()

    exHdlr.rxDf["Cross Antenna loss [dB]"][i] = exHdlr.rxDf["SNR [dB]"][i] - SNR

    exHdlr.save()

    print("### Done Rx #"+str(i), end='\r')

# REPORT

time.sleep(1)

txRes = exHdlr.txDf > exHdlr.txRef
rxRes = exHdlr.rxDf > exHdlr.rxRef

txRes = txRes.drop(columns="Sector + Tx bit")
rxRes = rxRes.drop(columns="Sector")

txFalses = 1 - txRes.values
rxFalses = 1 - rxRes.values

txNotPassed = np.sum(txFalses)
rxNotPassed = np.sum(rxFalses)
# save the final excel. maor addition
exHdlr.final_excel((txNotPassed or rxNotPassed), sn, exHdlr.tx_test_excel(sn), exHdlr.rx_test_excel(sn))

if txNotPassed or rxNotPassed:
    print('Device test results' + str(sn) + ':   Failed')
else:
    print('Device test results' + str(sn) + ':   Pass')

print("The test was completed successfully")




