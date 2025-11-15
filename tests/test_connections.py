import ssl
import asyncio
import logging
import pytest
import miniirc
import os

script_dir = os.path.dirname(__file__)

# to be used to speed up tests by mocking asyncio.sleep
async def mock_sleep(delay): ...

@pytest.fixture
async def custom_irc_server():
    servers = []

    async def start_server_with_responses(responses, *, ssl=None):
        async def client_handler(reader, writer):
            while True:
                line = await reader.readline()
                line = line.decode('utf-8').rstrip('\r\n')

                if line.startswith('QUIT'):
                    break

                if line not in responses:
                    logging.error(f'Received unexpected line: {line}')
                    break

                response = responses[line]
                if not response: continue

                for resp_line in response.split('\n'):
                    writer.write((resp_line + '\r\n').encode('utf-8'))
                    await writer.drain()
                    
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(client_handler, 'localhost', 0, ssl=ssl)
        servers.append(server)
        try:
            _, port, *rest = server.sockets[0].getsockname()
            return port
        except Exception as e:
            raise e

    yield start_server_with_responses

    for server in servers:
        server.close()
        await server.wait_closed()


class DummyIRC(miniirc.IRC):
    def __init__(self, port, **kwargs):
        persist = kwargs.pop('persist', False)
        super().__init__('localhost', port, 'tester', persist=persist, **kwargs)


base_exchange: dict = {
    'CAP LS 302': '',
    'USER tester 0 * :tester': '',
    'NICK tester': (
        '001 * arg1 arg2 :text message with space\n'
        '005 * NETWORK=Net NICKLEN=35 :are supported by this server'
    ),
}

ircv3_exchange = {
    'CAP LS 302': 'CAP * LS :abc sasl account-tag',
    'USER tester 0 * :tester': '',
    'NICK tester': '',
    'CAP REQ :account-tag sasl': 'CAP * ACK :sasl account-tag',
    'CAP REQ :sasl account-tag': 'CAP * ACK :account-tag sasl',
    'AUTHENTICATE PLAIN': 'AUTHENTICATE +',
    'AUTHENTICATE dGVzdGVyAHRlc3RlcgBodW50ZXIy': '903',
    'CAP END': (
        '001 * arg :welcome to the test server\n'
        '005 * BOT :are supported by this server\n'
    )
}

@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore::UserWarning")
async def test_basic_ssl_connection(custom_irc_server):
    server_ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_ssl_ctx.load_cert_chain(certfile=os.path.join(script_dir, "server.crt"), keyfile=os.path.join(script_dir, "server.key"))

    client_ssl_ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    client_ssl_ctx.load_verify_locations(cafile=os.path.join(script_dir, "server.crt")) # Trust the self-signed server certificate
    
    port = await custom_irc_server(base_exchange, ssl=server_ssl_ctx)
    irc = DummyIRC(port, ssl=client_ssl_ctx, verify_ssl=False)  
    handled = { '001': 0, '005': 0 }

    @irc.Handler('001')
    async def _handle_001(irc, msg):
        handled[msg.command] += 1
        assert msg.args == ['*', 'arg1', 'arg2', 'text message with space']

    @irc.Handler('005')
    async def _handle_005(irc, msg):
        handled[msg.command] += 1
        await irc.send('QUIT')

    await irc.connect()
    assert irc.isupport == {'NETWORK': 'Net', 'NICKLEN': 35}
    assert handled == {'001': 1, '005': 1}


@pytest.mark.asyncio
async def test_multi_isupport(custom_irc_server):
    responses = {
        **base_exchange,
        'USER tester 0 * :tester': 'PING :test',
        'PONG :test': '005 * ANOTHER=Val INVALID_LEN=a35 :are supported by this server'
    }

    port = await custom_irc_server(responses)
    irc = DummyIRC(port)

    # state machine for how many isupport received
    state = {'count': 0}

    @irc.Handler('005')
    async def _handle_005(irc, msg):
        state['count'] += 1

        # only proceed on the second 005
        if state['count'] < 2: return
        
        await irc.send('QUIT')

    await irc.connect()
    assert irc.isupport == {'NETWORK': 'Net', 'NICKLEN': 35, 'ANOTHER': 'Val'}
    assert state['count'] == 2


@pytest.mark.asyncio
async def test_sasl(custom_irc_server):
    port = await custom_irc_server(ircv3_exchange)
    irc = DummyIRC(port, password='hunter2')

    @irc.Handler('005')
    async def _handle_005(irc):
        await irc.send('QUIT')

    await irc.connect()
    assert irc.username == 'tester'
    assert irc.current_nick == 'tester'
    assert 'BOT' in irc.isupport
    

@pytest.mark.asyncio
async def test_reconnect_attempts(caplog, monkeypatch):
    monkeypatch.setattr('asyncio.sleep', mock_sleep)
  
    # TODO use logic to find an actual used port
    irc = DummyIRC(7890, max_reconnect_attempts=3, persist=True)    
    handled = { '001': 0 }

    @irc.Handler('001')
    async def _handle_001(irc, msg):
        handled[msg.command] += 1
        await irc.send('QUIT')

    await irc.connect()
    assert 'Failed to connect after 3 attempts' in caplog.text


@pytest.mark.asyncio
async def test_reconnecting(custom_irc_server, monkeypatch):
    monkeypatch.setattr('asyncio.sleep', mock_sleep)

    port = await custom_irc_server(base_exchange)
    irc = DummyIRC(port, max_reconnect_attempts=3, persist=True)    
    handled = { '001': 0 }

    @irc.Handler('001')
    async def _handle_001(irc, msg):
        handled[msg.command] += 1

        # allow to test to quit after 3 successful reconnections
        if handled[msg.command] > 2:
            irc.persist = False

        await irc.send('QUIT')

    await irc.connect()
    assert handled == {'001': 3}

@pytest.mark.asyncio
async def test_wait_until_disconnected(custom_irc_server, monkeypatch):
    monkeypatch.setattr('asyncio.sleep', mock_sleep)

    port = await custom_irc_server(base_exchange)
    bot1 = DummyIRC(port)
    bot2 = DummyIRC(port)

    handled = { '001': 0 }

    @miniirc.Handler('001')
    async def _handle_001(irc, msg):
        handled[msg.command] += 1
        await irc.send('QUIT')

    asyncio.create_task(bot1.connect())
    asyncio.create_task(bot2.connect())

    await asyncio.gather(bot1.wait_until_disconnected(), bot2.wait_until_disconnected())
    assert handled == {'001': 2}


@pytest.mark.asyncio
async def test_invalid_nickname(custom_irc_server):
    responses = {
        **base_exchange,
        'NICK tester': '433',
        'NICK tester_': (
            '001 * arg1 arg2 :text message with space\n'
            '005 * NETWORK=Net NICKLEN=35 :are supported by this server'
        ),
    }
    port = await custom_irc_server(responses)
    irc = DummyIRC(port)    

    @irc.Handler('005')
    async def _handle_005(irc, msg):
        await irc.send('QUIT')

    await irc.connect()
    assert irc.current_nick == 'tester_'




# TODO test handled commands

