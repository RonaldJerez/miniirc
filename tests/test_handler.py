import miniirc
import pytest
from miniirc import IRCMessage, Hostmask

def verify_handler(event):
    handler = miniirc._global_handlers[event][-1]
    assert handler.awaitable

def test_Handler():
    try:
        tmp, miniirc._global_handlers = miniirc._global_handlers, {}
        
        @miniirc.Handler('test', '1')
        async def f(irc, msg):
            ...
        verify_handler('TEST')
        verify_handler('1')

        expected = {
            'TEST': [f],
            '1': [f],
        }

        assert miniirc._global_handlers.keys() == expected.keys()

    finally:
        miniirc._global_handlers = tmp

def test_handler_signatures():
    try:
        tmp, miniirc._global_handlers = miniirc._global_handlers, {}

        # Test simple handler with no args
        @miniirc.Handler('TEST1')
        async def handler1(): ...
        handler = miniirc._global_handlers['TEST1'][-1]
        assert handler.params_count == 0
        
        # Test handler with single parameter
        @miniirc.Handler('TEST2')
        async def handler2(irc): ...
        handler = miniirc._global_handlers['TEST2'][-1]
        assert handler.params_count == 1

        # Test handler with all parameters
        @miniirc.Handler('TEST3')
        async def handler4(irc, msg): ...
        handler = miniirc._global_handlers['TEST3'][-1]
        assert handler.params_count == 2


        # should raise if too many params
        with pytest.raises(TypeError):
            @miniirc.Handler('TEST6')
            async def handler_wrong3(irc, msg, tt): ...

    finally:
        miniirc._global_handlers = tmp

@pytest.mark.asyncio
async def test_handler_execution():
    irc = miniirc.IRC(ip='', port=0, nick='', auto_connect=False)
    results = []

    @irc.Handler('TEST')
    async def handler1(irc, msg):
        results.append(('handler1', msg.args))

    @irc.Handler('TEST')
    async def handler2(irc, msg):
        results.append(('handler2', msg.command, msg.args))

    @irc.Handler('TEST')
    async def handler3(irc, msg):
        results.append(('handler3', msg.command, msg.hostmask, msg.tags, msg.args))

    msg = IRCMessage('TEST', Hostmask('nick', 'user', 'host'), {'tag': 'value'}, ['arg1', 'arg2'])
    await irc.handle_msg(msg)

    assert results == [
        ('handler1', ['arg1', 'arg2']),
        ('handler2', 'TEST', ['arg1', 'arg2']),
        ('handler3', 'TEST', Hostmask('nick', 'user', 'host'), {'tag': 'value'}, ['arg1', 'arg2'])
    ]
