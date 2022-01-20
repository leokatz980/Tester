from common import Imx6Controller, run_imx_app, kill_novelda_app, kill_echosystem_app, RSaDriver
from threading import Thread
import time


class DeviceController(Imx6Controller):
    """
    Class for controlling a device (DUT or Tester)
    """
    def __init__(self, IP, mode, *args):
        super().__init__(IP, mode, *args)
        self.imx_app_thread = None
        self.mac = [None] if self.mode == 'DUT' else []
        # how best to handle pw?!
        self.pw = "E5#C4*TnzRog" if self.mode == 'DUT' else '123456'
        self._setup()

    def _setup(self):
        """
        Kills all running programs and runs the relevant imx app
        """
        self.load_params()
        kill_novelda_app(self.IP, 'root', self.pw)
        kill_echosystem_app(self.IP, 'root', self.pw)
        self.imx_app_thread = Thread(target=run_imx_app,
                                     kwargs=dict(mode=self.mode,
                                                 ip=self.IP, username='root',
                                                 password=self.pw, mac=self.mac))
        self.imx_app_thread.start()
        time.sleep(2)


def connect_to_tester(IP, *args):
    tester = DeviceController(IP, 'TESTER', *args)
    connection_thread = Thread(target=tester.connect)
    connection_thread.start()
    connection_thread.join()
    return tester


def connect_to_dut(IP, *args):
    dut = DeviceController(IP, 'DUT', *args)
    connection_thread = Thread(target=dut.connect)
    connection_thread.start()
    connection_thread.join()
    return dut


def connect_to_rsa():
    rsa = RSaDriver()
    rsa.config()
    connection_thread = Thread(target=rsa.connect)
    connection_thread.start()
    connection_thread.join()
    return rsa
