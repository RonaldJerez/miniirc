import os
import logging
import tempfile
from miniirc import IRC

def test_set_logger_level_and_name():
    irc = IRC('localhost', 6667, 'testnick')
    irc.set_logger('miniirc.testlogger', level=logging.INFO)
    assert irc.log.name == 'miniirc.testlogger'
    assert irc.log.level == logging.INFO

def test_set_logger_file_and_format():
    irc = IRC('localhost', 6667, 'testnick')
    with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
        filename = tmpfile.name

    log_format = '%(levelname)s:%(name)s:%(message)s'
    irc.set_logger('miniirc.filelogger', filename=filename, format=log_format, level=logging.WARNING)
    irc.log.warning('Test warning message')

    with open(filename, 'r') as f:
        content = f.read()
    assert 'WARNING:miniirc.filelogger:Test warning message' in content

    os.remove(filename)

def test_instance_loggers_are_distinct():
    import tempfile
    from miniirc import logger

    irc1 = IRC('localhost', 6667, 'nick1')
    irc2 = IRC('localhost', 6667, 'nick2')

    with tempfile.NamedTemporaryFile(delete=False) as tmpfile1, tempfile.NamedTemporaryFile(delete=False) as tmpfile2:
        file1 = tmpfile1.name
        file2 = tmpfile2.name

    irc1.set_logger('miniirc.instance1', filename=file1, level=logging.INFO)
    irc2.set_logger('miniirc.instance2', filename=file2, level=logging.ERROR)

    # The loggers should be different objects
    assert irc1.log is not irc2.log
    assert irc1.log is not logger
    assert irc2.log is not logger

    # irc1 should log INFO, irc2 should only log ERROR
    irc1.log.info('Info from irc1')
    irc2.log.info('Info from irc2')  # Should not appear
    irc2.log.error('Error from irc2')

    with open(file1, 'r') as f1, open(file2, 'r') as f2:
        content1 = f1.read()
        content2 = f2.read()

    assert 'Info from irc1' in content1
    assert 'Info from irc2' not in content2
    assert 'Error from irc2' in content2

    os.remove(file1)
    os.remove(file2)
