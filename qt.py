import numpy as np
import qrc_resources
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt, QSize, pyqtSignal, pyqtSlot, QTimer
from PyQt5 import QtGui
from PyQt5.QtWidgets import (
    QMainWindow, QLabel, QApplication, QInputDialog, QLineEdit, QToolBar,
    QAction, QProgressBar
    )
from PyQt5.QtWidgets import QDialogButtonBox, QVBoxLayout, QPushButton, QWidget, QHBoxLayout
from PyQt5.QtGui import QIcon
import pickle
import sys
import time
from threading import Thread

from common import find_ip_by_mac, Calculator, ExcelHandler
from operation import connect_to_tester, connect_to_dut, connect_to_rsa
from validations import validate_ip, validate_sn




# pythonguis qtdesigner tutorial
# https://stackoverflow.com/questions/9957195/updating-gui-elements-in-multithreaded-pyqt
# https://realpython.com/python-menus-toolbars/#building-python-menu-bars-menus-and-toolbars-in-pyqt


messages = {
    'startup': "Connect Ethernet to Tester to begin",
    'tester_not_found': "Tester not found. Ensure proper configuration is set"
                        " and that the ethernet cable is connected to the Tester",
    'tester_found': "Tester found. Connect ethernet and power cable to DUT",
    'DUT_not_found': 'DUT not found. Check Ethernet connection',
    'DUT_found': "DUT found. Enter Serial Number of DUT",
    'RSA_not_found': 'RSA not found. Ensure that RSA is connected by usb to PC and SignalVu '
                     'application is open',
    'running_tests': 'Running Tests',
    'passed': "Test Passed!",
    'failed': "Test failed!",
}

CONFIG_DICT = {}
CONFIG_PATH = "./configuration.p"


class MainWindow(QMainWindow):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize(600, 400)
        self.message = messages['startup']
        # MainWindow requires a central widget
        self.central_widget = None
        self.progress_bar = None
        self.config_window = None
        self.setWindowTitle('EchoCare Tester')
        self.setup()
        self.create_toolbar()
        self.create_status_bar()
        self.create_progress_bar()
        # set a delay for the configuration to run
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.configuration)
        self.timer.start(1000)
        self.thread = FlowControl()
        self.thread.state.connect(self.update_message)

    def setup(self):
        # another option I would try is using QVBoxLayout and putting 2 dummy widgets above and
        # below the text. This might allow it to easily center the text
        layout = QVBoxLayout()
        self.central_widget = QLabel(self)
        self.central_widget.resize(320, 100)
        self.central_widget.setText("<h2>" + self.message + "<h2>")
        self.central_widget.setStyleSheet(
            """
            QWidget {
                color: blue;
            }    
            """
        )
        # this is the center with respect to the window - need
        # to account for Widget size
        self.central_widget.move(QtCore.QPoint(self.rect().center().x() - self.central_widget.width()//2,
                                 self.rect().center().y() - self.central_widget.height()//2))

    def resizeEvent(self, a0: QtGui.QResizeEvent) -> None:
        self.central_widget.move(QtCore.QPoint(self.rect().center().x() - self.central_widget.width() // 2 + 1,
                                               self.rect().center().y() - self.central_widget.height() // 2 + 1))

    def create_toolbar(self):
        # create a configurations tool buttons to set the configurations
        tools = self.addToolBar('Config')
        tools.setFixedHeight(20)
        self.configAction = QAction(QIcon(":config.svg"), "&Configuration", self)
        tools.addAction(self.configAction)

    def create_status_bar(self):
        self.statusbar = self.statusBar()

    def create_progress_bar(self):
        self.progress_bar = QProgressBar()
        self.statusbar.addPermanentWidget(self.progress_bar)
        self.progress_bar.setVisible(False)

    def run(self):
        self.thread.start()

    def configuration(self):
        self.configAction.triggered.connect(lambda: self.configuration_state("optional_config"))
        global CONFIG_DICT
        self.statusbar.showMessage("Searching For Configuration File", 1000)
        try:
            with open(CONFIG_PATH, 'rb') as f:
                CONFIG_DICT = pickle.load(f)
        except FileNotFoundError:
            status_string = 'required_config'
            self.configuration_state(status_string)
            self.statusbar.showMessage("No Saved Configuration Found", 1000)
        else:
            if not isinstance(CONFIG_DICT, dict) or not CONFIG_DICT:
                # can add message that save file was corrupted
                self.statusbar.showMessage("Saved Configuration Corrupted", 1000)
                status_string = 'required_config'
                self.configuration_state(status_string)
        self.statusbar.showMessage("Configuration Found", 3000)

    def configuration_state(self, status):
        print(status)
        self.config_window = ConfigurationWindow(status)
        self.config_window.closed.connect(self.config_closed)
        self.config_window.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
        self.config_window.show()

    def config_closed(self):
        print('Config Closed')

    def update_message(self, message):
        self.message = message
        if message == messages['tester_found']:
            self.statusbar.showMessage("Connecting to DUT and RSA", 1000)
        elif message == messages['failed'] or message == messages['passed']:
            self.main_window.statusbar.showMessage("Test Complete!", 1000)


class ConfigurationWindow(QMainWindow):
    closed = pyqtSignal()

    def __init__(self, status, parent=None):
        super().__init__(parent)
        self.status = status
        self.resize(400, 200)
        self.widgets = {}
        self.setWindowTitle('Configuration Settings')
        self.setup()

    def setup(self):
        layout = QVBoxLayout()
        pc_ip = QLineEdit(self)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self.widgets['pc_ip'] = pc_ip
        self.widgets['button_box'] = button_box
        if self.status == 'optional_config':
            pc_ip.insert(CONFIG_DICT['pc_ip'])
        else:
            pc_ip.setPlaceholderText("Enter PC IP")
        reg_obj = validate_ip(pc_ip)
        pc_ip.setValidator(reg_obj)
        pc_ip.textChanged.connect(self.check_ip)
        pc_ip.returnPressed.connect(self.accept)
        layout.addWidget(pc_ip, alignment=QtCore.Qt.AlignCenter)
        layout.addWidget(button_box, alignment=QtCore.Qt.AlignCenter)
        # need to add a dummy widget to apply the layout to the window
        widget = QWidget()
        widget.setMaximumWidth(200)
        widget.setLayout(layout)
        # centers the widget in the window
        widget_horiz = QWidget()
        layout_horiz = QHBoxLayout()
        layout_horiz.addWidget(widget)
        widget_horiz.setLayout(layout_horiz)
        self.setCentralWidget(widget_horiz)

    def check_ip(self, *args, **kwargs):
        # https://snorfalorpagus.net/blog/2014/08/09/validating-user-input-in-pyqt4-using-qvalidator/
        sender = self.sender()
        validator = sender.validator()
        state = validator.validate(sender.text(), 0)[0]
        if state == QtGui.QValidator.Acceptable:
            color = '#c4df9b'
        elif state == QtGui.QValidator.Intermediate:
            color = '#fff79a'
        else:
            color = '#f6989d'
        sender.setStyleSheet('QLineEdit { background-color: %s }' % color)

    def accept(self):
        """
        signal for the "accept" type
        """
        print("accepted")
        ip = self.widgets['pc_ip']
        if ip.validator().validate(ip.text(), 0)[0] == QtGui.QValidator.Acceptable:
            CONFIG_DICT['pc_ip'] = ip.text()
            with open(CONFIG_PATH, 'wb') as f:
                pickle.dump(CONFIG_DICT, f)
            self.closed.emit()
            self.close()

    def reject(self):
        print('rejected')
        if self.status == 'required_config':
            return
        else:
            self.closed.emit()
            self.close()


class SerialNumberDialog(QMainWindow):
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize(400, 200)
        self.widgets = {}
        self.setWindowTitle('Enter Serial Number')
        self.sn = None
        self.setup()

    def setup(self):
        layout = QVBoxLayout()
        sn = QLineEdit(self)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok, self)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self.widgets['sn'] = sn
        self.widgets['button_box'] = button_box

        sn.setPlaceholderText("Enter Serial Number")
        reg_obj = validate_sn(sn)
        sn.setValidator(reg_obj)
        sn.textChanged.connect(self.check_sn)
        sn.returnPressed.connect(self.accept)
        layout.addWidget(sn, alignment=QtCore.Qt.AlignCenter)
        layout.addWidget(button_box, alignment=QtCore.Qt.AlignCenter)
        # need to add a dummy widget to apply the layout to the window
        widget = QWidget()
        widget.setMaximumWidth(200)
        widget.setLayout(layout)
        # centers the widget in the window
        widget_horiz = QWidget()
        layout_horiz = QHBoxLayout()
        layout_horiz.addWidget(widget)
        widget_horiz.setLayout(layout_horiz)
        self.setCentralWidget(widget_horiz)

    def accept(self):
        sn = self.widgets['sn']
        if sn.validator().validate(sn.text(), 0)[0] == QtGui.QValidator.Acceptable:
            self.sn = sn.text()
            self.accept.emit()
            self.close()

    def reject(self):
        # serial number cannot be rejected
        return

    def check_sn(self, *args, **kwargs):
        # gets the sending widget
        sender = self.sender()
        validator = sender.validator()
        state = validator.validate(sender.text(), 0)[0]
        if state == QtGui.QValidator.Acceptable:
            color = '#c4df9b'
        elif state == QtGui.QValidator.Intermediate:
            color = '#fff79a'
        else:
            color = '#f6989d'
        sender.setStyleSheet('QLineEdit { background-color: %s }' % color)


class FlowControl(QtCore.QThread):
    """
    Class for managing the GUI flow.
    """
    # signal for indicating a state change in the main window
    state = QtCore.pyqtSignal(str)

    def __init__(self):
        """
        start up in the startup state and look for the configuration pickle file.
        If it does not exist move to the configuration state.
        """
        super().__init__()
        self.tester = None
        self.dut = None
        self.rsa = None
        self.sn = None
        self._sn_valid = False
        self.timeout = 2

    def _connect_ethernet_to_tester(self):
        # open a socket and wait for a response
        # I think you should continually emit a signal (in some time interval) when the ethernet is found,
        # and only if the conditions are met (ie valid config) should you block the signal
        # and continue
        tester_connected = False
        start = time.perf_counter()
        while not tester_connected:
            ip = find_ip_by_mac("whence is it from")
            if ip != 0:
                self.tester = connect_to_tester(ip)
                tester_connected = self.tester.isConnected
            stop = time.perf_counter()
            if stop - start > self.timeout:
                self.state.emit(messages['tester_not_found'])

    def run(self):
        self._connect_ethernet_to_tester()
        self.state.emit(messages['tester_found'])
        connected = False
        start = time.perf_counter()
        while not connected:
            self.rsa = connect_to_rsa()
            connected = self.rsa.isConnected
            stop = time.perf_counter()
            if stop - start > self.timeout:
                self.state.emit(messages['RSA_not_found'])
        connected = False

        while not connected:
            ip = 'find'
            self.dut = connect_to_dut(ip)
            connected = self.dut.isConnected
            stop = time.perf_counter()
            if stop - start > self.timeout:
                self.state.emit(messages['DUT_not_found'])
        self.state.emit(messages['DUT_found'])
        # can also make serial number an attribute of DUT
        self._get_sn()
        self.state.emit(messages['running_tests'])

        calc = Calculator()
        # create excel handler class
        excel_handler = ExcelHandler()

        dut_rev = '3.1'
        deviceInfo = [dut_rev, self.sn, self.dut.mac["eth0"], self.dut.mac["wlan0"]]

        excel_handler.set_device_info(deviceInfo)

        # load tx setup
        self.rsa.load_setup('tx')
        # change to full transmit gain
        self.dut.change_transmition_gain(3)

        self.main_window.progress_bar.setVisible(True)
        self.main_window.progress_bar.setMinimum(0)
        self.main_window.progress_bar.setMaximum(8)
        self.main_window.progress_bar.setValue(0)
        self.main_window.progress_bar.text('Tx Test')
        for i in range(8):
            self.rsa.refresh_trace()
            self.tester.switch('tx', i)
            time.sleep(0.1)

            # transmit for long time (3sec)
            for n in range(50):
                self.dut.switch('tx', i)

            spectrum = self.rsa.get_spectrum_curve()
            p = calc.measures(spectrum)

            excel_handler.txDf["8.3GHz [dBm]"][i] = p[0]
            excel_handler.txDf["8.58GHz [dBm]"][i] = p[1]
            excel_handler.txDf["8.9GHz [dBm]"][i] = p[2]
            self.main_window.statusbar.showMessage("### Done Tx #" + str(i))
            self.main_window.progress_bar.setValue(i + 1)

        # clear buffer
        self.dut.clear_buffer()
        # load tx setup
        self.rsa.load_setup('rx')
        # change to full transmit gain
        self.dut.change_transmition_gain(0)
        self.main_window.progress_bar.setMinimum(0)
        self.main_window.progress_bar.setMaximum(32)
        self.main_window.progress_bar.setValue(0)
        self.main_window.progress_bar.text('Rx Test')

        for i in range(32):
            # SNR test
            self.tester.switch('rx', i)
            time.sleep(0.1)
            # transmit for 1 second
            for n in range(10):
                data = self.dut.switch('rx', i)
                calc.snr(data)

            SNR = calc.mean_snr_db()

            excel_handler.rxDf["SNR [dB]"][i] = SNR

            excel_handler.save()

            # cross SNR test
            self.tester.switch('rx', (i + 1) % 32)
            time.sleep(0.1)
            # transmit for 1 second
            for n in range(10):
                data = self.dut.switch('rx', i)
                calc.snr(data)

            SNR = calc.mean_snr_db()

            excel_handler.rxDf["Cross Antenna loss [dB]"][i] = excel_handler.rxDf["SNR [dB]"][i] - SNR

            excel_handler.save()
            self.main_window.progress_bar.setValue(i + 1)
            self.main_window.statusbar.showMessage("### Done Rx #" + str(i))

        # REPORT
        time.sleep(1)

        tx_res = excel_handler.txDf > excel_handler.txRef
        rx_res = excel_handler.rxDf > excel_handler.rxRef

        tx_res = tx_res.drop(columns="Sector + Tx bit")
        rx_res = rx_res.drop(columns="Sector")

        tx_false = 1 - tx_res.values
        rx_false = 1 - rx_res.values

        tx_not_passed = np.sum(tx_false)
        rx_not_passed = np.sum(rx_false)

        # save the final excel.
        excel_handler.final_excel((tx_not_passed or rx_not_passed),
                                  self.sn, excel_handler.tx_test_excel(self.sn),
                                  excel_handler.rx_test_excel(self.sn))

        if tx_not_passed or rx_not_passed:
            self.state.emit(messages['failed'])
        else:
            self.state.emit(messages['passed'])

    def _get_sn(self):
        sn_dialog = SerialNumberDialog()
        sn_dialog.accept.connect(self._valid_sn)
        while not self._sn_valid:
            pass
        self.sn = sn_dialog.sn

    def _valid_sn(self):
        self._sn_valid = False


if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    tester = QTimer()
    tester.timeout.connect(main_window.run)
    tester.setSingleShot(True)
    tester.start(5000)
    sys.exit(app.exec_())
