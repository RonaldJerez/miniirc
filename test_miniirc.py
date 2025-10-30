#!/bin/false
import asyncio
import collections
import miniirc
import pathlib
import pytest
import re
from miniirc import IRCMessage

def fill_in_hostmask(cmd, hostmask):
    while len(hostmask) < 3:
        hostmask += ('',)
    return hostmask[:3]

def test_fill_in_hostmask():
    assert fill_in_hostmask('A', ()) == ('', '', '')
    assert fill_in_hostmask('A', ('B',)) == ('B', '', '')
    assert fill_in_hostmask('A', ('B', 'C')) == ('B', 'C', '')
    assert fill_in_hostmask('A', ('B', 'C', 'D')) == ('B', 'C', 'D')

def test_message_parser():
    p = miniirc.ircv3_message_parser
    for i in range(4):
        hostmask = fill_in_hostmask('PRIVMSG', ('n', 'u', 'h')[:i])
        hostmask_s = ':n!u@h'[:i * 2] + (' ' if i else '')
        assert (p(hostmask_s + 'PRIVMSG #channel :Hello world!') ==
                IRCMessage('PRIVMSG', hostmask, {},
                            ['#channel', 'Hello world!']))

    hostmask = fill_in_hostmask('Hi', ())
    empty_tag = ''
    assert (p(r'@tag1=value\:\swith\s\\spaces\rand\nnewlines;tag2;tag3= Hi') ==
            ('HI', hostmask,
             {'tag1': 'value; with \\spaces\rand\nnewlines', 'tag2': empty_tag,
              'tag3': empty_tag}, []))

def verify_handler(event, cmdhandler, colon, ircv3):
    handler = miniirc._global_handlers[event][-1]
    assert handler.cmdhandler == cmdhandler
    assert not colon
    assert handler.ircv3 == ircv3
    assert not handler.awaitable


def test_Handler(monkeypatch):
    try:
        tmp, miniirc._global_handlers = miniirc._global_handlers, {}
        @miniirc.Handler('test', 1, ircv3=True, colon=False)
        def f(irc, hostmask, tags, args):
            ...
        verify_handler('TEST', False, False, True)

        @miniirc.CmdHandler()
        def f3(irc, command, hostmask, args):
            ...
        verify_handler(None, True, False, False)

        expected = {
            'TEST': [f],
            '1': [f],
            None: [f3]
        }

        assert miniirc._global_handlers.keys() == expected.keys()

    finally:
        miniirc._global_handlers = tmp

def test_version():
    setup_py = pathlib.Path(__file__).resolve().parent / 'setup.py'
    with setup_py.open() as f:
        match = re.search(r"version *= '([0-9\.a-z]+)',", f.read())
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
    assert dict_to_tags(tags_dict) == rb'@abc;ghi;jkl=test\r\n\:\s '

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
    res = None
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
            (' abc\xa0def\xa0\xa0 \u0703ghi ::jkl', {'a': 'b'}))

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

@pytest.mark.asyncio
async def test_connection():
    irc = None

    async def handle_client(reader, writer):
        fixed_responses = {
            'CAP LS 302': 'CAP * LS :abc sasl account-tag',
            'CAP REQ :account-tag sasl': 'CAP miniirc-test ACK :sasl account-tag',
            'CAP REQ :sasl account-tag': 'CAP miniirc-test ACK :account-tag sasl',
            'AUTHENTICATE PLAIN': 'AUTHENTICATE +',
            'AUTHENTICATE dGVzdAB0ZXN0AGh1bnRlcjI=': '903',
            'CAP END': (
                '001 miniirc-test_ parameter test :with colon\n'
                '005 * CAP=END :isupport description\n'
            ),
            'USER miniirc-test 0 * :miniirc-test':
                ':a PRIVMSG miniirc-test :\x01VERSION\x01',
            'NICK miniirc-test': '433',
            'NICK :miniirc-test': '433',
            'NICK miniirc-test_': '',
            'NOTICE a :\x01VERSION ' + miniirc.version + '\x01':
                '005 miniirc-test CTCP=VERSION :are supported by this server',
            'QUIT :I grew sick and died.': '',
        }

        line = None
        while line != 'SUCCESS':
            line = await reader.readline()
            line = line.decode('utf-8').rstrip('\r\n')
            assert line in fixed_responses

            response = fixed_responses[line]
            for resp_line in response.split('\n'):
                writer.write((resp_line + '\r\n').encode('utf-8'))
                await writer.drain()

        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, '127.0.0.1', 0)
    ip, port = server.sockets[0].getsockname()

    try:
        irc = miniirc.IRC(ip, port, 'miniirc-test', auto_connect=False,
            ns_identity=('test', 'hunter2'), persist=False, debug=True)
        assert irc.connected is None

        @irc.Handler('001')
        async def _handle_001(irc, hostmask, args):
            assert args == ['miniirc-test_', 'parameter', 'test', 'with colon']

        state = {'count': 0}
        
        @irc.Handler('005')
        async def _handle_005(irc, hostmask, args):
            state['count'] = state['count'] + 1
            if state['count'] < 2: return
            
            assert irc.isupport == {'CTCP': 'VERSION', 'CAP': 'END'}
            await irc.send('SUCCESS')

        await irc.connect()

        assert irc.nick == 'miniirc-test'
        assert irc.current_nick == 'miniirc-test_'

    finally:
        await irc.disconnect()
        server.close()
        await server.wait_closed()

    await irc.wait_until_disconnected()

if __name__ == '__main__':
    pytest.main([__file__])