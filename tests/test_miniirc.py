import re
import pytest
import miniirc
import collections
import pathlib
from miniirc import IRCMessage, Hostmask

def fill_in_hostmask(hostmask):
    parts = list(hostmask) + [''] * (3 - len(hostmask))
    return Hostmask(*parts[:3])

def test_fill_in_hostmask():
    assert fill_in_hostmask(()) == Hostmask('', '', '')
    assert fill_in_hostmask(('B',)) == Hostmask('B', '', '')
    assert fill_in_hostmask(('B', 'C')) == Hostmask('B', 'C', '')
    assert fill_in_hostmask(('B', 'C', 'D')) == Hostmask('B', 'C', 'D')

def test_message_parser():
    p = miniirc.ircv3_message_parser
    for i in range(4):
        hostmask = fill_in_hostmask(('n', 'u', 'h')[:i])
        hostmask_s = ':n!u@h'[:i * 2] + (' ' if i else '')
        assert (p(hostmask_s + 'PRIVMSG #channel :Hello world!') ==
                IRCMessage('PRIVMSG', hostmask, {},
                            ['#channel', 'Hello world!']))

    hostmask = fill_in_hostmask(())
    empty_tag = ''
    assert (p(r'@tag1=value\:\swith\s\\spaces\rand\nnewlines;tag2;tag3= Hi') ==
            ('HI', hostmask,
             {'tag1': 'value; with \\spaces\rand\nnewlines', 'tag2': empty_tag,
              'tag3': empty_tag}, []))

def test_version():
    pyproject_toml = pathlib.Path(__file__).resolve().parent.parent / 'pyproject.toml'
    with pyproject_toml.open() as f:
        match = re.search(r"version *= [\"']([0-9\.a-z]+)[\"']", f.read())
    assert match
    assert miniirc.__version__ == match.group(1)

    assert ('.'.join(map(str, miniirc.ver[:3])) + ''.join(miniirc.ver[3:])
            == miniirc.__version__)
    assert miniirc.version == 'miniirc IRC framework v' + miniirc.__version__

def test_dict_to_tags():
    dict_to_tags = miniirc._dict_to_tags
    tags_dict = collections.OrderedDict((
        ('abc', True), ('def', False), ('ghi', ''), ('jkl', 'test\r\n; ')
    ))
    assert dict_to_tags(tags_dict) == rb'@abc;jkl=test\r\n\:\s '

def test_logfile():
    msgs = []
    logfile = miniirc._Logfile(msgs.append)
    logfile.write('Hello world!\nThis is a test\rmessage\nto test the ')
    logfile.write('_Logfile class.')
    logfile.write('\n')
    print('This is', 'the final line', file=logfile)
    assert msgs == [
        'Hello world!',
        'This is a test\rmessage',
        'to test the _Logfile class.',
        'This is the final line'
    ]

class DummyIRC(miniirc.IRC):
    def __init__(self, ip='', port=0, nick='', *args, **kwargs):
        kwargs['auto_connect'] = False
        super().__init__(ip, port, nick, *args, **kwargs)

class IRCQuoteWrapper(DummyIRC):
    res: tuple | None  = None
    TEST_FUNC = 'quote'
    async def quote(self, *args, force=None, tags=None):
        assert self.res is None
        self.res = (' '.join(args), tags)

    @classmethod
    async def test(cls, *args, **kwargs):
        self = cls()
        await getattr(self, cls.TEST_FUNC)(*args, **kwargs)
        return self.res

    @classmethod
    def make_test(cls, test_func):
        class res(cls):
            TEST_FUNC = test_func
        res.__name__ = res.__qualname__ = 'test_' + test_func
        return res.test

@pytest.mark.asyncio
async def test_irc_send():
    test = IRCQuoteWrapper.make_test('send')
    assert (await test('a')) == ('a', None)
    assert (await test('a', 'Hello world!', 'b')) == ('a Hello\xa0world! :b', None)
    assert (await test('', 'abc def\r\n', ':ghi', ':jkl', tags={'a': 'b'}) ==
            ('\xa0 abc\xa0def\xa0\xa0 \u0703ghi ::jkl', {'a': 'b'}))

irc_msg_funcs = {
    'msg': 'PRIVMSG {} :{}',
    'notice': 'NOTICE {} :{}',
    'ctcp': 'PRIVMSG {} :\x01{}\x01',
    'me': 'PRIVMSG {} :\x01ACTION {}\x01'
}

@pytest.mark.asyncio
async def test_irc_msg_funcs():
    for func, fmt in irc_msg_funcs.items():
        test = IRCQuoteWrapper.make_test(func)
        assert (await test('abc', ':def')) == (fmt.format('abc', ':def'), None)
        assert (await test('target', 'hello', 'world', tags={'abc': 'def'}) ==
            (fmt.format('target', 'hello world'), {'abc': 'def'}))

def test_change_parser():
    irc = DummyIRC()
    assert irc._parse == miniirc.ircv3_message_parser
    def f(msg):
        ...
    irc.change_parser(f)
    assert irc._parse == f

def test_get_ca_certs():
    certs = miniirc.get_ca_certs()
    # Either None if certifi not installed, or a path to a CA bundle
    assert certs is None or isinstance(certs, str)
