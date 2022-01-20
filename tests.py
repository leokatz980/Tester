import warnings


class TestBench:
    """
    contains a collection of Test or TestBench classes which it calls in sequence.
    Amalgamates logs for each test and broadcasts the results.
    """
    def __init__(self, tests, name=None, listeners=None):
        """
        tests: a dictionary of named tests to run. Each test must contain the log, run, and result methods
        listeners: list of elements which are updated with test results after the test is run
        """
        self.tests = tests
        self.listeners = None
        self.name = None
        self._log = {}
        self.passed = False

    def run(self):
        for key, value in self.tests.items():
            self._log[key] = value.run()
        self._check_status()
        self.broadcast()
        return self._log

    def _check_status(self):
        fail_flag = 0
        for key, value in self.tests.items():
            if not value.passed:
                fail_flag = 1
        if not fail_flag:
            self.passed = True

    def broadcast(self):
        if self.listeners is not None:
            for elem in self.listeners:
                try:
                    elem.update(self)
                except AttributeError:
                    warnings.warn("An object was passed as a listener which does not contain the update method")

    
