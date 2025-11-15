#!/usr/bin/python3
#
# miniirc - A small-ish IRC framework.
#
# © 2018-2022 by luk3yx and other contributors of miniirc.
#

import asyncio
import re
import ssl
import warnings
import inspect
import logging
from typing import NamedTuple
from base64 import b64encode

logger = logging.getLogger(__name__)

# The version string and tuple
ver = __version_info__ = (2, 0, 0, 'a9')
version = 'miniirc IRC framework v2.0.0a9'
__version__ = '2.0.0a9'

# __all__ and _default_caps
__all__ = ['Handler', 'IRC', 'IRCMessage', 'Hostmask', 'register_numerics']
_default_caps = {
    'account-notify',
    'account-tag',
    'away-notify',
    'cap-notify',
    'chghost',
    'extended-join',
    'invite-notify',
    'message-tags',
    'server-time',
    'sts',
}

# Get the certificate list.
try:
    from certifi import where as get_ca_certs  # type: ignore
except ImportError:

    def get_ca_certs():
        pass


# Included numerics that are used internally to keep library lightweight
_IRC_NUMERICS = {
    'RPL_WELCOME': '001',
    'RPL_ISUPPORT': '005',
    'ERR_ERRONEUSNICKNAME': '432',
    'ERR_NICKNAMEINUSE': '433',
    'ERR_NICKLOCKED': '902',
    'RPL_SASLSUCCESS': '903',
    'ERR_SASLFAIL': '904',
    'ERR_SASLABORTED': '905',
}


# Allow consumers to register additional numeric mappings
def register_numerics(numerics):
    """
    Register additional IRC numeric replies.
    """
    _IRC_NUMERICS.update(numerics)


def _event_name_to_numeric(event):
    """Convert event name to its numeric value if applicable"""
    if event is None:
        return None
    event = str(event).upper()
    return _IRC_NUMERICS.get(event, event)


# Create global handlers
_global_handlers = {}


class _Handler:
    """Internal handler wrapper for IRC event callbacks."""
    __slots__ = ('func', 'awaitable', 'params_count')

    def __init__(self, func):
        self.func = func
        self.awaitable = asyncio.iscoroutinefunction(func)

        signature = inspect.signature(func)
        self.params_count = len(signature.parameters.keys())

        if self.params_count > 2:
            raise TypeError(f'Handler only accepts 2 params, got {self.params_count}')


def _add_handler(handlers, events):
    """Decorator to add a handler for one or more IRC events."""
    if not events:
        raise TypeError('Handler() called without arguments.')

    def add_handler(func):
        handler = _Handler(func)
        for event in events:
            event = _event_name_to_numeric(event)
            if event not in handlers:
                handlers[event] = []
            if handler not in handlers[event]:
                handlers[event].append(handler)
        return func

    return add_handler


def Handler(*events):
    """Decorator to register a global handler for IRC events."""
    return _add_handler(_global_handlers, events)


# Parse IRCv3 tags
_ircv3_tag_escapes = {':': ';', 's': ' ', 'r': '\r', 'n': '\n'}


def _tag_list_to_dict(tag_list):
    """Convert a list of IRCv3 tag strings to a dictionary."""
    
    tags = {}
    for tag in tag_list:
        tag = tag.split('=', 1)
        if len(tag) == 1:
            tags[tag[0]] = ''
        elif len(tag) == 2:
            if '\\' in tag[1]:  # Iteration is bad, only do it if required.
                value = ''
                escape = False
                for char in tag[1]:  # TODO: Remove this iteration.
                    if escape:
                        value += _ircv3_tag_escapes.get(char, char)
                        escape = False
                    elif char == '\\':
                        escape = True
                    else:
                        value += char
            else:
                value = tag[1]
            tags[tag[0]] = value

    return tags


# Create the IRCv2/3 parser
class Hostmask(NamedTuple):
    """Represents an IRC hostmask (nick!user@host)."""
    nick: str = ''
    user: str = ''
    host: str = ''


class IRCMessage(NamedTuple):
    """Represents a parsed IRC message."""
    command: str
    hostmask: Hostmask = Hostmask()
    tags: dict | None = None
    args: list | None = None

    def sub_command(self, prefix):
        """
        Creates a new message with sub-commands from the current message.

        Example:
            msg = IRCMessage('PRIVMSG', ..., args=['#chan', '\x01ACTION waves\x01'])
            sub = msg.sub_command('CTCP')
            # sub.command == 'CTCP ACTION'
            # sub.args == ['#chan', 'waves']
        """
        target, text = self.args

        if text.startswith('\x01') and text.endswith('\x01'):
            text = text[1:-1]

        if text == '':
            return None

        sub_command, *new_args = text.split(' ', 1)
        new_command = f'{prefix} {sub_command}'

        new_args.insert(0, target)

        return self._replace(command=new_command, args=new_args)


_msg_re = re.compile(
    r'^'
    r'(?:@([^ ]*) )?'  # Tags
    r'(?::([^!@ ]*)(?:!([^@ ]*))?(?:@([^ ]*))? )?'  # Hostmask
    r'([^@: ][^ ]*)(?: (.*?))??(?: :(.*))?'  # Command and arguments
    r'$'
)


def ircv3_message_parser(msg):
    """Parse a raw IRC message string into an IRCMessage object."""
    match = _msg_re.match(msg)
    if not match:
        return

    # Process IRCv3 tags
    raw_tags = match.group(1)
    tags = {} if raw_tags is None else _tag_list_to_dict(raw_tags.split(';'))

    # Process arguments
    hostmask = Hostmask(*match.groups('')[1:4])
    cmd = match.group(5)

    # Get the command and arguments
    raw_args = match.group(6)
    args = [] if raw_args is None else raw_args.split(' ')

    trailing = match.group(7)
    if trailing:
        args.append(trailing)

    # Return the parsed data
    return IRCMessage(cmd, hostmask, tags, args)


def _escape_tag(tag):
    """Escape a tag value for IRCv3 message tags."""
    tag = str(tag).replace('\\', '\\\\')
    for i in _ircv3_tag_escapes:
        tag = tag.replace(_ircv3_tag_escapes[i], '\\' + i)
    return tag


def _dict_to_tags(tags):
    """Convert a dictionary of tags to an IRCv3 tag string."""
    res = b'@'
    for tag, value in tags.items():
        if value and value != '':
            etag = _escape_tag(tag).replace('=', '-')
            if value and isinstance(value, str):
                etag += '=' + _escape_tag(value)
            etag = (etag + ';').encode('utf-8')
            if len(res) + len(etag) > 4094:
                break
            res += etag
    if len(res) < 3:
        return b''
    return res[:-1] + b' '

class IRC:
    """An IRC client connection supporting IRCv2 and IRCv3 features."""

    connected = None
    msglen = 512
    quit_message = 'I grew sick and died.'
    _sendq = None
    _loop = None
    _sasl = False
    _unhandled_caps = None
    _combined_handlers = None
    _task = None

    def __init__(self, host, port, nick, *, 
                 channels=None,
                 username=None, realname=None, 
                 password=None, server_password=None, 
                 persist=True, ssl=None, verify_ssl=True,
                 ircv3_caps=None, connect_modes=None,
                 ping_interval=60, ping_timeout=None):
        
        # Set basic variables
        self.host = host
        self.port = int(port)
        self.nick = self.current_nick = nick
        if isinstance(channels, str):
            channels = map(str.lstrip, channels.split(','))
        self.channels = set(channels or ())
        self.username = username or nick
        self.realname = realname or nick
        self.password = password
        self.ssl = ssl
        self.persist = persist
        self.ircv3_caps = set(ircv3_caps or ()) | _default_caps
        self.active_caps = set()
        self.isupport = {}
        self.connect_modes = connect_modes
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.verify_ssl = verify_ssl
        self.server_password = server_password
        self._sendq = []

        # Add IRCv3 capabilities.
        if self.password:
            self.ircv3_caps.add('sasl')

        # Add handlers and set the default message parser
        self.change_parser()
        self._instance_handlers = {}

        # Try to detect ssl
        if ssl is None and self.port == 6697:
            self.ssl = True

    async def send(self, *msg, force=False, tags=None):
        """Send a raw IRC message by joining arguments with spaces.
        
        This is the low-level method that sends exactly what you provide.
        For formatted IRC commands with automatic trailing parameter handling,
        use command() instead.
        
        Args:
            *msg: Message components to join with spaces
            force: Send even if not connected (for connection setup)
            tags: IRCv3 message tags dictionary
        """
        str_msg = ' '.join(str(m) for m in msg)

        if not self.connected and not force:
            logger.debug(f'>Q> {str_msg}')
            if not self._sendq:
                self._sendq = []
            self._sendq.append((tags, msg))
            return

        logger.debug(f'>>> {str_msg}')
        
        # Convert to bytes
        msg_bytes = str_msg.replace('\x00', '\ufffd').encode('utf-8', errors='replace')
        msg_bytes = msg_bytes.replace(b'\r', b' ').replace(b'\n', b' ')

        # Truncate if needed
        if len(msg_bytes) + 2 > self.msglen:
            msg_bytes = msg_bytes[: self.msglen - 2]
            # Re-decode and encode to avoid splitting multi-byte characters
            msg_bytes = msg_bytes.decode('utf-8', errors='ignore').encode('utf-8')

        # Add tags if applicable
        if isinstance(tags, dict) and 'message-tags' in self.active_caps:
            msg_bytes = _dict_to_tags(tags) + msg_bytes

        msg_bytes += b'\r\n'
        
        try:
            self._writer.write(msg_bytes)
            await self._writer.drain()
        except Exception as e:
            logger.error(f'Error sending message: {e}')
            raise

    # User-friendly msg, notice, and CTCP functions.
    async def command(self, command, *args, force=False, tags=None):
        """Send a IRC command with arguments. Applying ':' to the last argument."""
        if args:
            args = list(args)
            args[-1] = ':' + str(args[-1])
        await self.send(command, *args, force=force, tags=tags)

    async def msg(self, target, msg, tags=None):
        """Send a PRIVMSG to a target."""
        await self.command('PRIVMSG', target, msg, tags=tags)

    async def notice(self, target, msg, tags=None):
        """Send a NOTICE to a target."""
        await self.command('NOTICE', target, msg, tags=tags)
        
    async def ctcp(self, target, *msg, reply=False, tags=None):
        """Send a CTCP message or reply to a target."""
        m = self.notice if reply else self.msg
        await m(target, f'\x01{" ".join(map(str, msg))}\x01', tags=tags)

    async def me(self, target, msg, tags=None):
        """Send a CTCP ACTION (/me) to a target."""
        await self.ctcp(target, 'ACTION', msg, tags=tags)

    def Handler(self, *events):
        """Register a handler for this IRC instance."""
        return _add_handler(self._instance_handlers, events)

    async def connect(self, *, loop=None):
        """Connect to the IRC server and start the main loop."""
        if self.connected is not None:
            logger.debug('Already connected!')
            return

        if loop is None:
            # Try to get existing event loop, create new one if needed
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

        self._loop = loop
        self.connected = False
        self._unhandled_caps = None
        self.current_nick = self.nick
        logger.debug('Starting main loop...')
        self._sasl = self._pinged = False

        self._task = self._loop.create_task(self._async_main())
        await self._task

    async def disconnect(self, msg=None, *, auto_reconnect=False):
        """Disconnect from the IRC server."""
        if self._loop is None:
            return

        self.persist = auto_reconnect and self.persist
        self.connected = None
        self.active_caps.clear()
        self._unhandled_caps = None
        try:
            await self.command('QUIT', msg or self.quit_message, force=True)
        except Exception:
            pass

        if hasattr(self, '_writer'):
            self._writer.close()
            await self._writer.wait_closed()

        # Cancel any running task
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info(f'Disconnected from {self.host}')

        if hasattr(self, 'on_disconnect'):
            self.on_disconnect()

    async def finish_negotiation(self, cap):
        """Finish IRCv3 capability negotiation for a given capability."""
        logger.debug(f'Capability {cap} handled')
        if self._unhandled_caps:
            cap = cap.lower()
            if cap in self._unhandled_caps:
                del self._unhandled_caps[cap]
            if len(self._unhandled_caps) < 1:
                self._unhandled_caps = None
                if not self.connected:
                    await self.send('CAP END', force=True)

    def change_parser(self, parser=ircv3_message_parser):
        """Change the message parser used for incoming messages."""
        self._parse = parser

    async def _start_handler(self, handler, msg):
        """Start a handler for a given message, running async or in executor."""
        try:
            params = (self, msg)
            if handler.awaitable:
                await handler.func(*params[: handler.params_count])
            else:
                # Run non-async handlers in the event loop's default executor
                await self._loop.run_in_executor(None, handler.func, *params[: handler.params_count])
        except Exception as e:
            logger.exception(f'Handler {handler.func.__name__} raised an exception: {e}')

    def handle_msg(self, input_msg):
        """Dispatch a parsed IRC message to registered handlers."""
        ctcp_msg = None
        handled = False
        input_command = input_msg.command.upper()

        if input_command in ('PRIVMSG', 'NOTICE') and input_msg.args:
            text = input_msg.args[-1]
            if len(text) > 2 and text.startswith('\x01') and text.endswith('\x01'):
                ctcp_msg = input_msg.sub_command('CTCP')

        msg = ctcp_msg or input_msg
        msg_command = msg.command.upper()

        # do this loop only once per instance, there shouldn't be any new handlers post init
        if self._combined_handlers is None:
            self._combined_handlers = {}
            for key in set(_global_handlers) | set(self._instance_handlers):
                self._combined_handlers[key] = _global_handlers.get(key, []) + self._instance_handlers.get(key, [])

        handlers = self._combined_handlers.get(msg_command, []) + self._combined_handlers.get(None, [])
        if len(handlers) > 0:
            handled = True
            for handler in handlers:
                asyncio.create_task(self._start_handler(handler, msg))

        return handled

    async def _handle_cap(self, cap):
        """Handle IRCv3 capability acknowledgement."""
        cap = cap.lower()
        self.active_caps.add(cap)
        if self._unhandled_caps and cap in self._unhandled_caps:
            msg = IRCMessage(f'CAP ACK {cap}', args=self._unhandled_caps[cap])
            handled = self.handle_msg(msg)
            if not handled:
                await self.finish_negotiation(cap)

    async def _send_initial_msgs(self):
        """Send initial registration and capability negotiation messages."""
        if self.server_password:
            await self.send('PASS', self.server_password, force=True)
        await self.send('CAP LS 302', force=True)
        await self.command('USER', self.username, '0 *', self.realname, force=True)
        await self.send('NICK', self.nick, force=True)

    async def _async_main(self):
        """Main loop for reading and handling IRC messages."""
        ctx = None
        if self.ssl:
            ctx = ssl.create_default_context(cafile=get_ca_certs())
            if self.verify_ssl:
                assert ctx.check_hostname
            else:
                warnings.warn('Disabling verify_ssl is usually a bad idea.')
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

        # Try to connect
        while True:
            try:
                logger.debug(f'Initializing connection to {self.host} on port {self.port}')
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port, ssl=ctx),
                    timeout=self.ping_timeout or self.ping_interval,
                )

                # Send initial messages
                await self._send_initial_msgs()
                break
            except (asyncio.TimeoutError, OSError):
                if hasattr(self, '_writer'):
                    self._writer.close()
                if not self.persist:
                    raise

                logger.debug('Failed to connect, trying again in 5 seconds.')
                await asyncio.sleep(5)

        logger.info(f'Connected to {self.host} on port {self.port}')
        while True:
            try:
                try:
                    # Use readuntil so that partial lines aren't read
                    line = await asyncio.wait_for(
                        self._reader.readuntil(b'\n'), timeout=self._pinged and self.ping_timeout or self.ping_interval
                    )
                except asyncio.TimeoutError:
                    if self._pinged:
                        raise

                    self._pinged = True
                    await self.send('PING :miniirc-ping', force=True)
                    continue

                if not line:
                    raise ConnectionAbortedError
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, OSError):
                logger.debug(f'Connection to {self.host} lost')
                # TODO: add logic to only reconnect if he have a successful initial connection (ie: after receiving RPL_WELCOME), for now disabled auto-reconnect
                await self.disconnect(auto_reconnect=False)

                if self.persist:
                    await asyncio.sleep(5)
                    logger.debug('Reconnecting...')
                    await self.connect()
                return

            line_str = line.rstrip(b'\r\n').decode('utf-8', 'replace')
            if line_str:
                if hasattr(self, 'debug_line_filter'):
                    self.debug_line_filter(line_str)
                else:
                    logger.debug(f'<<< {line_str}')

                try:
                    msg = self._parse(line_str)
                    if isinstance(msg, IRCMessage):
                        self.handle_msg(msg)
                    else:
                        logger.debug(f'Ignored message: {line_str}')
                except Exception as exc:
                    logger.error('Error handling IRC message', exc_info=exc)

    async def wait_until_disconnected(self):
        """Wait until the IRC connection is closed.

        This can be used with asyncio.gather() to wait for multiple connections:
        await asyncio.gather(irc1.wait_until_disconnected(), irc2.wait_until_disconnected())
        """
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass


# Handle some IRC messages by default.
@Handler('RPL_WELCOME')
async def _handler(irc):
    irc.connected = True
    irc.isupport.clear()
    irc._unhandled_caps = None

    logger.debug('Welcome message received!')

    if irc.connect_modes:
        await irc.send('MODE', irc.current_nick, irc.connect_modes)
    if not irc._sasl and irc.password:
        logger.debug('Logging in (no SASL, aww)...')
        await irc.msg('NickServ', 'identify', irc.password)
    if irc.channels:
        logger.debug(f'*** Joining channels... {irc.channels}')
        await irc.send('JOIN', ','.join(irc.channels))

    # Handle queued messages
    sendq, irc._sendq = irc._sendq, None
    if sendq:
        for tags, args in sendq:
            await irc.send(*args, tags=tags)


@Handler('PING')
async def _handler(irc, msg):
    await irc.command('PONG', *msg.args, force=True)


@Handler('PONG')
async def _handler(irc, msg):
    if msg.args and msg.args[-1] == 'miniirc-ping' and irc.ping_interval:
        irc._pinged = False


@Handler('ERR_ERRONEUSNICKNAME', 'ERR_NICKNAMEINUSE')
async def _handler(irc):
    if not irc.connected:
        try:
            return int(irc.nick[0])
        except (IndexError, ValueError):
            pass
        if len(irc.current_nick) >= irc.isupport.get('NICKLEN', 20):
            return
        logger.warning(f'The requested nickname {irc.current_nick} is invalid.')
        logger.warning(f'Trying again with {irc.current_nick}_')
        irc.current_nick += '_'
        await irc.send('NICK', irc.current_nick, force=True)


@Handler('NICK')
async def _handler(irc, msg):
    if msg.hostmask.nick.lower() == irc.current_nick.lower():
        irc.current_nick = msg.args[-1]


@Handler('CTCP VERSION')
async def _handler(irc, msg):
    if not version:
        return
    await irc.ctcp(msg.hostmask.nick, 'VERSION', version, reply=True)


@Handler('CAP')
async def _handler(irc, msg):
    if len(msg.args) < 3:
        return

    msg = IRCMessage(f'CAP {msg.args[1]}', msg.hostmask, args=msg.args)
    irc.handle_msg(msg)


@Handler('CAP ACK')
async def _handler(irc, msg):
    caps = msg.args[-1].split(' ')
    for cap in caps:
        await irc._handle_cap(cap)


@Handler('CAP NAK')
async def _handler(irc):
    irc._unhandled_caps = None
    await irc.send('CAP END', force=True)


@Handler('CAP LS', 'CAP NEW')
async def _handler(irc, msg):
    req = set()

    if not irc._unhandled_caps:
        irc._unhandled_caps = {}

    caps = msg.args[-1].split(' ')
    multiline = msg.args[2] == '*'

    for raw in caps:
        raw = raw.split('=', 1)
        cap = raw[0].lower()
        if cap in irc.ircv3_caps:
            irc._unhandled_caps[cap] = raw
            if cap == 'sts':
                irc._handle_cap(cap)
            else:
                req.add(cap)

    if irc.connected is None:
        return
    elif req:
        await irc.command('CAP', 'REQ', ' '.join(req), force=True)
    elif msg.command == 'CAP LS' and not irc._unhandled_caps and not multiline:
        irc._unhandled_caps = None
        await irc.send('CAP END', force=True)


@Handler('CAP DEL')
async def _handler(irc, msg):
    caps = msg.args[-1].split(' ')

    for cap in caps:
        cap = cap.lower()
        if cap in irc.active_caps:
            irc.active_caps.remove(cap)


@Handler('CAP ACK SASL')
async def _handler(irc, msg):
    sasl_options = msg.args[-1].upper().split(',')
    if irc.password and (len(msg.args) < 2 or 'PLAIN' in sasl_options):
        await irc.send('AUTHENTICATE PLAIN', force=True)
    else:
        await irc.send('AUTHENTICATE *', force=True)
        await irc.finish_negotiation('sasl')


@Handler('AUTHENTICATE')
async def _handler(irc, msg):
    if msg.args and msg.args[0] == '+':
        irc._sasl = True
        pw = f'{irc.username}\x00{irc.username}\x00{irc.password}'.encode('utf-8')
        await irc.send('AUTHENTICATE', b64encode(pw).decode('utf-8'), force=True)


@Handler('ERR_SASLFAIL', 'ERR_SASLABORTED')
async def _handler(irc):
    if irc._sasl:
        irc._sasl = False
        await irc.send('AUTHENTICATE *', force=True)


@Handler('ERR_NICKLOCKED', 'RPL_SASLSUCCESS', 'ERR_SASLFAIL', 'ERR_SASLABORTED')
async def _handler(irc):
    await irc.finish_negotiation('sasl')


# STS
@Handler('CAP ACK STS')
async def _handler(irc, msg):
    if not irc.ssl and len(msg.args) == 2:
        try:
            port = int(_tag_list_to_dict(msg.args[1].split(','))['port'])
        except (IndexError, KeyError, ValueError):
            return

        persist = irc.persist
        await irc.disconnect()
        logger.info(f'STS detected, enabling TLS/SSL and changing the port to {port}')
        irc.port = port
        irc.ssl = True
        await asyncio.sleep(1)
        await irc.connect()
        irc.persist = persist
    else:
        await irc.finish_negotiation('sts')


@Handler('RPL_ISUPPORT')
async def _handler(irc, msg):
    isupport = _tag_list_to_dict(msg.args[1:-1])

    # Try and auto-detect integers
    remove = set()
    for key in isupport:
        try:
            isupport[key] = int(isupport[key])
            if key == 'NICKLEN':
                irc.current_nick = irc.current_nick[: isupport[key]]
        except ValueError:
            if key.endswith('LEN'):
                remove.add(key)
    for key in remove:
        del isupport[key]

    irc.isupport.update(isupport)


del _handler
