# miniirc stub file
# This allows type checking without breaking compatibility or making the main
#   file slower to load.

from logging import Logger
from re import Match, Pattern
from ssl import SSLContext
from collections.abc import Callable, Iterable
from typing import Any, NamedTuple, TypeAlias, overload
from asyncio import AbstractEventLoop, StreamReader, StreamWriter, Task

# The version string and tuple
ver: tuple[int, int, int, str] = ...
version: str = ...
__version__: str = ...

# __all__ and _default_caps
__all__: list[str] = ['Handler', 'IRC', 'IRCMessage', 'Hostmask', 'register_numerics', 'HandlersCollection']
_default_caps: set[str] = {
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

get_ca_certs: Callable[[], str | None]
try:
    from certifi import where as get_ca_certs  # type: ignore
except ImportError:
    def get_ca_certs() -> str | None:
        pass

_handler_func_1 = Callable[['IRC'], Any]
_handler_func_2 = Callable[['IRC', 'IRCMessage'], Any]

TagsDict: TypeAlias = dict[str, str | bool]

class Handler:
    """Internal handler wrapper for IRC event callbacks."""

    func: Callable
    awaitable: bool
    params_count: int
    def __init__(self, func: Callable) -> None: ...

class HandlersCollection:
    """Handler decorator and manager for IRC events."""

    handlers: dict[str, list[Handler]]
    def __init__(self) -> None: ...
    def __call__(self, *events: str) -> Callable[[Any], Any]: ...
    def getHandlers(self) -> dict[str, list[Handler]]: ...

handle: HandlersCollection

@overload
def handle(*events: str) -> Callable[[_handler_func_1], _handler_func_1]: ...
@overload
def handle(*events: str) -> Callable[[_handler_func_2], _handler_func_2]: ...

_ircv3_tag_escapes: dict[str, str] = {':': ';', 's': ' ', 'r': '\r', 'n': '\n'}

def _unescape_tag(match: Match[str]) -> str: ...
def _tag_list_to_dict(tag_list: Iterable[str]) -> TagsDict: ...

class Hostmask(NamedTuple):
    nick: str = ''
    user: str = ''
    host: str = ''

class IRCMessage(NamedTuple):
    command: str
    hostmask: Hostmask = Hostmask()
    tags: TagsDict | None = None
    args: list | None = None
    line: str | None = None

    def sub_command(self, prefix: str) -> 'IRCMessage | None': ...
    def handle(self, irc: 'IRC') -> bool: ...
    async def _start_handler(self, handler: Handler, irc: 'IRC') -> None: ...

# Escape tags
def _escape_tag(tag: str) -> str: ...

# Convert a dict into an IRCv3 tags string
def _dict_to_tags(tags: TagsDict) -> bytes: ...
def register_numerics(numerics: dict[str, str]) -> None: ...
def _event_name_to_numeric(event: str) -> str | None: ...

# Create the IRC class
class IRC:
    connected: bool | None = None
    msglen: int = 512

    host: str
    port: int
    nick: str
    current_nick: str
    channels: set[str]
    username: str
    realname: str
    password: str | None
    ssl: bool | SSLContext | None
    persist: bool
    ircv3_caps: set[str]
    active_caps: set[str]
    isupport: dict[str, str | int | bool]
    connect_modes: str | None
    quit_message: str
    ping_interval: int
    ping_timeout: int | None
    verify_ssl: bool
    server_password: str | None
    max_reconnect_attempts: int
    log: Logger

    # Internal runtime attrs
    _sendq: list[tuple[TagsDict | None, tuple[str, ...]]] | None
    _loop: AbstractEventLoop
    _task: Task[None] | None
    _sasl: bool
    _unhandled_caps: dict[str, list[str]] | None
    _combined_handlers: dict[str, list[Handler]] | None
    _nickname_re: Pattern[str]
    _msg_re: Pattern[str]
    _reconnect: bool
    _pinged: bool
    _reader: StreamReader | None
    _writer: StreamWriter | None
    _disconnecting: bool

    handle: HandlersCollection

    # 1. Initialization & Configuration
    def __init__(
        self,
        host: str,
        port: int,
        nick: str,
        *,
        channels: Iterable[str] | str | None = None,
        username: str | None = None,
        realname: str | None = None,
        password: str | None = None,
        server_password: str | None = None,
        persist: bool = True,
        ssl: bool | SSLContext | None = None,
        verify_ssl: bool = True,
        ircv3_caps: set[str] | None = None,
        connect_modes: str | None = None,
        ping_interval: int = 60,
        ping_timeout: int | None = None,
        max_reconnect_attempts: int = 10,
    ) -> None: ...
    def set_logger(
        self, name: str, *, level: int | None = None, filename: str | None = None, format: str | None = None
    ) -> None: ...

    # 2. Connection Management
    async def connect(self, *, loop: AbstractEventLoop | None = None) -> None: ...
    async def disconnect(self, msg: str | None = None, *, auto_reconnect: bool | None = None) -> None: ...
    def _create_ssl_context(self) -> SSLContext | None: ...
    async def _establish_connection(self, ctx: SSLContext | None) -> None: ...
    def _send_initial_msgs(self) -> None: ...
    async def wait_until_disconnected(self) -> None: ...

    # 3. Message Sending
    def send(self, *msg: str, force: bool = False, tags: TagsDict | None = None) -> Task | None: ...
    def command(self, command: str, *args: str, force: bool = False, tags: TagsDict | None = None) -> Task | None: ...
    def msg(self, target: str, msg: str, tags: TagsDict | None = None) -> Task | None: ...
    def notice(self, target: str, msg: str, tags: TagsDict | None = None) -> Task | None: ...
    def ctcp(self, target: str, *msg: str, reply: bool = False, tags: TagsDict | None = None) -> Task | None: ...
    def me(self, target: str, msg: str, tags: TagsDict | None = None) -> Task | None: ...

    # 4. Message Parsing & Handling
    def message_parser(self, msg: str) -> IRCMessage | None: ...
    def _get_combined_handlers(self) -> dict[str, list[Handler]]: ...
    async def _process_line(self, line: str) -> None: ...
    async def _message_loop(self) -> None: ...
    async def _async_main(self) -> None: ...
    async def _read_line_with_timeout(self) -> bytes | None: ...

    # 5. IRCv3 Capability Negotiation
    def finish_negotiation(self, cap: str) -> None: ...
    def _handle_cap(self, cap: str) -> None: ...

    # 6. Utility & Overridable Methods
    def on_disconnect(self) -> None: ...
    def debug_print_line(self, line: str) -> None: ...
    def alter_nickname(self) -> str: ...
