import pyvisa  # package for communicating with tektronix RSA device
import numpy as np
import os
import socket
import struct
from xml.etree import cElementTree as ElementTree
import pandas as pd
from io import StringIO
from xlsxwriter.exceptions import FileCreateError
import subprocess
import sys
import re  # regular expression
from fabric import Connection  # ssh connection
from threading import Thread
import win32com.client as win32  # expand of the columns in the excel


def run_imx_app(mode, ip, username, password, mac):
    p = {'password': password}
    conn = Connection(ip, user=username, connect_kwargs=p, connect_timeout=3)

    try:
        if mode == 'TESTER':
            # run "EchoCareTester" app in tester
            conn.run('/home/debian/EchoCareTester > /dev/null 2>&1')  # > /dev/null 2>&1' for dropping the printings
        elif mode == 'DUT':
            mac[0] = get_mac_with_ssh(conn)
            # run batch file which kills EchoSystem app and starts NoveldaAppMatlab_01.02
            conn.run('/home/debian/EchoCareTester.sh > /dev/null 2>&1')
    except:
        print('Problem with SSH connection to device')
        pass

    return mac


def kill_novelda_app(ip, username, password):
    p = {'password': password}
    conn = Connection(ip, user=username, connect_kwargs=p, connect_timeout=3)

    try:
        conn.run('killall NoveldaAppMatlab_01.02')
    except:
        print('Problem with SSH connection to device in kill NoveldaApp')
        pass


def kill_echosystem_app(ip, username, password):
    p = {'password': password}
    conn = Connection(ip, user=username, connect_kwargs=p, connect_timeout=3)

    try:
        conn.run('killall EchoSystem')
    except:
        print('Problem with SSH connection to device in kill EchoSystem')
        pass


def get_mac_with_ssh(connection):
    # conn is SSH connection (fabric package)

    MACaddressStrLen = 17
    # run if config command on linux
    response = connection.run('ifconfig')
    # extract response string
    ifconfigStr = response.__str__()

    interfaces = ['eth0', 'wlan0']  # names of internet interfaces [ ETHERNET AND WIFI ]
    MACaddresses = {interfaces[0]: None, interfaces[1]: None}
    # find MAC addresses
    for interface in interfaces:
        wlanIdx = ifconfigStr.find(interface)

        if wlanIdx == -1:  # interface was not found
            continue

        etherIdx = ifconfigStr[wlanIdx:].find('ether')

        MACidx = wlanIdx + etherIdx + len('ether') + 1

        MACaddress = ifconfigStr[MACidx:MACidx + MACaddressStrLen]

        MACaddresses[interface] = MACaddress

    return MACaddresses


def update_arp(subnet):
    def ping(ip_last_byte):
        r = os.system('ping -n 1 ' + subnet + '.' + str(ip_last_byte))

    pingThreads = [None] * 256

    for i in range(256):
        pingThreads[i] = Thread(target=ping, kwargs=dict(ip_last_byte=i))

    for t in pingThreads:
        t.start()

    for t in pingThreads:
        t.join()

    print('Done')


def find_ip_by_mac(mac):
    # the max should be xx_xx_xx_xx_xx_xx format

    arpStr = subprocess.check_output('arp -a').decode()

    idx = arpStr.find(mac)

    if idx == -1:
        print('MAC address was not found !!!')
        return 0

    subStr = arpStr[:idx]

    for i in range(len(subStr)):
        if subStr[len(subStr) - i - 1] != ' ':
            ipEndIdx = len(subStr) - i
            break

    for i in range(ipEndIdx):
        if subStr[ipEndIdx - i - 1] == ' ':
            ipStartIdx = ipEndIdx - i
            break

    return subStr[ipStartIdx:ipEndIdx]


def check_user_input(userInput, *args):
    if userInput == '0':
        sys.exit()

    if args:
        inputType = args[0]

    if inputType == 'SN':
        if len(userInput) != 8:
            return False

        return re.match("[0-9]{8}", userInput) is not None

    elif inputType == 'MAC':

        return re.match("[0-9a-f]{2}([-:]?)[0-9a-f]{2}(\\1[0-9a-f]{2}){4}$", userInput.lower()) is not None


def check_ping(IP):
    r = subprocess.check_output('ping -n 1 ' + IP)
    if 'Destination host unreachable' in r.decode():
        return 0
    else:
        return 1


class RSaDriver:

    def __init__(self):
        self.rsa = None  # this is the object which controls the SignalVu SW
        self.txSetupFile = 'setup\\tx_setup.Setup'
        self.rxSetupFile = 'setup\\rx_setup.Setup'
        self.isConnected = False

    def connect(self):

        rm = pyvisa.ResourceManager()
        listResources = rm.list_resources()

        if len(listResources) > 0:  # if any instrument is detected

            conncted = False
            counter = 0

            while counter < 3:  # try to connected to instrument 3 times
                try:
                    self.rsa = rm.open_resource(listResources[0])
                    print(self.rsa.query('*idn?'))
                    conncted = True
                    break
                except:
                    counter += 1

        if not conncted:
            print('### RSA: cannot connect to signalVu')
        else:
            print('### RSA: is connected')

        self.isConnected = conncted

        return conncted

    def config(self):
        #  parameters for communication with SignalVu
        self.rsa.timeout = 5000
        self.rsa.encoding = 'latin_1'
        self.rsa.write_termination = None
        self.rsa.read_termination = '\n'

    def disconnect(self):

        self.rsa.close()

    def load_setup(self, type):

        startStr = 'MMEMORY:LOAD:STATE "' + os.getcwd() + '\\'
        endStr = '"'

        if type == 'rx':
            cmd = startStr + self.rxSetupFile
        elif type == 'tx':
            cmd = startStr + self.txSetupFile

        cmd = cmd + endStr

        self.rsa.write(cmd)  # TBD: need to check return value

        print(type + " setup is loaded")

    def get_spectrum_curve(self):

        curve = None

        try:
            curve = self.rsa.query_binary_values('FETCh:SPECtrum:TRACe?', datatype='f', container=np.array)
        except:
            print('Problem with getting data from sprctrum')

        return curve

    def init_data_acquition(self):

        self.rsa.write('initiate:immediate')
        self.rsa.query('*opc?')

    def refresh_trace(self):

        self.rsa.write('SENSe:SPECtrum:CLEar:RESults')


class Imx6Controller(socket.socket):
    PORT = 5044
    configFilePath = "setup\\novelda_params_for_tests.xml"

    opCode = {
        "INIT": b'I',  # opCode for INIT command
        "SWITCH": b'M'  # opCode for switch/get signal command
    }

    range = struct.pack("f", 5)

    def __init__(self, IP, mode, *args):
        super().__init__(socket.AF_INET, socket.SOCK_DGRAM)

        self.IP = IP
        self.settimeout(2)  # set timeout for 1 second
        self.serverAddress = (self.IP, self.PORT)
        self.params = None
        self.recvBufferLen = None
        self.fileContentTXT = None  # same as params, but in txt format
        self.NoFasts = None
        self.Nbins = 3
        self.mode = mode
        self.isConnected = False

        if args:  # if args is not empty
            loadParams = args[0]  # first element of args is "True" or "False" (whether load the params or not
            if loadParams:
                self.load_params()

        if mode == 'TESTER':
            self.dataType = 'B'
            self.baselinesTx = [48, 16, 40, 8, 32, 0, 56, 24]
            self.baselinesRx = [
                7, 6, 5, 4, 3, 2, 1, 0,
                31, 30, 29, 28, 27, 26, 25, 24,
                23, 22, 21, 20, 19, 18, 17, 16,
                15, 14, 13, 12, 11, 10, 9, 8
            ]
        elif mode == 'DUT':
            self.dataType = 'f'
            self.baselinesTx = [16, 48, 24, 56, 0, 32, 8, 40]
            self.baselinesRx = range(32)

    def load_params(self):
        # open novelda params xml file
        with open(self.configFilePath, "r") as fp:
            self.fileContentTXT = fp.read()

        root = ElementTree.XML(self.fileContentTXT)
        self.params = XmlDictConfig(root)
        self.NoFasts = int(int(self.params["FPS_Motion"]) * float(self.params["motionTime"]))
        self.recvBufferLen = int(self.params["udpBufferLength"])

    def change_transmition_gain(self, value):

        if type(value) is not int:
            print("value must be an integer !!!")
            return
        if value < 0 or value > 3:
            print("Value mast be  !!!")
            return

        self.params["transmitGain"] = str(value)

        transmitGianIdx = self.fileContentTXT.find('</transmitGain>')
        self.fileContentTXT = self.fileContentTXT[:transmitGianIdx - 1] + str(value) + self.fileContentTXT[
                                                                                       transmitGianIdx:]

        self.connect()  # send new params to novelda (with new transmission gain)

    def switch(self, testType, ant):

        if testType == 'tx':
            baseline = self.baselinesTx[ant]
        elif testType == 'rx':
            baseline = self.baselinesRx[ant]

        # antenna number to bytes (uint8)
        antBytes = struct.pack("B", baseline)

        # send cmg to get signal switch
        cmd = self.opCode["SWITCH"] + self.range + antBytes

        self.sendto(cmd, self.serverAddress)

        # set long buffer length
        self.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.NoFasts * self.recvBufferLen)

        data = np.zeros([self.NoFasts, self.Nbins])

        for i in range(self.NoFasts):
            try:
                # receive one fast
                buffer = self.recv(self.recvBufferLen)

                # if we are in TESTER mode just get ack and return
                if self.mode == 'TESTER':
                    return 1

                parsedData = np.frombuffer(buffer, dtype=np.dtype(self.dataType), count=-1, offset=0)

                data[i, :] = parsedData[1:]

            except socket.timeout:
                print("Time out !!!")
                return 0

        return data

    def clear_buffer(self):

        while True:
            try:
                self.recv(self.recvBufferLen)
            except socket.timeout:
                break

    def connect(self):

        if not check_ping(self.IP):
            print('Cannot ping to ' + self.mode)
            return self.isConnected
        # the command is the opcode and file content
        if self.fileContentTXT is None:
            print("Load novelda params file first !!!")
            return 0

        self.clear_buffer()

        cmd = self.opCode["INIT"] + self.fileContentTXT.encode()

        # send command through udp
        self.sendto(cmd, self.serverAddress)

        if self.mode == 'TESTER':
            r = self.switch('tx', 1)

            if r:
                print("### Tester: is connected")
                self.isConnected = True
                return self.isConnected
            else:
                print("### Tester: app isn't running")
                return self.isConnected

        # receive ack ( only for DUT )
        try:
            data = self.recv(self.recvBufferLen)

            ack = data[0]

            # first element in revc buffer should be "1"
            if ack == 1:
                # the rest of the buffer is Nbins (uint16)
                self.Nbins = struct.unpack("H", data[1:])[0]
                print("### DUT: is connected")
                self.isConnected = True
                return self.Nbins

        except socket.timeout:
            print("### DUT: app isn't running")
            return self.isConnected


class ExcelHandler:

    def __init__(self):

        self.filePath = 'test\\'  # the name of the folder with results
        # first sheet - Device INFO
        data = 'Revision, Serial Number, eth MAC, wlan MAC\n'
        self.deviceInfo = pd.read_csv(StringIO(data))
        # second sheet - Rx tests
        col = ["Sector + Tx bit", "8.3GHz [dBm]", "8.58GHz [dBm]", "8.9GHz [dBm]"]
        data = np.zeros([8, len(col)])
        data[:, 0] = np.array([10, 11, 20, 21, 30, 31, 40, 41])
        self.txDf = pd.DataFrame(index=range(8), columns=col, data=data, dtype=float)
        self.txDf.index.name = 'Tx #'

        # third sheet - Rx tests
        col = ["Sector", "SNR [dB]", "Cross Antenna loss [dB]"]
        data = np.zeros([32, len(col)])

        for i in range(4):
            data[i * 8:(i + 1) * 8, 0] = np.ones(8) * (i + 1)

        self.rxDf = pd.DataFrame(index=range(32), columns=col, data=data, dtype=float)
        self.rxDf.index.name = 'Rx #'

        self.txRef = pd.read_excel('setup\\txRef.xlsx')
        self.rxRef = pd.read_excel('setup\\rxRef.xlsx')

    def set_device_info(self, info):
        # info[0] - revision
        # info[1] - serial number
        # info[0] - max address

        self.filePath = self.filePath + info[1] + '.xlsx'  # serial number
        data = 'Revision, Serial Number, eth MAC, wlan MAC\n'
        for str in info:
            data += ',' + str

        self.deviceInfo = pd.read_csv(StringIO(data))

        self.save()

    def save(self):
        try:
            # write all to excel file
            with pd.ExcelWriter(self.filePath) as writer:
                self.deviceInfo.to_excel(writer, sheet_name='Device info', index=None)
                self.txDf.to_excel(writer, sheet_name='Tx test', float_format='%.2f')
                self.rxDf.to_excel(writer, sheet_name='Rx test', float_format='%.2f')

                workbook = writer.book

                format = workbook.add_format({
                    'align': 'center'})

                worksheet = writer.sheets['Device info']
                worksheet.set_column('A:D', 16, format)

                worksheet = writer.sheets['Tx test']
                worksheet.set_column('A:F', 16, format)

                worksheet = writer.sheets['Rx test']
                worksheet.set_column('A:D', 16, format)

        except FileCreateError:
            print("Problem with saving xlsx file. Probably the file is opened")
            sys.exit()

    def expand_columns(self, outfile):  # expend columns (when the file open - the columns will be in the max width)

        excel = win32.gencache.EnsureDispatch('Excel.Application')

        cwd = os.getcwd()
        wb = excel.Workbooks.Open(cwd + '/test/' + outfile)
        ws = wb.Worksheets("Sheet1")
        ws.Columns.AutoFit()
        wb.Save()
        excel.Application.Quit()

    def rx_test_excel(self, sn):  # check the values of the Rx and color in red the failed result.

        df = pd.read_excel('test//' + sn + '.xlsx', sheet_name=2)

        df_ref = pd.read_excel('setup/rxRef.xlsx')
        df['Test antenna SNR Diff'] = (df['SNR [dB]'] - df_ref['SNR [dB'])
        df['Test cross antenna loss'] = (df['Cross Antenna loss [dB]'] - df_ref['Cross Antenna loss [dB]'] < 0) * \
                                  (df['Cross Antenna loss [dB]'] - df_ref['Cross Antenna loss [dB]'])
        test_threshold = 0
        df.style.apply(lambda x: ["background:red" if x < test_threshold else "background: green"
                                  for x in df.test_83GHz], axis=0)
        df_styled = df.style \
            .applymap(
            lambda x: 'background-color: %s' % 'red' if x < test_threshold else 'background-color: %s' % 'white',
            subset=['Test antenna SNR Diff', 'Test cross antenna loss'])
        # df_styled.to_excel('test/rx_test.xlsx', engine='openpyxl', index=False)

        return df_styled

    def tx_test_excel(self, sn):  # check the values of the Tx and color in red the failed result.

        df = pd.read_excel('test//' + sn + '.xlsx',
                           sheet_name=1)
        df_ref = pd.read_excel('setup\\txRef.xlsx')
        df['test_8.3GHz'] = (df['8.3GHz [dBm]'] - df_ref['8.3GHz [dBm]'] < 0) * (
                df['8.3GHz [dBm]'] - df_ref['8.3GHz [dBm]'])
        df['test_8.58GHz'] = (df['8.58GHz [dBm]'] - df_ref['8.58GHz [dBm]'] < 0) * (
                df['8.58GHz [dBm]'] - df_ref['8.58GHz [dBm]'])
        df['test_8.9GHz'] = (df['8.9GHz [dBm]'] - df_ref['8.9GHz [dBm]'] < 0) * (
                df['8.9GHz [dBm]'] - df_ref['8.9GHz [dBm]'])
        df = df.replace(0, '')

        test_threshold = 0

        df_styled = df.style. \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.3GHz [dBm]'][0] - df_ref['8.3GHz [dBm]'][
            0]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[0, ['8.3GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.3GHz [dBm]'][1] - df_ref['8.3GHz [dBm]'][
            1]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[1, ['8.3GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.3GHz [dBm]'][2] - df_ref['8.3GHz [dBm]'][
            2]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[2, ['8.3GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.3GHz [dBm]'][3] - df_ref['8.3GHz [dBm]'][
            3]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[3, ['8.3GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.3GHz [dBm]'][4] - df_ref['8.3GHz [dBm]'][
            4]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[4, ['8.3GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.3GHz [dBm]'][5] - df_ref['8.3GHz [dBm]'][
            5]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[5, ['8.3GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.3GHz [dBm]'][6] - df_ref['8.3GHz [dBm]'][
            6]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[6, ['8.3GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.3GHz [dBm]'][7] - df_ref['8.3GHz [dBm]'][
            7]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[7, ['8.3GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.58GHz [dBm]'][0] - df_ref['8.58GHz [dBm]'][
            0]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[0, ['8.58GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.58GHz [dBm]'][1] - df_ref['8.58GHz [dBm]'][
            1]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[1, ['8.58GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.58GHz [dBm]'][2] - df_ref['8.58GHz [dBm]'][
            2]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[2, ['8.58GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.58GHz [dBm]'][3] - df_ref['8.58GHz [dBm]'][
            3]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[3, ['8.58GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.58GHz [dBm]'][4] - df_ref['8.58GHz [dBm]'][
            4]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[4, ['8.58GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.58GHz [dBm]'][5] - df_ref['8.58GHz [dBm]'][
            5]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[5, ['8.58GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.58GHz [dBm]'][6] - df_ref['8.58GHz [dBm]'][
            6]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[6, ['8.58GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.58GHz [dBm]'][7] - df_ref['8.58GHz [dBm]'][
            7]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[7, ['8.58GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.9GHz [dBm]'][0] - df_ref['8.9GHz [dBm]'][
            0]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[0, ['8.9GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.9GHz [dBm]'][1] - df_ref['8.9GHz [dBm]'][
            1]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[1, ['8.9GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.9GHz [dBm]'][2] - df_ref['8.9GHz [dBm]'][
            2]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[2, ['8.9GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.9GHz [dBm]'][3] - df_ref['8.9GHz [dBm]'][
            3]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[3, ['8.9GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.9GHz [dBm]'][4] - df_ref['8.9GHz [dBm]'][
            4]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[4, ['8.9GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.9GHz [dBm]'][5] - df_ref['8.9GHz [dBm]'][
            5]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[5, ['8.9GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.9GHz [dBm]'][6] - df_ref['8.9GHz [dBm]'][
            6]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[6, ['8.9GHz [dBm]']]). \
            applymap(lambda x: 'background-color: %s' % 'red' if (df['8.9GHz [dBm]'][7] - df_ref['8.9GHz [dBm]'][
            7]) < 0 else 'background-color: %s' % 'white', subset=pd.IndexSlice[7, ['8.9GHz [dBm]']])

        # df_styled.to_excel('test/tx_test.xlsx', engine='openpyxl', index=False)
        return df_styled

    def final_excel(self, failed, sn, df2, df3):  # save the final excel file
        # failed - failed or pass -  for the file's name.
        # df2 -  Tx test
        # df3 -  Rx test

        if failed:
            file_name = 'Failed_' + sn + '.xlsx'
        else:
            file_name = 'Pass_' + sn + '.xlsx'

        writer = pd.ExcelWriter('test\\' + file_name, engine='xlsxwriter')
        df1 = pd.read_excel('test\\' + sn + '.xlsx', sheet_name=0)
        df1.to_excel(writer, sheet_name='Device info')
        df2.to_excel(writer, sheet_name='Tx test')
        df3.to_excel(writer, sheet_name='Rx test')
        writer.save()

        excel = win32.gencache.EnsureDispatch('Excel.Application')

        cwd = os.getcwd()
        wb = excel.Workbooks.Open(cwd + '\\test\\' + file_name)
        ws = wb.Worksheets("Device info")
        ws.Columns.AutoFit()
        ws = wb.Worksheets("Tx test")
        ws.Columns.AutoFit()
        ws = wb.Worksheets("Rx test")
        ws.Columns.AutoFit()
        wb.Save()
        excel.Application.Quit()

        os.remove("test\\" + sn + ".xlsx")


class Calculator:
    freq8GhzIdx = 176  # lowest freq (idx) inside the band for Rx test
    freq9_5GhzIdx = 209  # highest freq (idx) inside the band for Rx test
    NUMBER_OF_SIGNALS = 10  # number of times we average the spectrum
    FFT_LEN = 512
    samplingRate_Ghz = 23.238
    startFreq_Ghz = 7.5
    endFreq_Ghz = 9.5

    def __init__(self):
        self.SNR = np.zeros(10)
        self.SNRpointer = 0
        self.freq = np.linspace(0, self.samplingRate_Ghz / 2, num=int(self.FFT_LEN / 2) + 1)
        self.txFreqPoints = [8.3, 8.58, 8.9]  # in GHz, for tx test

    # for rx test
    def snr(self, x):
        # real fft for each row (fast signal) (512 points) -> abs -> power 2
        X = np.fft.rfft(x, n=self.FFT_LEN).__abs__().__pow__(2)
        # mean for each frequnecy
        X_mean = X.mean(axis=0)

        # SNR = peak/median
        noise = np.median(X_mean[self.freq8GhzIdx:self.freq9_5GhzIdx])
        signal = np.max(X_mean)

        self.SNR[self.SNRpointer] = signal / noise

        self.SNRpointer = (self.SNRpointer + 1) % self.NUMBER_OF_SIGNALS

        # plt.plot(self.freq, 10*np.log10(X_mean))
        # plt.plot(self.freq[self.freq8GhzIdx:self.freq9_5GhzIdx], 10 * np.log10(noise) * np.ones(self.freq9_5GhzIdx - self.freq8GhzIdx))

    # for rx test
    def mean_snr_db(self):
        meanSNR = self.SNR.mean()

        return 10 * np.log10(meanSNR)

    # for tx test
    def peak_power(self, data):
        return data.max()

    def measures(self, data):
        p = []  # all the power measures

        # spectrum frequency axis
        freqAxis = np.linspace(self.startFreq_Ghz, self.endFreq_Ghz, data.shape[0])

        # iterate over all the wanted frequencies
        for freq in self.txFreqPoints:
            idx = (np.abs(
                freqAxis - freq)).argmin()  # find the index of freq in vector freqAxis (for 3 freqs in self.txFreqPoints)

            p.append(data[idx])

        return p

    def fail_or_pass(self, test_result):  # not in use!

        result = True
        for col in test_result:
            for check in test_result[col]:
                result = result and check
        return result


# ================== OPEN SOURCE CLASSES ================== #

# this 2 classes are for reading xml files


class XmlListConfig(list):
    def __init__(self, aList):
        for element in aList:
            if element:
                # treat like dict
                if len(element) == 1 or element[0].tag != element[1].tag:
                    self.append(XmlDictConfig(element))
                # treat like list
                elif element[0].tag == element[1].tag:
                    self.append(XmlListConfig(element))
            elif element.text:
                text = element.text.strip()
                if text:
                    self.append(text)


class XmlDictConfig(dict):
    '''
    Example usage:

    >>> tree = ElementTree.parse('your_file.xml')
    >>> root = tree.getroot()
    >>> xmldict = XmlDictConfig(root)

    Or, if you want to use an XML string:

    >>> root = ElementTree.XML(xml_string)
    >>> xmldict = XmlDictConfig(root)

    And then use xmldict for what it is... a dict.
    '''

    def __init__(self, parent_element):
        if parent_element.items():
            self.update(dict(parent_element.items()))
        for element in parent_element:
            if element:
                # treat like dict - we assume that if the first two tags
                # in a series are different, then they are all different.
                if len(element) == 1 or element[0].tag != element[1].tag:
                    aDict = XmlDictConfig(element)
                # treat like list - we assume that if the first two tags
                # in a series are the same, then the rest are the same.
                else:
                    # here, we put the list in dictionary; the key is the
                    # tag name the list elements all share in common, and
                    # the value is the list itself
                    aDict = {element[0].tag: XmlListConfig(element)}
                # if the tag has attributes, add those to the dict
                if element.items():
                    aDict.update(dict(element.items()))
                self.update({element.tag: aDict})
            # this assumes that if you've got an attribute in a tag,
            # you won't be having any text. This may or may not be a
            # good idea -- time will tell. It works for the way we are
            # currently doing XML configuration files...
            elif element.items():
                self.update({element.tag: dict(element.items())})
            # finally, if there are no child tags and no attributes, extract
            # the text
            else:
                self.update({element.tag: element.text})
