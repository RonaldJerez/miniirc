import miniirc
import pytest
from miniirc import IRCMessage, Hostmask

def verify_handler(event):
    handler = miniirc._global_handlers[event][-1]
    assert handler.awaitable
    assert hasattr(handler, 'params')

def test_Handler():
    try:
        tmp, miniirc._global_handlers = miniirc._global_handlers, {}
        
        @miniirc.Handler('test', '1')
        async def f(irc, *, command, args):
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

        # Test simple handler with only args
        @miniirc.Handler('TEST1')
        async def handler1(irc, args): ...
        handler = miniirc._global_handlers['TEST1'][-1]
        assert len(handler.params) == 1
        
        # Test handler with command parameter
        @miniirc.Handler('TEST2')
        async def handler2(irc, command, tags): ...
        handler = miniirc._global_handlers['TEST2'][-1]
        assert len(handler.params) == 2

        # Test handler with all parameters
        @miniirc.Handler('TEST3')
        async def handler4(irc, command, hostmask, tags, args): ...
        handler = miniirc._global_handlers['TEST3'][-1]
        assert len(handler.params) == 4

        # Test wrong handler (invalid test2 parameter)
        with pytest.raises(TypeError):
            @miniirc.Handler('TEST4')
            async def handler_wrong(irc, command, args, test2): ...
        
        # Test wrong parameters *args, **kwargs
        with pytest.raises(TypeError):
            @miniirc.Handler('TEST5')
            async def handler_wrong2(irc, *args): ...

        with pytest.raises(TypeError):
            @miniirc.Handler('TEST6')
            async def handler_wrong3(irc, command, **kwargs): ...

    finally:
        miniirc._global_handlers = tmp

@pytest.mark.asyncio
async def test_handler_execution():
    irc = miniirc.IRC(ip='', port=0, nick='', auto_connect=False)
    results = []

    @irc.Handler('TEST')
    async def handler1(irc, args):
        results.append(('handler1', args))

    @irc.Handler('TEST')
    async def handler2(irc, command, args):
        results.append(('handler2', command, args))

    @irc.Handler('TEST')
    async def handler3(irc, command, hostmask, tags, args):
        results.append(('handler3', command, hostmask, tags, args))

    msg = IRCMessage('TEST', Hostmask('nick', 'user', 'host'), {'tag': 'value'}, ['arg1', 'arg2'])
    await irc.handle_msg(msg)

    assert results == [
        ('handler1', ['arg1', 'arg2']),
        ('handler2', 'TEST', ['arg1', 'arg2']),
        ('handler3', 'TEST', Hostmask('nick', 'user', 'host'), {'tag': 'value'}, ['arg1', 'arg2'])
    ]
