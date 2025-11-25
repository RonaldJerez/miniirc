import pytest
import asyncio
from miniirc import IRC, IRCMessage, Hostmask, Handler


class DummyIRC(IRC):
    def __init__(self):
        super().__init__('localhost', 6697, 'tester')
        loop = asyncio.get_event_loop()
        self._loop = loop


def verify_is_handler(container, event):
    handlers = container.handle.getHandlers()

    for ev, handler_list in handlers.items():
        assert ev == ev.upper()
        for handler in handler_list:
            assert isinstance(handler, Handler)


def test_adding_handlers():
    # global IRC handlers
    @IRC.handle('global_event1', 'global_event2')
    async def f(irc, msg): ...
    verify_is_handler(IRC, 'global_event1')
    verify_is_handler(IRC, 'global_event2')

    # subclass handlers
    @DummyIRC.handle('subclass_event1', 'subclass_event2')
    async def e(irc, msg): ... 
    verify_is_handler(DummyIRC, 'subclass_event1')
    verify_is_handler(DummyIRC, 'subclass_event2')

    # instance handlers
    bot_instance = DummyIRC()
    
    @bot_instance.handle('instance_event1', 'instance_event2')
    async def h(irc, msg): ...
    verify_is_handler(bot_instance, 'instance_event1')
    verify_is_handler(bot_instance, 'instance_event2')

    # get just the keys for assertion
    global_handlers = set(sorted(IRC.handle.getHandlers().keys()))
    subclass_handlers = set(sorted(DummyIRC.handle.getHandlers().keys()))
    instance_handlers = set(sorted(bot_instance.handle.getHandlers().keys()))

    assert not subclass_handlers.issubset(global_handlers)
    assert not instance_handlers.issubset(subclass_handlers)
    assert not instance_handlers.issubset(global_handlers)

    assert bot_instance._get_combined_handlers().keys() == global_handlers | subclass_handlers | instance_handlers


def test_handler_signatures():
    try:
        tmp, IRC.handle.handlers = IRC.handle.handlers, {}
        # Test simple handler with no args
        @IRC.handle('TEST1')
        async def handler1(): ...

        handler = IRC.handle.handlers['TEST1'][-1]
        assert handler.params_count == 0

        # Test handler with single parameter
        @IRC.handle('TEST2')
        async def handler2(irc): ...

        handler = IRC.handle.handlers['TEST2'][-1]
        assert handler.params_count == 1

        # Test handler with all parameters
        @IRC.handle('TEST3')
        async def handler4(irc, msg): ...

        handler = IRC.handle.handlers['TEST3'][-1]
        assert handler.params_count == 2

        # should raise if too many params
        with pytest.raises(TypeError):

            @IRC.handle('TEST6')
            async def handler_wrong3(irc, msg, tt): ...

    finally:
        IRC.handle.handlers = tmp

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

    msg1 = IRCMessage('CUSTOM', Hostmask(), {}, ['1st', 0.001])
    msg2 = IRCMessage('CUSTOM', Hostmask(), {}, ['2nd', 0.002])
    msg3 = IRCMessage('CUSTOM', Hostmask(), {}, ['3rd', 0.003])

    msg2.handle(irc)
    msg3.handle(irc)
    msg1.handle(irc)

    # wait for messages to complete since they are fire/forget
    await asyncio.sleep(0.004)

    assert completion_order == ['1st', '2nd', '3rd']


@pytest.mark.asyncio
async def test_handler_inheritance():
    """Test that instance handlers execute along with class handlers."""
    irc = DummyIRC()
    results = []

    # Add a global-level handler to IRC
    @IRC.handle('MULTI')
    async def class_handler(irc, msg):
        results.append('global')

    # Add a class-level handler to IRC
    @DummyIRC.handle('MULTI')
    async def class_handler(irc, msg):
        results.append('class')

    # Add an instance-level handler
    @irc.handle('MULTI')
    async def instance_handler(irc, msg):
        results.append('instance')

    msg = IRCMessage('MULTI', Hostmask(), {}, [])
    msg.handle(irc)

    await asyncio.sleep(0.01)

    # Both handlers should have been called
    assert 'global' in results
    assert 'class' in results
    assert 'instance' in results
