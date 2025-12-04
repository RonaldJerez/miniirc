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
from contextlib import suppress

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


# Parse IRCv3 tags
_ircv3_tag_escapes = {':': ';', 's': ' ', 'r': '\r', 'n': '\n'}


def _unescape_tag(match):
    char = match.group(1)
    return _ircv3_tag_escapes.get(char, char)


def _tag_list_to_dict(tag_list):
    """Convert a list of IRCv3 tag strings to a dictionary."""

    tags = {}
    for tag in tag_list:
        tag = tag.split('=', 1)
        if len(tag) == 1:
            tags[tag[0]] = True
        elif len(tag) == 2:
            value = re.sub(r'\\(.)', _unescape_tag, tag[1])
            tags[tag[0]] = value

    return tags


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


class Handler:
    """Internal handler wrapper for IRC event callbacks."""

    __slots__ = ('func', 'awaitable', 'params_count')

    def __init__(self, func):
        self.func = func
        self.awaitable = asyncio.iscoroutinefunction(func)

        signature = inspect.signature(func)
        self.params_count = len(signature.parameters.keys())

        if self.params_count > 2:
            raise TypeError(f'Handler only accepts 2 params, got {self.params_count}')


class HandlersCollection:
    """Handler decorator and manager for IRC events."""

    def __init__(self):
        self.handlers = {}

    def __call__(self, *events):
        """Decorator to add a handler for one or more IRC events."""
        if not events:
            raise TypeError('Handler() called without arguments.')

        def wrapper(func):
            handler = Handler(func)
            for event in events:
                event = _event_name_to_numeric(event)
                if event not in self.handlers:
                    self.handlers[event] = []
                if handler not in self.handlers[event]:
                    self.handlers[event].append(handler)
            return func

        return wrapper

    def getHandlers(self):
        return self.handlers


class Hostmask(NamedTuple):
    """Represents an IRC hostmask (nick!user@host)."""

    nick: str = ''
    user: str = ''
    host: str = ''


_active_background_tasks = set()


class IRCMessage(NamedTuple):
    """Represents a parsed IRC message."""

    command: str
    hostmask: Hostmask = Hostmask()
    tags: dict | None = None
    args: list | None = None

    # optionally store the line this message was derived from (for debugging purpose)
    line: str | None = None 

    def sub_command(self, prefix):
        """
        Creates a new message with sub-commands from the current message.

        Example:
            msg = IRCMessage('PRIVMSG', ..., args=['#chan', '\x01ACTION waves\x01'])
            sub = msg.sub_command('CTCP')<br>
            sub.command == 'CTCP ACTION'
            sub.args == ['#chan', 'waves']
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

    def handle(self, irc):
        """Dispatch a parsed IRC message to registered handlers."""
        ctcp_msg = None
        handled = False
        input_command = self.command.upper()

        if input_command in ('PRIVMSG', 'NOTICE') and self.args:
            text = self.args[-1]
            if len(text) > 2 and text.startswith('\x01') and text.endswith('\x01'):
                ctcp_msg = self.sub_command('CTCP')

        msg = ctcp_msg or self
        msg_command = msg.command.upper()
        combined_handlers = irc._get_combined_handlers()

        handlers = combined_handlers.get(msg_command, []) + combined_handlers.get('*', [])
        if len(handlers) > 0:
            handled = True
            for handler in handlers:
                task = asyncio.create_task(msg._start_handler(handler, irc))
                task.add_done_callback(_active_background_tasks.discard)
                _active_background_tasks.add(task)

        return handled

    async def _start_handler(self, handler, irc):
        """Start a handler for a given message, running async or in executor."""
        try:
            params = (irc, self)
            if handler.awaitable:
                await handler.func(*params[: handler.params_count])
            else:
                # Run non-async handlers in the event loop's default executor
                await irc._loop.run_in_executor(None, handler.func, *params[: handler.params_count])
        except Exception as e:
            irc.log.exception(f'Handler {handler.func.__name__} raised an exception: {e}')


class IRC:
    """An IRC client connection supporting IRCv2 and IRCv3 features."""

    connected = None
    msglen = 512
    quit_message = 'I grew sick and died.'
    _reconnect = False
    _sendq = None
    _loop = None
    _sasl = False
    _unhandled_caps = None
    _combined_handlers = None
    _task = None
    _nickname_re = re.compile(r'^(?![\d-])[\w`^|{}[\]\-\\]+$')
    _msg_re = re.compile(
        r'^'
        r'(?:@([^ ]*) )?'  # Tags
        r'(?::([^!@ ]*)(?:!([^@ ]*))?(?:@([^ ]*))? )?'  # Hostmask
        r'([^@: ][^ ]*)(?: (.*?))??(?: :(.*))?'  # Command and arguments
        r'$'
    )

    # Class-level handlers (global)
    handle = HandlersCollection()

    def __init_subclass__(cls, **kwargs):
        """Create isolated handler collection for each subclass."""
        super().__init_subclass__(**kwargs)
        cls.handle = HandlersCollection()

    # 1. Initialization & Configuration
    def __init__(self, host, port, nick, *, 
                 channels=None,
                 username=None, realname=None, 
                 password=None, server_password=None, 
                 persist=True, ssl=None, verify_ssl=True,
                 ircv3_caps=None, connect_modes=None,
                 ping_interval=60, ping_timeout=None,
                 max_reconnect_attempts=10):
        
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
        self.max_reconnect_attempts = max_reconnect_attempts
        self._sendq = []
        self.log = logger
        self._disconnecting = False

        # validate the nickname
        if not self._nickname_re.match(self.nick):
            raise ValueError(f'Invalid nickname: {self.nick}')

        # Add IRCv3 capabilities.
        if self.password:
            self.ircv3_caps.add('sasl')

        # Instance-level handlers (shadows class attribute for this instance)
        self.handle = HandlersCollection()

        # Try to detect ssl
        if ssl is None and self.port == 6697:
            self.ssl = True

    def set_logger(self, name, *, level=None, filename=None, format=None):
        """Set up a logger for this IRC instance."""

        instance_logger = logging.getLogger(name)
        instance_logger.propagate = False

        if level is not None:
            instance_logger.setLevel(level)

        if filename is not None:
            if instance_logger.hasHandlers():
                self.log.warning(f'Logger "{name}" already has handlers, skipping file handler creation.')
            else:
                handler = logging.FileHandler(filename)
                if format is not None:
                    formatter = logging.Formatter(format)
                    handler.setFormatter(formatter)
                instance_logger.addHandler(handler)

        self.log = instance_logger

    # 2. Connection Management
    async def connect(self, *, loop=None):
        """
        Connect to the IRC server and start the main loop.

        Does **NOT** raises CancelledError on disconnect, if you need that for say asyncio.gather()
        use wait_until_disconnected(), after making your connection.
        """
        if self.connected is not None:
            self.log.debug('Already connected!')
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
        self.log.debug('Starting main loop...')
        self._sasl = self._pinged = False

        self._task = self._loop.create_task(self._async_main())
        try:
            await self._task
        except asyncio.CancelledError:
            self._task.uncancel()

    async def disconnect(self, msg=None, *, auto_reconnect=None):
        """Disconnect from the IRC server."""
        if self._loop is None:
            return
        if auto_reconnect is not None:
            self._reconnect = auto_reconnect
        self.connected = None
        self.active_caps.clear()
        self._unhandled_caps = None
        self._disconnecting = True

        if hasattr(self, '_writer') and not self._writer.is_closing():
            # with suppress(Exception):
            quit_task = self.command('QUIT', msg or self.quit_message, force=True)
            if quit_task:
                await quit_task

            with suppress(Exception):
                self._writer.close()
                await self._writer.wait_closed()

        # Cancel any running task
        current_task = asyncio.current_task()
        if self._task and self._task is current_task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                self._task.uncancel()

    def _create_ssl_context(self):
        """Create and configure SSL context for secure connections."""
        if not self.ssl:
            return None
        elif isinstance(self.ssl, ssl.SSLContext):
            ctx = self.ssl
        else:
            ctx = ssl.create_default_context(cafile=get_ca_certs())

        if self.verify_ssl:
            assert ctx.check_hostname
        else:
            warnings.warn('Disabling verify_ssl is usually a bad idea.')
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def _establish_connection(self, ctx):
        """Establish connection to IRC server with retry logic."""
        attempt = 0
        self._reconnect = False
        while True:
            try:
                self.log.debug(f'Initializing connection to {self.host} on port {self.port} (attempt {attempt + 1})')
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port, ssl=ctx),
                    timeout=self.ping_timeout or self.ping_interval,
                )
                self.log.info(f'Socket connected to {self.host} on port {self.port}')
                self._send_initial_msgs()
                return
            except (asyncio.TimeoutError, OSError) as e:
                if hasattr(self, '_writer'):
                    self._writer.close()
                    await self._writer.wait_closed()

                attempt += 1
                if not self.persist or attempt >= self.max_reconnect_attempts:
                    self.log.error(f'Failed to connect after {attempt} attempts')
                    self.log.error(str(e))
                    break

                # Exponential delay, capped at 5 minutes
                delay = min(2**attempt, 300)
                self.log.debug(f'Failed to connect, trying again in {delay} seconds...')
                await asyncio.sleep(delay)

    def _send_initial_msgs(self):
        """Send initial registration and capability negotiation messages."""
        if self.server_password:
            self.send('PASS', self.server_password, force=True)
        self.send('CAP LS 302', force=True)
        self.command('USER', self.username, '0 *', self.realname, force=True)
        self.send('NICK', self.nick, force=True)

    async def wait_until_disconnected(self):
        """Wait until the IRC connection is closed.

        This can be used with asyncio.gather() to wait for multiple connections:
        await asyncio.gather(irc1.wait_until_disconnected(), irc2.wait_until_disconnected())

        raises: asyncio.CancelledError.
        """
        if self._task:
            await self._task

    # 3. Message Sending
    def send(self, *msg, force=False, tags=None):
        """Send a raw IRC message by joining arguments with spaces.

        This is the low-level method that sends exactly what you provide.
        For formatted IRC commands with automatic trailing parameter handling,
        use command() instead.

        Args:
            *msg: Message components to join with spaces
            force: Send even if not connected (for connection setup)
            tags: IRCv3 message tags dictionary
        """
        if getattr(self, '_disconnecting', False):
            self.log.debug('Suppressing send: disconnect in progress')
            return

        str_msg = ' '.join(str(m) for m in msg)

        if not self.connected and not force:
            self.log.debug(f'>Q> {str_msg}')
            if not self._sendq:
                self._sendq = []
            self._sendq.append((tags, msg))
            return

        if not hasattr(self, '_writer'):
            self.log.debug('No writer available to send message')
            return

        self.log.debug(f'>>> {str_msg}')

        msg_bytes = str_msg.replace('\x00', '\ufffd').encode('utf-8', errors='replace')
        msg_bytes = msg_bytes.replace(b'\r', b' ').replace(b'\n', b' ')

        # Truncate if needed
        # TODO multi line support?
        if len(msg_bytes) + 2 > self.msglen:
            msg_bytes = msg_bytes[: self.msglen - 2]
            # Re-decode and encode to avoid splitting multi-byte characters
            msg_bytes = msg_bytes.decode('utf-8', errors='ignore').encode('utf-8')

        # Add tags if applicable
        if isinstance(tags, dict) and 'message-tags' in self.active_caps:
            msg_bytes = _dict_to_tags(tags) + msg_bytes

        msg_bytes += b'\r\n'

        send_task = asyncio.create_task(self._quote(msg_bytes))
        send_task.add_done_callback(_active_background_tasks.discard)
        _active_background_tasks.add(send_task)
        return send_task

    async def _quote(self, msg_bytes):
        """Send raw bytes to the server."""

        try:
            self._writer.write(msg_bytes)
            await self._writer.drain()
        except Exception as e:
            self.log.error(f'Error sending message: {msg_bytes.decode("utf-8", errors="replace")}')
            self.log.exception(e)

    def command(self, command, *args, force=False, tags=None):
        """Send a IRC command with arguments. Applying ':' to the last argument."""
        if args:
            args = list(args)
            args[-1] = ':' + str(args[-1])
        return self.send(command, *args, force=force, tags=tags)

    def msg(self, target, msg, tags=None):
        """Send a PRIVMSG to a target."""
        return self.command('PRIVMSG', target, msg, tags=tags)
        
    def notice(self, target, msg, tags=None):
        """Send a NOTICE to a target."""
        return self.command('NOTICE', target, msg, tags=tags)
    
    def ctcp(self, target, *msg, reply=False, tags=None):
        """Send a CTCP message or reply to a target."""
        m = self.notice if reply else self.msg
        return m(target, f'\x01{" ".join(map(str, msg))}\x01', tags=tags)
    
    def me(self, target, msg, tags=None):
        """Send a CTCP ACTION (/me) to a target."""
        return self.ctcp(target, 'ACTION', msg, tags=tags)

    # 4. Message Parsing & Handling
    def message_parser(self, line):
        """Parse a raw IRC message string into an IRCMessage object."""
        match = self._msg_re.match(line)
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
        return IRCMessage(cmd, hostmask, tags, args, line)

    def _get_combined_handlers(self):
        """Get combined IRC base class (global), current class, and instance handlers."""

        # do this loop only once per instance, there shouldn't be any new handlers post init
        if self._combined_handlers is None:
            self._combined_handlers = {}
            
            # Get handlers from IRC base class
            irc_base_handlers = IRC.handle.getHandlers()
            
            # Get handlers from the current class (if it's a subclass)
            current_class_handlers = {}
            if self.__class__ is not IRC:
                current_class_handlers = self.__class__.handle.getHandlers()
            
            # Get instance handlers
            instance_handlers = self.handle.getHandlers()

            # Combine all three levels
            for key in set(irc_base_handlers) | set(current_class_handlers) | set(instance_handlers):
                self._combined_handlers[key] = (
                    irc_base_handlers.get(key, []) + 
                    current_class_handlers.get(key, []) + 
                    instance_handlers.get(key, [])
                )

        return self._combined_handlers

    async def _process_line(self, line_str):
        """Process a single IRC message line."""
        self.debug_print_line(line_str)

        try:
            msg = self.message_parser(line_str)
            if isinstance(msg, IRCMessage):
                msg.handle(self)
            else:
                self.log.debug(f'Ignored message: {line_str}')
        except Exception as exc:
            self.log.error('Error handling IRC message', exc_info=exc)

    async def _message_loop(self):
        """Main message reading and processing loop."""
        while True:
            try:
                line = await self._read_line_with_timeout()

                # line will return None if a PING was sent to check timeout
                if line is None:
                    continue

                if not line:
                    self.log.debug('Received empty line, connection might be closed.')
                    raise ConnectionAbortedError

                line_str = line.rstrip(b'\r\n').decode('utf-8', 'replace')
                if line_str:
                    await self._process_line(line_str)

            except Exception as exc:
                self.log.info(f'Disconnected from {self.host}')
                self.log.debug(f'Disconnection reason: {exc}')

                # Only reconnect we had a successful initial connection (RPL_WELCOME received)
                should_reconnect = self._reconnect or (self.persist and self.connected)
                await self.disconnect()
                self.on_disconnect()

                if should_reconnect:
                    self.log.debug('Attempting to reconnect...')
                    await asyncio.sleep(5)
                    await self.connect()

                return

    async def _async_main(self):
        """Main loop for reading and handling IRC messages."""
        ctx = self._create_ssl_context()
        await self._establish_connection(ctx)
        await self._message_loop()

    async def _read_line_with_timeout(self):
        """Read a line from the IRC server with ping timeout handling."""
        timeout = self.ping_timeout if self._pinged else self.ping_interval
        try:
            return await asyncio.wait_for(self._reader.readuntil(b'\n'), timeout=timeout)
        except asyncio.TimeoutError:
            if self._pinged:
                raise
            self._pinged = True
            self.send('PING :miniirc-ping', force=True)
            return None

    # 5. IRCv3 Capability Negotiation
    def finish_negotiation(self, cap):
        """Finish IRCv3 capability negotiation for a given capability."""
        self.log.debug(f'Capability {cap} handled')
        if self._unhandled_caps:
            cap = cap.lower()
            if cap in self._unhandled_caps:
                del self._unhandled_caps[cap]
            if len(self._unhandled_caps) < 1:
                self._unhandled_caps = None
                if not self.connected:
                    self.send('CAP END', force=True)

    def _handle_cap(self, cap):
        """Handle IRCv3 capability acknowledgement."""
        cap = cap.lower()
        self.active_caps.add(cap)
        if self._unhandled_caps and cap in self._unhandled_caps:
            msg = IRCMessage(f'CAP ACK {cap}', args=self._unhandled_caps[cap])
            handled = msg.handle(self)
            if not handled:
                self.finish_negotiation(cap)

    # 6. Utility & Overridable Methods
    def on_disconnect(self):
        """Called when the IRC connection is closed. Override as needed."""
        pass

    def debug_print_line(self, line):
        """
        Print every line received when debugging.
        Override this method to customize or filter which lines to print.
        """
        self.log.debug(f'<<< {line}')

    def alter_nickname(self):
        """Alter the current nickname by appending an underscore."""
        self.current_nick += '_'
        return self.current_nick


# Handle some IRC messages by default.
@IRC.handle('RPL_WELCOME')
async def _handler(irc):
    irc.connected = True
    irc.isupport.clear()
    irc._unhandled_caps = None

    irc.log.info(f'Welcome message received from {irc.host}! Connection fully established.')

    if irc.connect_modes:
        irc.send('MODE', irc.current_nick, irc.connect_modes)
    if not irc._sasl and irc.password:
        irc.log.debug('Logging in (no SASL, aww)...')
        irc.msg('NickServ', f'identify {irc.username} {irc.password}')
    if irc.channels:
        irc.log.debug(f'*** Joining channels... {irc.channels}')
        irc.send('JOIN', ','.join(irc.channels))

    # Handle queued messages
    sendq, irc._sendq = irc._sendq, None
    if sendq:
        for tags, args in sendq:
            irc.send(*args, tags=tags)


@IRC.handle('PING')
async def _handler(irc, msg):
    irc.command('PONG', *msg.args, force=True)


@IRC.handle('PONG')
async def _handler(irc, msg):
    if msg.args and msg.args[-1] == 'miniirc-ping' and irc.ping_interval:
        irc._pinged = False


@IRC.handle('ERR_ERRONEUSNICKNAME', 'ERR_NICKNAMEINUSE')
async def _handler(irc, msg):
    if not irc.connected:
        irc.log.info(f'{msg.command}: The requested nickname "{irc.current_nick}" is invalid or in use.')

        new_nick = irc.alter_nickname()

        # TODO: we wouldnt have gotten an isupport response yet?
        if not irc._nickname_re.match(new_nick) or len(new_nick) > irc.isupport.get('NICKLEN', 20):
            irc.log.error(f'New nickname "{new_nick}" is invalid or too long. Disconnecting.')
            with suppress(Exception):
                await irc.disconnect()
            return

        irc.log.info(f'Trying again with "{new_nick}"')
        irc.send('NICK', new_nick, force=True)


# Server changed our nickname?
@IRC.handle('NICK')
async def _handler(irc, msg):
    if msg.hostmask.nick.lower() == irc.current_nick.lower():
        irc.current_nick = msg.args[-1]


@IRC.handle('CTCP VERSION')
async def _handler(irc, msg):
    if not version:
        return
    irc.ctcp(msg.hostmask.nick, 'VERSION', version, reply=True)


@IRC.handle('CAP')
async def _handler(irc, msg):
    if len(msg.args) < 3:
        return

    msg = msg._replace(command=f'CAP {msg.args[1]}')
    msg.handle(irc)


@IRC.handle('CAP ACK')
async def _handler(irc, msg):
    caps = msg.args[-1].split(' ')
    for cap in caps:
        irc._handle_cap(cap)


@IRC.handle('CAP NAK')
async def _handler(irc):
    irc._unhandled_caps = None
    irc.send('CAP END', force=True)


@IRC.handle('CAP LS', 'CAP NEW')
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
        irc.command('CAP', 'REQ', ' '.join(req), force=True)
    elif msg.command == 'CAP LS' and not irc._unhandled_caps and not multiline:
        irc._unhandled_caps = None
        irc.send('CAP END', force=True)


@IRC.handle('CAP DEL')
async def _handler(irc, msg):
    caps = msg.args[-1].split(' ')

    for cap in caps:
        cap = cap.lower()
        if cap in irc.active_caps:
            irc.active_caps.remove(cap)


@IRC.handle('CAP ACK SASL')
async def _handler(irc, msg):
    sasl_options = msg.args[-1].upper().split(',')
    if irc.password and (len(msg.args) < 2 or 'PLAIN' in sasl_options):
        irc.send('AUTHENTICATE PLAIN', force=True)
    else:
        irc.send('AUTHENTICATE *', force=True)
        irc.finish_negotiation('sasl')


@IRC.handle('AUTHENTICATE')
async def _handler(irc, msg):
    if msg.args and msg.args[0] == '+':
        irc._sasl = True
        pw = f'{irc.username}\x00{irc.username}\x00{irc.password}'.encode('utf-8')
        irc.send('AUTHENTICATE', b64encode(pw).decode('utf-8'), force=True)


@IRC.handle('ERR_SASLFAIL', 'ERR_SASLABORTED')
async def _handler(irc):
    if irc._sasl:
        irc._sasl = False
        irc.log.warning(f'SASL authentication failed for {irc.host}')
        irc.send('AUTHENTICATE *', force=True)


@IRC.handle('ERR_NICKLOCKED', 'RPL_SASLSUCCESS', 'ERR_SASLFAIL', 'ERR_SASLABORTED')
async def _handler(irc):
    irc.finish_negotiation('sasl')


@IRC.handle('CAP ACK STS')
async def _handler(irc, msg):
    if not irc.ssl and len(msg.args) == 2:
        try:
            port = int(_tag_list_to_dict(msg.args[1].split(','))['port'])
        except (IndexError, KeyError, ValueError):
            return

        irc.log.info(f'STS detected, enabling TLS/SSL and changing the port to {port}')

        # dont override ctx if already set (needed for testing)
        if not irc.ssl:
            irc.ssl = True

        irc.port = port
        irc._reconnect = True

        await irc.disconnect(auto_reconnect=True)
    else:
        irc.finish_negotiation('sts')


@IRC.handle('RPL_ISUPPORT')
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
            # Unable to convert to int, remove it as it is invalid value
            if key.endswith('LEN'):
                remove.add(key)
    for key in remove:
        del isupport[key]

    irc.isupport.update(isupport)


del _handler
