import re
import pytest
import miniirc
import collections
import pathlib
from miniirc import IRCMessage, Hostmask


class DummyIRC(miniirc.IRC):
    def __init__(self, ip='', port=0, nick='a', *args, **kwargs):
        super().__init__(ip, port, nick, *args, **kwargs)


def test_message_parser():
    irc = DummyIRC()
    p = irc.message_parser
    for i in range(4):
        hostmask = Hostmask(*('n', 'u', 'h')[:i])
        hostmask_s = ':n!u@h'[: i * 2] + (' ' if i else '')
        assert p(hostmask_s + 'PRIVMSG #channel :Hello world!') == IRCMessage(
            'PRIVMSG', hostmask, {}, ['#channel', 'Hello world!']
        )

    hostmask = Hostmask()
    assert p(r'@tag1=value\:\swith\s\\spaces\rand\nnewlines;tag2;tag3= Hi') == (
        'Hi',
        hostmask,
        {'tag1': 'value; with \\spaces\rand\nnewlines', 'tag2': True, 'tag3': ''},
        [],
    )


def test_version():
    pyproject_toml = pathlib.Path(__file__).resolve().parent.parent / 'pyproject.toml'
    with pyproject_toml.open() as f:
        match = re.search(r"version *= [\"']([0-9\.a-z]+)[\"']", f.read())
    assert match
    assert miniirc.__version__ == match.group(1)

    assert '.'.join(map(str, miniirc.ver[:3])) + ''.join(miniirc.ver[3:]) == miniirc.__version__
    assert miniirc.version == 'miniirc IRC framework v' + miniirc.__version__


def test_dict_to_tags():
    dict_to_tags = miniirc._dict_to_tags
    tags_dict = collections.OrderedDict((('abc', True), ('def', False), ('ghi', ''), ('jkl', 'test\r\n; ')))
    assert dict_to_tags(tags_dict) == rb'@abc;jkl=test\r\n\:\s '


class IRCQuoteWrapper(DummyIRC):
    res: tuple | None = None
    TEST_FUNC = 'send'

    def send(self, *args, force=None, tags=None):
        assert self.res is None
        self.res = (' '.join(args), tags)

    @classmethod
    async def test(cls, *args, **kwargs):
        self = cls()
        getattr(self, cls.TEST_FUNC)(*args, **kwargs)
        return self.res

    @classmethod
    def make_test(cls, test_func):
        class res(cls):
            TEST_FUNC = test_func

        res.__name__ = res.__qualname__ = 'test_' + test_func
        return res.test


irc_msg_funcs = {
    'msg': 'PRIVMSG {} :{}',
    'notice': 'NOTICE {} :{}',
    'ctcp': 'PRIVMSG {} :\x01{}\x01',
    'me': 'PRIVMSG {} :\x01ACTION {}\x01',
}


@pytest.mark.asyncio
async def test_irc_msg_funcs():
    for func, fmt in irc_msg_funcs.items():
        test = IRCQuoteWrapper.make_test(func)
        assert (await test('abc', ':def')) == (fmt.format('abc', ':def'), None)
        assert await test('target', 'hello world', tags={'abc': 'def'}) == (
            fmt.format('target', 'hello world'),
            {'abc': 'def'},
        )


def test_get_ca_certs():
    certs = miniirc.get_ca_certs()
    # Either None if certifi not installed, or a path to a CA bundle
    assert certs is None or isinstance(certs, str)
