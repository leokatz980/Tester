from PyQt5.QtGui import QRegExpValidator
from PyQt5.QtCore import QRegExp

"""
Some people, when confronted with a problem, think “I know, I’ll use regular expressions.”

Now they have two problems.
"""


def validate_ip(parent=None):
    # don't put a space in {1,3}
    pattern = QRegExp(r'[0-9]{3}\.[0-9]{3}\.[0-9]{1,3}\.[0-9]{1,3}')
    return QRegExpValidator(pattern, parent)


def validate_sn(parent=None):
    pattern = QRegExp(r'[0-9]{8}')
    return QRegExpValidator(pattern, parent)