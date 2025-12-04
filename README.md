# miniirc

# Warning

This branch contains a miniirc v2.0.0 pre-release, the documentation is probably
out-of-date and breaking changes can and will happen without notice.

[![Python 3.6+]](#python-version-support) [![Available on PyPI.]](https://pypi.org/project/miniirc/) [![License: MIT]](https://github.com/luk3yx/miniirc/blob/master/LICENSE.md)

[Python 3.6+]: https://img.shields.io/badge/python-3.13+-blue.svg
[Available on PyPI.]: https://img.shields.io/pypi/v/miniirc.svg
[License: MIT]: https://img.shields.io/pypi/l/miniirc.svg

A relatively simple async/await-based IRC client framework.

## What's New in v2.0.0

- **Async/await architecture**: miniirc v2.0.0 is built on asyncio. Handlers can be async functions, and connection methods are async.
- **Simplified handler system**: Handler signatures are introspected to determine parameters, eliminating boilerplate code. Use `@irc.handle()` decorator.
- **Built-in logging**: Uses Python's standard `logging` module with per-instance configuration.
- **Hostmask as NamedTuple**: Hostmasks are structured as `Hostmask(nick, user, host)` for clearer field access.
- **Internal CTCP handling**: CTCP messages are handled internally, so `PRIVMSG` handlers only receive actual chat messages.
- **Event name references**: IRC numerics can be referenced by name (e.g., `'RPL_WELCOME'`) instead of just numbers.
- **Improved handler isolation**: Global, class, and instance handlers are properly isolated.
- **Non-blocking message sending**: No need to make all methods async just to send messages - synchronous sending is supported.

To install miniirc, simply run `pip3 install miniirc`.


## Parameters

```py
from miniirc import IRC

bot = IRC(host, port, nick, *, 
        channels=None,
        username=None, realname=None, 
        password=None, server_password=None, 
        persist=True, ssl=None, verify_ssl=True,
        ircv3_caps=None, connect_modes=None,
        ping_interval=60, ping_timeout=None,
        max_reconnect_attempts=10)
```

*Note that everything before the \* is a positional argument.*

### Typical usage

You don't need to add every argument, and the `host`, `port`, and `nick` arguments should be specified as positional arguments.

```py
import asyncio
from miniirc import IRC

bot = IRC('irc.example.com', 6697, 'my-bot', 
            channels=['#my-channel'], 
            password='hunter2')

# For async context
async def main():
    await bot.connect()

asyncio.run(main())
```

If you are not doing anything with the main thread after connecting to IRC,
please call `await irc.wait_until_disconnected()` to keep the program running while miniirc is connected.

### Parameter descriptions

| Parameter     | Description                                                |
| ------------- | -------------------------------------------------------- |
| `host`        | The IP/hostname of the IRC server to connect to.          |
| `port`        | The port to connect to.                                   |
| `nick`        | The desired nickname of the bot.                                 |
| `channels`    | The channels to join on connect. This can be an iterable containing strings (list, set, etc), or a comma-delimited string. |
| `username`    | The username/ident to use, defaults to `nick`.            |
| `realname`    | The realname to use, defaults to `nick` as well.          |
| `password`    | The NickServ/SASL password for authentication.            |
| `server_password` | The server password (sent before registration).       |
| `persist`     | Whether to automatically reconnect.                       |
| `ssl`         | Enable TLS/SSL. If `None`, TLS is disabled unless the port is `6697`. |
| `verify_ssl`  | Verifies TLS/SSL certificates. Disabling this is not recommended as it opens the IRC connection up to MiTM attacks. If you have trouble with certificate verification, try running `pip3 install certifi` first. |
| `ircv3_caps`  | A set() of additional IRCv3 capabilities to request. SASL is auto-added if `password` is specified. |
| `connect_modes` | A mode string (for example `'+B'`) of UMODEs to set when connected. |
| `ping_interval` | If no packets are sent or received for this amount of seconds, miniirc will send a `PING`, and if no reply is sent, after the ping timeout, miniirc will attempt to reconnect. Set to `None` to disable. |
| `ping_timeout` | The ping timeout used alongside the above `ping_interval` option, if unspecified will default to `ping_interval`. |
| `max_reconnect_attempts` | Maximum number of reconnection attempts before giving up. |

*The only mandatory parameters are `host`, `port`, and `nick`.*

## SSL/TLS
To verify SSL certificates, you will need to install the `certifi` package. This is done so that consumers can update the CA bundle independently of miniirc.

```sh
pip3 install certifi
```

## Logging

miniirc v2.0.0 uses Python's standard `logging` module. To configure logging:

```py
import logging
import miniirc

# Set logging level for miniirc globally
logging.getLogger('miniirc').setLevel(logging.INFO)

# Or configure per-instance with custom logger
bot = miniirc.IRC('irc.example.com', 6697, 'my-bot')
bot.set_logger('my_bot_logger', level=logging.DEBUG, filename='my_bot.log')
```

## Functions

### Connection Management

| Function      | Description                                               |
| ------------- | --------------------------------------------------------  |
| `await connect(*, loop=None)` | Connects to the IRC server if not already connected. Does not raise `CancelledError` on disconnect. Async function. |
| `await disconnect(msg=None, *, auto_reconnect=None)` | Disconnects from the IRC server. If `msg` is provided, it's sent as the QUIT message. Set `auto_reconnect` to trigger a reconnect attempt. |
| `await wait_until_disconnected()` | Waits until the IRC connection is closed. Useful with `asyncio.gather()` for multiple connections. Raises `CancelledError`. Async function. |
| `on_disconnect()` | Called when the IRC connection is closed. Override this method to add custom cleanup logic. |

### Message Sending

| Function      | Description                                               |
| ------------- | --------------------------------------------------------  |
| `send(*msg, force=False, tags=None)` | Sends a raw IRC message by joining arguments with spaces. Low-level method - use `command()` for formatted commands. Messages are queued if not connected unless `force=True`. |
| `command(command, *args, force=False, tags=None)` | Sends an IRC command with arguments. Automatically adds `:` to the last argument. Higher-level than `send()`. |
| `msg(target, msg, tags=None)` | Sends a `PRIVMSG` to a target (channel or user). |
| `notice(target, msg, tags=None)` | Sends a `NOTICE` to a target (channel or user). |
| `ctcp(target, *msg, reply=False, tags=None)` | Sends a CTCP request or reply. Set `reply=True` to send a CTCP reply (uses NOTICE instead of PRIVMSG). |
| `me(target, msg, tags=None)` | Sends a CTCP ACTION (`/me`) to a target. |

### Configuration & Utilities

| Function      | Description                                               |
| ------------- | --------------------------------------------------------  |
| `set_logger(name, *, level=None, filename=None, format=None)` | Configures a custom logger for this IRC instance. Sets up a named logger with optional level, file output, and format. |
| `message_parser(msg)` | Parses a raw IRC message string into an `IRCMessage` object. Can be overridden for custom parsing. |
| `finish_negotiation(cap)` | Marks an IRCv3 capability as handled during capability negotiation. Call this in IRCv3 capability handlers. |
| `handle(*events)` | Decorator to add handlers for IRC events. See [Handlers](#handlers) section. |

*Note: Messages sent with `send()` or `command()` are automatically queued if miniirc is not connected (unless `force=True` is used). They will be sent once the connection is established.*

### send() vs command()

The two functions `send()` and `command()` serve different purposes:

- **`send(*msg, force=False, tags=None)`**: Low-level raw message sending. Joins all arguments with spaces and sends exactly what you provide. Use this when you need precise control over the IRC protocol message.

- **`command(command, *args, force=False, tags=None)`**: Higher-level command sending. Automatically formats the last argument with a leading `:` as per IRC protocol. Use this for most IRC commands.

#### Examples

```py
# Using send() - you control the exact format
irc.send('PRIVMSG', '#channel', ':Hello, world!')  # Sends: PRIVMSG #channel :Hello, world!

# Using command() - automatic formatting
irc.command('PRIVMSG', '#channel', 'Hello, world!')  # Sends: PRIVMSG #channel :Hello, world!

# For PRIVMSG/NOTICE, use the convenience methods
irc.msg('#channel', 'Hello, world!')  # Recommended - cleaner syntax
irc.notice('#channel', 'Notice text')
```

*For most use cases, use `msg()`, `notice()`, or `command()` rather than `send()` directly.*

## Variables

*These variables should not be changed directly unless noted otherwise.*

| Variable      | Description                                               |
| ------------- | --------------------------------------------------------  |
| `host`        | The hostname/IP of the IRC server. |
| `port`        | The port number to connect to. |
| `nick`        | The nickname to use when connecting. This is the configured nickname, not necessarily the current one. |
| `current_nick` | The bot/client's current nickname on IRC. Use this to get the active nickname. Read-only. |
| `channels`    | A `set` of channels to join on connect. |
| `username`    | The username/ident used for connection. |
| `realname`    | The realname used for connection. |
| `password`    | The NickServ/SASL password (if configured). |
| `connected`   | Connection status: `True` when connected, `False` when connecting, `None` when disconnected. Read-only. |
| `active_caps` | A `set` of IRCv3 capabilities that have been successfully negotiated. Empty while disconnected. Read-only. |
| `isupport`    | A `dict` of values from `ISUPPORT` (005) messages sent by the server. Read-only. |
| `msglen`      | The maximum length (in bytes) of messages including `\r\n`. Read-only. |
| `persist`     | Whether to automatically reconnect on disconnect. |
| `ssl`         | Whether TLS/SSL is enabled for the connection. |
| `verify_ssl`  | Whether to verify TLS/SSL certificates. |
| `ircv3_caps`  | A `set` of IRCv3 capabilities to request. |
| `connect_modes` | Mode string of UMODEs to set when connected. |
| `ping_interval` | Seconds between PING checks. |
| `ping_timeout` | Timeout for PING responses. |
| `log`         | The logger instance for this IRC connection. |
| `handle`      | The handler collection for this instance. Use as decorator: `@irc.handle('EVENT')`. |

## Handler Types

miniirc supports three types of handlers, each with different scopes:

### Global Handlers

Global handlers are added to the `IRC` base class and triggered for **all** IRC instances:

```py
from miniirc import IRC

# This handler will be called for ALL IRC connections
@IRC.handle('PRIVMSG')
def global_handler(irc, msg):
    print(f"Global: {msg.hostmask.nick} said {msg.args[-1]}")

# Both connections will trigger the global handler
irc1 = IRC('irc.example.com', 6697, 'bot1')
irc2 = IRC('irc.other.com', 6697, 'bot2')
```

### Class Handlers

Class handlers are added to a custom subclass and triggered only for instances of that class:

```py
import miniirc

class MyBot(miniirc.IRC):
    pass

# This handler only works for MyBot instances
@MyBot.handle('PRIVMSG')
def class_handler(irc, msg):
    print(f"Class: {msg.hostmask.nick} said {msg.args[-1]}")

bot1 = MyBot('irc.example.com', 6697, 'bot1')  # Will trigger class_handler
irc2 = miniirc.IRC('irc.other.com', 6697, 'bot2')  # Will NOT trigger class_handler
```

### Instance Handlers

Instance handlers are added to a specific IRC instance and only triggered for that instance:

```py
import miniirc

irc1 = miniirc.IRC('irc.example.com', 6697, 'bot1')
irc2 = miniirc.IRC('irc.other.com', 6697, 'bot2')

# This handler only works for irc1
@irc1.handle('PRIVMSG')
def instance_handler(irc, msg):
    print(f"Instance: {msg.hostmask.nick} said {msg.args[-1]}")

# irc1 will trigger instance_handler, irc2 will not
```

### Handler Priority

When an IRC event occurs, handlers are called in this order:
1. Global handlers (from `IRC` base class)
2. Class handlers (from the instance's class)
3. Instance handlers (from the specific instance)

All matching handlers are called - they don't override each other.

## Handler Decorator

The `*.handle()` is the decorator that adds functions to an event handler list. Functions in this list are called when their respective IRC event(s) are received as described above.

The basic syntax for a handler is as follows, where `*events` is a list of events (`PRIVMSG`, `NOTICE`, etc) to handle.

```py
import miniirc

irc = miniirc.IRC('irc.example.com', 6697, 'my-bot')

# Handlers can be synchronous
@irc.handle('PRIVMSG')
def handler(irc, msg):
    # irc: An 'IRC' object.
    # msg: An 'IRCMessage' object containing:
    #      - cmd: The command (e.g., 'PRIVMSG')
    #      - hostmask: A Hostmask namedtuple (nick, user, host)
    #      - tags: A dict of IRCv3 tags
    #      - args: A list of command arguments
    #      - line: The raw line received from the server
    print(f"{msg.hostmask.nick} said: {msg.args[-1]}")

# Or asynchronous
@irc.handle('NOTICE')
async def async_handler(irc, msg):
    await some_async_operation()
    irc.msg(msg.args[0], 'Got your notice!')
```

Handlers are automatically run concurrently using asyncio. The handler signature is introspected to determine what parameters to pass:
- `handler()` - Does not receive any parameters
- `handler(irc)` - Only receives the IRC object
- `handler(irc, msg)` - Receives IRC object and full IRCMessage

### Handling multiple events

You can handle multiple events by passing multiple event names to `irc.handle()`. The command name that triggered the event will be available in `msg.cmd`.

### Message object
Message objects are `NamedTuple` objects with the format `IRCMessage(cmd, hostmask, tags, args, line)`, allowing field access by name, the attributes are as follows:
- `cmd`: The command name (e.g., `PRIVMSG`, `NOTICE`, etc).
- `hostmask`: A `Hostmask` object (see below).
- `tags`: A `dict` of IRCv3 tags (if any).
- `args`: A `list` of command arguments.
- `line`: The raw line received from the server.

```py
@irc.handle('PRIVMSG')
def handler(irc, msg):
    print(f"Command: {msg.cmd}") # e.g., 'PRIVMSG'
    print(f"Hostmask: {msg.hostmask}") # Hostmask named tuple (nick, user, host)
    print(f"Arguments: {msg.args}")
    print(f"Raw line: {msg.line}")
```

### Hostmask object

Hostmasks are `NamedTuple` objects with the format `Hostmask(nick, user, host)`, allowing field access by name, the attributes are as follows:
- `nick`: The nickname part of the hostmask.
- `user`: The username/ident part of the hostmask.
- `host`: The hostname part of the hostmask.

```py
@irc.handle('PRIVMSG')
def handler(irc, msg):
    print(f"Nick: {msg.hostmask.nick}")
    print(f"User: {msg.hostmask.user}")
    print(f"Host: {msg.hostmask.host}")
```

If `user` and `host` aren't sent from the server, they will be filled in with empty strings. If a command is received without a hostmask, all the `hostmask` fields will be set to empty strings.

### CTCP handling

miniirc automatically separates CTCP messages from regular PRIVMSG/NOTICE messages. When a CTCP message is received, it triggers a separate `CTCP <command>` event instead of PRIVMSG:

```py
@irc.handle('PRIVMSG')
def handle_privmsg(irc, msg):
    # This handler is ONLY called for actual chat messages
    # CTCP requests like VERSION, PING, ACTION are NOT handled here
    print(f"Chat message: {msg.args[-1]}")

@irc.handle('CTCP VERSION')
def handle_ctcp_version(irc, msg):
    # This handles CTCP VERSION requests
    # msg.args[0] is the target (usually your nick)
    # msg.args[1] contains any additional parameters (if present)
    irc.ctcp(msg.hostmask.nick, 'VERSION', 'MyBot v1.0', reply=True)

@irc.handle('CTCP PING')
def handle_ctcp_ping(irc, msg):
    # Echo back the PING parameter
    if len(msg.args) > 1:
        irc.ctcp(msg.hostmask.nick, 'PING', msg.args[1], reply=True)

@irc.handle('CTCP ACTION')
def handle_action(irc, msg):
    # Handle /me messages (CTCP ACTION)
    # msg.args[0] is the channel or nick
    # msg.args[1] is the action text
    print(f"* {msg.hostmask.nick} {msg.args[1]}")

# Sending CTCP requests
irc.ctcp('#channel', 'VERSION')  # Request version from channel
irc.ctcp('nickname', 'PING', '12345')  # Send PING with timestamp

# Sending /me (CTCP ACTION)
irc.me('#channel', 'waves hello')  # Sends: /me waves hello
```

**How it works**: When a PRIVMSG or NOTICE contains CTCP format (`\x01COMMAND args\x01`), miniirc creates a new `CTCP <COMMAND>` event with the CTCP content extracted, so your regular message handlers don't have to deal with CTCP parsing.

### Event names

Handler event names can be specified using either a friendly descriptive name (e.g., `RPL_WELCOME`, `RPL_ISUPPORT`) or the numeric code (e.g., `001`, `005`).

> miniirc does not currently include all numeric-to-name mappings by default, only as small subset needed for internal logic. You can register additional names as needed (see below).

```py
@irc.handle('RPL_WELCOME')  # Named reference instead of '001'
def on_welcome(irc, msg):
    pass

# You must register your own custom names for numerics
miniirc.register_numerics({'NICK_NAME_LOCKED': '902'})

@irc.handle('NICK_NAME_LOCKED') # or @irc.handle('902')
def on_nick_locked(irc, msg):
    pass

```

### IRCv3 support

#### IRCv3 tags capability

IRCv3 tags are automatically included in the `IRCMessage` object passed to handlers. Access them via `msg.tags`:

```py
import miniirc

irc = miniirc.IRC('irc.example.com', 6697, 'my-bot')

@irc.handle('PRIVMSG')
def handler(irc, msg):
    # Tags are always available in msg.tags
    if 'account' in msg.tags:
        print(f"User is logged in as: {msg.tags['account']}")
    print(f"Message: {msg.args[-1]}")
```

*miniirc will automatically un-escape IRCv3 tag values.*

#### IRCv3 extended-join capability

The `extended-join` capability is requested by default. In `JOIN` handlers,
use `args[0]` instead of `args[-1]` to get the channel as `extended-join` adds extra arguments to `JOIN` messages.

#### Handling other IRCv3 capabilities

You can handle IRCv3 capabilities before connecting using a handler.
You must use `force=True` on any `irc.send()` called here, as when this is
called, miniirc may not be fully connected yet.

```py
import miniirc

irc = miniirc.IRC('irc.example.com', 6697, 'my-bot', ircv3_caps={'my-cap-name'})

@irc.handle('IRCv3 my-cap-name')
async def handler(irc, msg):
    # Process the capability here
    # msg.args contains capability parameters
    
    # IRCv3.2 capabilities:
    #   msg.args = ['my-cap-name', 'IRCv3.2-parameters']

    # IRCv3.1 capabilities:
    #   msg.args = ['my-cap-name']

    # Remove the capability from the processing list.
    irc.finish_negotiation(msg.args[0])  # This can also be 'my-cap-name'.
```

## Advanced usage

### Message parser
If the IRC server you are connecting to supports a non-standard message syntax,
you can subclass `IRC` and overwrite `message_parser`.  This method is called with the raw message
(as a string) and can either return `None` to ignore the message or an instance
of `IRCMessage`.


> This message parser makes the normal parser allow `~` as an IRCv3 tag prefix character.

```py
import miniirc

class MyIRC(miniirc.IRC):
    def message_parser(self, msg: str) -> miniirc.IRCMessage | None:
        # Replace ~ with @ for tag parsing
        modified_msg = msg.replace('~', '@', 1) if msg.startswith('~') else msg
        return super().message_parser(modified_msg)
```



### Catch-all handlers

**Please do not use these unless there is no other alternative.**

If you want to handle *every* event, you can use catch-all handlers. To create
these, you can pass '*' to `irc.handle()`. Note that this
handler will be called many times while connecting (and once connected).

### Example

```py
import miniirc

irc = miniirc.IRC('irc.example.com', 6697, 'my-bot')

@irc.handle('*')
def catch_all_handler(irc, msg):
    if msg.cmd in ('PRIVMSG', 'NOTICE'):
        print(f"Catch-all: {msg.hostmask.nick} sent a {msg.cmd}: {msg.args[-1]}")

```

## Python version support

miniirc v2.0.0 requires **Python 3.13 or later**.

 - Python 3.12 and below are not supported due to the async/await architecture and modern typing features used in miniirc v2.0.0.
 - Python 3.13+ is fully supported and recommended.

If there is a bug/error, please open an issue or pull request on [GitHub](https://github.com/luk3yx/miniirc/issues) 
