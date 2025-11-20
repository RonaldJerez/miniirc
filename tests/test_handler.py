import miniirc
import pytest
import asyncio
from miniirc import IRCMessage, Hostmask


class DummyIRC(miniirc.IRC):
    def __init__(self):
        super().__init__('localhost', 6697, 'tester')
        loop = asyncio.get_event_loop()
        self._loop = loop


def verify_handler(event):
    handlers = miniirc.handle.getHandlers()
    handler = handlers[event][-1]
    assert handler.awaitable


def test_adding_handlers():
    try:
        tmp, miniirc.handle.handlers = miniirc.handle.handlers, {}

        @miniirc.handle('test', '1')
        async def f(irc, msg): ...

        verify_handler('TEST')
        verify_handler('1')

        expected = {
            'TEST': [f],
            '1': [f],
        }

        assert miniirc.handle.handlers.keys() == expected.keys()

    finally:
        miniirc.handle.handlers = tmp


def test_handler_signatures():
    try:
        tmp, miniirc.handle.handlers = miniirc.handle.handlers, {}

        # Test simple handler with no args
        @miniirc.handle('TEST1')
        async def handler1(): ...

        handler = miniirc.handle.handlers['TEST1'][-1]
        assert handler.params_count == 0

        # Test handler with single parameter
        @miniirc.handle('TEST2')
        async def handler2(irc): ...

        handler = miniirc.handle.handlers['TEST2'][-1]
        assert handler.params_count == 1

        # Test handler with all parameters
        @miniirc.handle('TEST3')
        async def handler4(irc, msg): ...

        handler = miniirc.handle.handlers['TEST3'][-1]
        assert handler.params_count == 2

        # should raise if too many params
        with pytest.raises(TypeError):

            @miniirc.handle('TEST6')
            async def handler_wrong3(irc, msg, tt): ...

    finally:
        miniirc.handle.handlers = tmp


@pytest.mark.asyncio
async def test_handler_execution():
    irc = DummyIRC()
    results = []

    @irc.handle('TEST')
    async def handler1(irc, msg):
        results.append(('handler1', msg.args))

    @irc.handle('TEST')
    async def handler2(irc, msg):
        results.append(('handler2', msg.command, msg.args))

    @irc.handle('TEST')
    async def handler3(irc, msg):
        results.append(('handler3', msg.command, msg.hostmask, msg.tags, msg.args))

    msg = IRCMessage('TEST', Hostmask('nick', 'user', 'host'), {'tag': 'value'}, ['arg1', 'arg2'])
    msg.handle(irc)

    # await for fire/forget handle_msg
    await asyncio.sleep(0.01)

    assert results == [
        ('handler1', ['arg1', 'arg2']),
        ('handler2', 'TEST', ['arg1', 'arg2']),
        ('handler3', 'TEST', Hostmask('nick', 'user', 'host'), {'tag': 'value'}, ['arg1', 'arg2']),
    ]


@pytest.mark.asyncio
async def test_ctcp_handlers():
    irc = DummyIRC()
    called = {'PRIVMSG': 0, 'CTCP': 0}

    @irc.handle('PRIVMSG', 'CTCP VERSION', 'CTCP ACTION')
    async def handle_all(irc, msg):
        command = msg.command.split(' ', 1)[0]
        called[command] += 1

    reg_msg = IRCMessage('PRIVMSG', Hostmask(), {}, ['arg1', 'arg2'])
    ctcp_msg1 = reg_msg._replace(args=['#chan', '\x01VERSION\x01'])
    ctcp_msg2 = reg_msg._replace(args=['#chan', '\x01ACTION jumping\x01'])

    assert called['PRIVMSG'] == 0
    assert called['CTCP'] == 0

    reg_msg.handle(irc)
    await asyncio.sleep(0)
    assert called['PRIVMSG'] == 1
    assert called['CTCP'] == 0

    ctcp_msg1.handle(irc)
    await asyncio.sleep(0)
    assert called['PRIVMSG'] == 1
    assert called['CTCP'] == 1

    ctcp_msg2.handle(irc)
    await asyncio.sleep(0.0)
    assert called['PRIVMSG'] == 1
    assert called['CTCP'] == 2


@pytest.mark.asyncio
async def test_concurrency():
    irc = DummyIRC()
    completion_order = []

    @irc.handle('CUSTOM')
    async def handle_all(irc, msg):
        name, timer = msg.args
        await asyncio.sleep(timer)
        completion_order.append(name)

    msg1 = IRCMessage('CUSTOM', Hostmask(), {}, ['1st', 0.1])
    msg2 = IRCMessage('CUSTOM', Hostmask(), {}, ['2nd', 0.2])
    msg3 = IRCMessage('CUSTOM', Hostmask(), {}, ['3rd', 0.3])

    msg2.handle(irc)
    msg3.handle(irc)
    msg1.handle(irc)

    # wait for messages to complete since they are fire/forget
    await asyncio.sleep(0.4)

    assert completion_order == ['1st', '2nd', '3rd']
