import asyncio
import miniirc
import pytest

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
        async def _handle_001(irc, msg):
            assert msg.args == ['miniirc-test_', 'parameter', 'test', 'with colon']

        state = {'count': 0}
        
        @irc.Handler('005')
        async def _handle_005(irc):
            state['count'] = state['count'] + 1
            if state['count'] < 2:
                return
            
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
