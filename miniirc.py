#!/usr/bin/python3
#
# miniirc - A small-ish IRC framework.
#
# © 2018-2022 by luk3yx and other contributors of miniirc.
#

import asyncio
import collections
import re
import ssl
import sys
import types
import warnings
import inspect

# The version string and tuple
ver = __version_info__ = (2,0,0,'a9')
version = 'miniirc IRC framework v2.0.0a9'
__version__ = '2.0.0a9'

# __all__ and _default_caps
__all__ = ['CmdHandler', 'Handler', 'IRC']
_default_caps = {'account-notify', 'account-tag', 'away-notify', 'cap-notify',
                'chghost', 'extended-join', 'invite-notify', 'message-tags',
                'server-time', 'sts'}

# Get the certificate list.
try:
    from certifi import where as get_ca_certs # type: ignore
except ImportError:
    def get_ca_certs():
        pass

# Create global handlers
_global_handlers = {}

class _Handler:
    __slots__ = ('func', 'awaitable', 'signature')

    def __init__(self, func):
        self.func = func
        self.awaitable = asyncio.iscoroutinefunction(func)
        self.signature = inspect.signature(func)

        possible_params = {'irc', 'command', 'hostmask', 'tags', 'args'}

        # throw error if signature does not match expected parameters
        params = list(self.signature.parameters.values())
        for param in params:
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                raise TypeError('Handler parameters cannot be *args or **kwargs.')
            if param.name not in possible_params:
                raise TypeError(f'Invalid handler parameter: {param.name}')


# Included numerics that are used internally to keep library lightweight
_IRC_NUMERICS = {
    'RPL_WELCOME': '001',
    'RPL_ISUPPORT': '005',
    'ERR_ERRONEUSNICKNAME': '432',
    'ERR_NICKNAMEINUSE': '433',
    'ERR_NICKLOCKED': '902',
    'RPL_SASLSUCCESS': '903',
    'ERR_SASLFAIL': '904',
    'ERR_SASLABORTED': '905'
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

def _add_handler(handlers, events):
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
    return _add_handler(_global_handlers, events)

def CmdHandler(*events):
    warnings.warn('CmdHandler is deprecated, use Handler instead', DeprecationWarning)
    return Handler(*events)

# Parse IRCv3 tags
_ircv3_tag_escapes = {':': ';', 's': ' ', 'r': '\r', 'n': '\n'}
def _tag_list_to_dict(tag_list):
    tags = {}
    for tag in tag_list:
        tag = tag.split('=', 1)
        if len(tag) == 1:
            tags[tag[0]] = ''
        elif len(tag) == 2:
            if '\\' in tag[1]: # Iteration is bad, only do it if required.
                value = ''
                escape = False
                for char in tag[1]: # TODO: Remove this iteration.
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
Hostmask = collections.namedtuple('Hostmask', 'nick user host')
IRCMessage = collections.namedtuple('IRCMessage', 'command hostmask tags args')
_msg_re = re.compile(
    r'^'
    r'(?:@([^ ]*) )?'                               # Tags
    r'(?::([^!@ ]*)(?:!([^@ ]*))?(?:@([^ ]*))? )?'  # Hostmask
    r'([^@: ][^ ]*)(?: (.*?)(?: :(.*))?)?'          # Command and arguments
    r'$'
)
def ircv3_message_parser(msg):
    match = _msg_re.match(msg)
    if not match:
        return

    # Process IRCv3 tags
    raw_tags = match.group(1)
    tags = {} if raw_tags is None else _tag_list_to_dict(raw_tags.split(';'))

    # Process arguments
    hostmask = Hostmask(match.group(2) or '', match.group(3) or '',
                        match.group(4) or '')
    cmd = match.group(5)

    # Get the command and arguments
    raw_args = match.group(6)
    args = [] if raw_args is None else raw_args.split(' ')

    trailing = match.group(7)
    if trailing:
        args.append(trailing)

    # Return the parsed data
    return IRCMessage(cmd.upper(), hostmask, tags, args)

# Escape tags
def _escape_tag(tag):
    tag = str(tag).replace('\\', '\\\\')
    for i in _ircv3_tag_escapes:
        tag = tag.replace(_ircv3_tag_escapes[i], '\\' + i)
    return tag

# Convert a dict into an IRCv3 tags string
def _dict_to_tags(tags):
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

# A wrapper for callable logfiles
class _Logfile:
    __slots__ = ('_buffer', '_func')

    def write(self, data):
        self._buffer += data
        while '\n' in self._buffer:
            line, self._buffer = self._buffer.split('\n', 1)
            self._func(line)

    def __init__(self, func):
        self._buffer = ''
        self._func = func

# Replace invalid RFC1459 characters with Unicode lookalikes
def _prune_arg(arg):
    if arg.startswith(':'):
        arg = '\u0703' + arg[1:]
    elif not arg:
        # Replace the argument with something to prevent misinterpretation
        arg = ' '
    return arg.replace(' ', '\xa0').replace('\r', '\xa0').replace('\n', '\xa0')

async def _suppress_oserror(coro):
    try:
        return await coro
    except OSError:
        pass

# Create the IRC class
class IRC:
    connected = None
    debug_file = sys.stdout
    _sendq = None
    msglen = 512
    _loop = None
    _sasl = False
    _unhandled_caps = None

    def __init__(self, ip, port, nick, channels=None, *, ssl=None, ident=None,
                 realname=None, persist=True, debug=False, ns_identity=None,
                 auto_connect=True, ircv3_caps=None, connect_modes=None,
                 quit_message='I grew sick and died.', ping_interval=60,
                 ping_timeout=None, verify_ssl=True, server_password=None, loop=None):
        # Set basic variables
        self.ip = ip
        self.port = int(port)
        self.nick = self.current_nick = nick
        if isinstance(channels, str):
            channels = map(str.lstrip, channels.split(','))
        self.channels = set(channels or ())
        self.ident = ident or nick
        self.realname = realname or nick
        self.ssl = ssl
        self.persist = persist
        self.ircv3_caps = set(ircv3_caps or ()) | _default_caps
        self.active_caps = set()
        self.isupport = {}
        self.connect_modes = connect_modes
        self.quit_message = quit_message
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.verify_ssl = verify_ssl
        self.server_password = server_password
        self._task = None
        self._sendq = []

        # Set the NickServ identity
        if ns_identity:
            if isinstance(ns_identity, str):
                self.ns_identity = tuple(ns_identity.split(' ', 1))
            else:
                self.ns_identity = tuple(map(str, ns_identity))
            assert len(self.ns_identity) == 2
        else:
            self.ns_identity = None

        # Set the debug file
        if not debug:
            self.debug_file = None
        elif hasattr(debug, 'write'):
            self.debug_file = debug
        elif callable(debug):
            self.debug_file = _Logfile(debug)

        # Add IRCv3 capabilities.
        if self.ns_identity:
            self.ircv3_caps.add('sasl')

        # Add handlers and set the default message parser
        self.change_parser()
        self._handlers = {}
        if ssl is None and self.port == 6697:
            self.ssl = True

        # Start the connection
        if auto_connect:
            if loop is None:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            self._loop = loop
            loop.create_task(self.connect(loop=loop))
        elif loop is not None:
            raise TypeError('loop cannot be specified with auto_connect=False')

    # Debug print()
    def debug(self, *args, **kwargs):
        if self.debug_file:
            print(*args, file=self.debug_file, **kwargs)
            if hasattr(self.debug_file, 'flush'):
                self.debug_file.flush()

    # Send raw messages
    async def quote(self, *msg, force=False, tags=None):
        if not self.connected and not force:
            self.debug('>Q>', *msg)
            if not self._sendq:
                self._sendq = []
            self._sendq.append((tags, msg))
            return

        self.debug('>>>', *msg)
        msg = (' '.join(msg).replace('\x00', '\ufffd').encode('utf-8')
               .replace(b'\r', b' ') .replace(b'\n', b' '))

        if len(msg) + 2 > self.msglen:
            msg = msg[:self.msglen - 2]
            if msg[-1] >= 0x80:
                msg = msg.decode('utf-8', 'ignore').encode('utf-8')

        if isinstance(tags, dict) and 'message-tags' in self.active_caps:
            msg = _dict_to_tags(tags) + msg

        msg += b'\r\n'
        self._writer.write(msg)
        await self._writer.drain()

    async def send(self, command, *args, force=False, tags=None):
        if args:
            await self.quote(
                _prune_arg(command),
                *map(_prune_arg, args[:-1]),
                ':' + args[-1],
                force=force,
                tags=tags
            )
        else:
            await self.quote(_prune_arg(command), force=force, tags=tags)

    # User-friendly msg, notice, and CTCP functions.
    async def msg(self, target, *msg, tags=None):
        await self.quote('PRIVMSG', target, ':' + ' '.join(msg), tags=tags)

    async def notice(self, target, *msg, tags=None):
        await self.quote('NOTICE', target, ':' + ' '.join(msg), tags=tags)

    async def ctcp(self, target, *msg, reply=False, tags=None):
        m = (self.notice if reply else self.msg)
        await m(target, f'\x01{" ".join(msg)}\x01', tags=tags)

    async def me(self, target, *msg, tags=None):
        await self.ctcp(target, 'ACTION', *msg, tags=tags)

    # Allow per-connection handlers
    def Handler(self, *events):
        return _add_handler(self._handlers, events)

    def CmdHandler(self, *events):
        warnings.warn('CmdHandler is deprecated, use Handler instead', DeprecationWarning)
        return self.Handler(*events)

    # The connect function
    async def connect(self, *, loop=None):
        if self.connected is not None:
            self.debug('Already connected!')
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
        self.debug('Starting main loop...')
        self._sasl = self._pinged = False
        
        self._task = self._loop.create_task(self._async_main())
        await self._task

    # Disconnect from IRC.
    async def disconnect(self, msg=None, *, auto_reconnect=False):
        if self._loop is None:
            return

        self.persist = auto_reconnect and self.persist
        self.connected = None
        self.active_caps.clear()
        self._unhandled_caps = None
        try:
            await self.quote('QUIT :' + str(msg or self.quit_message),
                       force=True)
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

    # Finish capability negotiation
    async def finish_negotiation(self, cap):
        self.debug('Capability', cap, 'handled.')
        if self._unhandled_caps:
            cap = cap.lower()
            if cap in self._unhandled_caps:
                del self._unhandled_caps[cap]
            if len(self._unhandled_caps) < 1:
                self._unhandled_caps = None
                if not self.connected:
                    await self.quote('CAP END', force=True)

    # Change the message parser
    def change_parser(self, parser=ircv3_message_parser):
        self._parse = parser

    # Start a handler function
    async def _start_handler(self, handlers, msg):
        for handler in handlers:
            kwargs = {}
            if 'irc' in handler.signature.parameters:
                kwargs['irc'] = self
            if 'hostmask' in handler.signature.parameters:
                kwargs['hostmask'] = msg.hostmask
            if 'command' in handler.signature.parameters:
                kwargs['command'] = msg.command
            if 'tags' in handler.signature.parameters:
                kwargs['tags'] = types.MappingProxyType(msg.tags)
            if 'args' in handler.signature.parameters:
                kwargs['args'] = list(msg.args)

            if handler.awaitable:
                await handler.func(**kwargs)
            else:
                # Run non-async handlers in the event loop's default executor
                await self._loop.run_in_executor(None, handler.func, **kwargs)

    # Launch handlers
    async def handle_msg(self, msg):
        # Handle CTCP embedded in PRIVMSG/NOTICE internally:
        # if the last argument is a CTCP (starts and ends with \x01 and length>2),
        # construct a "CTCP {COMMAND}" message and dispatch that instead of
        # the original PRIVMSG/NOTICE.
        if msg.command in ('PRIVMSG', 'NOTICE') and msg.args:
            text = msg.args[-1]
            if isinstance(text, str) and len(text) > 2 and text.startswith('\x01') and text.endswith('\x01'):
                ctcp_content = text[1:-1]
                ctcp_parts = ctcp_content.split(' ', 1)
                ctcp_command = 'CTCP ' + ctcp_parts[0].upper()

                ctcp_args = list(msg.args[:-1])
                if len(ctcp_parts) > 1:
                    ctcp_args.append(ctcp_parts[1])

                ctcp_msg = IRCMessage(ctcp_command, msg.hostmask, msg.tags, ctcp_args)

                handled = False
                for handlers in (_global_handlers, self._handlers):
                    if ctcp_msg.command in handlers:
                        await self._start_handler(handlers[ctcp_msg.command], ctcp_msg)
                        handled = True

                    if None in handlers:
                        await self._start_handler(handlers[None], ctcp_msg)

                return handled

        # If it was not a CTCP command, then process the message normally
        handled = False
        for handlers in (_global_handlers, self._handlers):
            if msg.command in handlers:
                await self._start_handler(handlers[msg.command], msg)
                handled = True

            if None in handlers:
                await self._start_handler(handlers[None], msg)

        return handled

    # Launch IRCv3 CAP acknowledgement handlers
    async def _handle_cap(self, cap):
        cap = cap.lower()
        self.active_caps.add(cap)
        if self._unhandled_caps and cap in self._unhandled_caps:
            handled = await self.handle_msg(IRCMessage(
                ('CAP ACK ' + cap).upper(), Hostmask('', '', ''), {},
                self._unhandled_caps[cap]
            ))
            if not handled:
                await self.finish_negotiation(cap)

    async def _send_initial_msgs(self):
        if self.server_password:
            await self.quote('PASS', self.server_password, force=True)
        await self.quote('CAP LS 302', force=True)
        await self.quote('USER', self.ident, '0', '*', ':' + self.realname,
                         force=True)
        await self.quote('NICK', self.nick, force=True)

    # The main loop
    async def _async_main(self):
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
                self.debug('Connecting to', self.ip, 'port', self.port)
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.ip, self.port, ssl=ctx),
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

                self.debug('Failed to reconnect, trying again in 5 seconds.')
                await asyncio.sleep(5)

        self.debug('Main loop running!')
        while True:
            try:
                try:
                    # Use readuntil so that partial lines aren't read
                    line = await asyncio.wait_for(
                        self._reader.readuntil(b'\n'),
                        timeout=self._pinged and self.ping_timeout or
                                self.ping_interval
                    )
                except asyncio.TimeoutError:
                    if self._pinged:
                        raise

                    self._pinged = True
                    await self.quote('PING :miniirc-ping', force=True)
                    continue

                if not line:
                    raise ConnectionAbortedError
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                    asyncio.TimeoutError, OSError) as exc:
                self.debug('Lost connection!', repr(exc))
                await self.disconnect(auto_reconnect=True)

                if self.persist:
                    await asyncio.sleep(5)
                    self.debug('Reconnecting...')
                    await self.connect()
                return

            line_str = line.rstrip(b'\r\n').decode('utf-8', 'replace')
            if line_str:
                self.debug('<<<', line_str)
                try:
                    msg = self._parse(line_str)
                    if isinstance(msg, IRCMessage):
                        await self.handle_msg(msg)
                    else:
                        self.debug('Ignored message:', line_str)
                except Exception:
                    import traceback
                    traceback.print_exc()

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
async def _handler(irc, args):
    irc.connected = True
    irc.isupport.clear()
    irc._unhandled_caps = None
    irc.debug('Connected!')
    if irc.connect_modes:
        await irc.quote('MODE', irc.nick, irc.connect_modes)
    if not irc._sasl and irc.ns_identity:
        irc.debug('Logging in (no SASL, aww)...')
        await irc.msg('NickServ', 'identify', *irc.ns_identity)
    if irc.channels:
        irc.debug('*** Joining channels...', irc.channels)
        await irc.quote('JOIN', ','.join(irc.channels))

    # Handle queued messages
    sendq, irc._sendq = irc._sendq, None
    if sendq:
        for tags, args in sendq:
            await irc.quote(*args, tags=tags)

@Handler('PING')
async def _handler(irc, args):
    await irc.send('PONG', *args, force=True)

@Handler('PONG')
async def _handler(irc, args):
    if args and args[-1] == 'miniirc-ping' and irc.ping_interval:
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
        irc.debug('WARNING: The requested nickname', repr(irc.current_nick),
            'is invalid. Trying again with', repr(irc.current_nick + '_') +
            '...')
        irc.current_nick += '_'
        await irc.quote('NICK', irc.current_nick, force=True)

@Handler('NICK')
async def _handler(irc, hostmask, args):
    if hostmask[0].lower() == irc.current_nick.lower():
        irc.current_nick = args[-1]

@Handler('CTCP VERSION')
async def _handler(irc, hostmask):
    if not version:
        return
    await irc.ctcp(hostmask[0], 'VERSION', version, reply=True)

@Handler('CAP')
async def _handler(irc, hostmask, args):
    if len(args) < 3:
        return
    
    cmd = args[1].upper()
    # caps = args[-1].split(' ')

    msg = IRCMessage('CAP ' + cmd, hostmask, {}, args)
    await irc.handle_msg(msg)

@Handler('CAP ACK')
async def _handler(irc, args):
    caps = args[-1].split(' ')
    for cap in caps:
        await irc._handle_cap(cap)

@Handler('CAP NAK')
async def _handler(irc):
    irc._unhandled_caps = None
    await irc.quote('CAP END', force=True)

@Handler('CAP LS', 'CAP NEW')
async def _handler(irc, command, args):
    req = set()
    
    if not irc._unhandled_caps:
        irc._unhandled_caps = {}

    caps = args[-1].split(' ')
    multiline = args[2] == '*'

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
        await irc.quote('CAP REQ', ':' + ' '.join(req), force=True)
    elif command == 'CAP LS' and not irc._unhandled_caps and not multiline:
        irc._unhandled_caps = None
        await irc.quote('CAP END', force=True)

@Handler('CAP DEL')
async def _handler(irc, args):
    caps = args[-1].split(' ')

    for cap in caps:
        cap = cap.lower()
        if cap in irc.active_caps:
            irc.active_caps.remove(cap)

@Handler('CAP ACK SASL')
async def _handler(irc, args):
    if irc.ns_identity and (len(args) < 2 or 'PLAIN' in
            args[-1].upper().split(',')):
        await irc.quote('AUTHENTICATE PLAIN', force=True)
    else:
        await irc.quote('AUTHENTICATE *', force=True)
        await irc.finish_negotiation('sasl')

@Handler('AUTHENTICATE')
async def _handler(irc, args):
    if args and args[0] == '+':
        from base64 import b64encode
        irc._sasl = True
        pw = '{0}\x00{0}\x00{1}'.format(*irc.ns_identity).encode('utf-8')
        await irc.quote('AUTHENTICATE', b64encode(pw).decode('utf-8'), force=True)

@Handler('ERR_SASLFAIL', 'ERR_SASLABORTED')
async def _handler(irc):
    if irc._sasl:
        irc._sasl = False
        await irc.quote('AUTHENTICATE *', force=True)

@Handler('ERR_NICKLOCKED', 'RPL_SASLSUCCESS', 'ERR_SASLFAIL', 'ERR_SASLABORTED')
async def _handler(irc):
    await irc.finish_negotiation('sasl')

# STS
@Handler('CAP ACK STS')
async def _handler(irc, args):
    if not irc.ssl and len(args) == 2:
        try:
            port = int(_tag_list_to_dict(args[1].split(','))['port'])
        except (IndexError, KeyError, ValueError):
            return

        persist = irc.persist
        await irc.disconnect()
        irc.debug('STS detected, enabling TLS/SSL and changing the port to ',
                  port)
        irc.port = port
        irc.ssl = True
        await asyncio.sleep(1)
        await irc.connect()
        irc.persist = persist
    else:
        await irc.finish_negotiation('sts')

@Handler('RPL_ISUPPORT')
async def _handler(irc, args):
    isupport = _tag_list_to_dict(args[1:-1])

    # Try and auto-detect integers
    remove = set()
    for key in isupport:
        try:
            isupport[key] = int(isupport[key])
            if key == 'NICKLEN':
                irc.current_nick = irc.current_nick[:isupport[key]]
        except ValueError:
            if key.endswith('LEN'):
                remove.add(key)
    for key in remove:
        del isupport[key]

    irc.isupport.update(isupport)

del _handler
