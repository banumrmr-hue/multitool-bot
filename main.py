#!/usr/bin/env python3
"""
Multi-Tool Telegram Bot — Single File
Owner: @aadarshpy
Requires: BOT_TOKEN and MONGODB_URI environment variables
"""

# ─────────────────────────────────────────────────────────────────────────────
#  IMPORTS
# ─────────────────────────────────────────────────────────────────────────────

import ast
import asyncio
import base64
import binascii
import codecs
import gzip
import hashlib
import html
import io
import logging
import marshal
import os
import random
import re
import string
import sys
import textwrap
import time
import tokenize
import urllib.parse
import zlib
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.mongo import MongoStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from motor.motor_asyncio import AsyncIOMotorClient

# ─────────────────────────────────────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIG  (all from environment variables — no hardcoded secrets)
# ─────────────────────────────────────────────────────────────────────────────

BOT_TOKEN       = os.environ.get("BOT_TOKEN", "").strip()
MONGODB_URI     = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/telebot")
OWNER_USERNAME  = os.environ.get("OWNER_USERNAME", "@aadarshpy")
OWNER_CONTACT   = os.environ.get("OWNER_CONTACT",  "https://t.me/aadarshpy")
BOT_VERSION     = os.environ.get("BOT_VERSION",    "2.0.0")
MAX_FILE_SIZE   = int(os.environ.get("MAX_FILE_SIZE", str(5 * 1024 * 1024)))

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN environment variable is not set.")
    print("Set it on Render → Environment tab.")
    sys.exit(1)

_START_TIME = time.time()

# ─────────────────────────────────────────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────────────────────────────────────────

_mongo_client: AsyncIOMotorClient | None = None
_mongo_db = None


async def db_connect() -> None:
    global _mongo_client, _mongo_db
    _mongo_client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    _mongo_db = _mongo_client.get_default_database(default="telebot")
    await _mongo_client.admin.command("ping")
    logger.info("MongoDB connected.")


async def db_close() -> None:
    if _mongo_client:
        _mongo_client.close()


def _db():
    if _mongo_db is None:
        raise RuntimeError("DB not connected")
    return _mongo_db


async def upsert_user(user_id: int, username: str | None, first_name: str) -> None:
    try:
        await _db().users.update_one(
            {"user_id": user_id},
            {
                "$set": {"username": username, "first_name": first_name,
                          "last_seen": datetime.now(timezone.utc)},
                "$setOnInsert": {"user_id": user_id,
                                  "joined_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )
    except Exception:
        pass


async def log_op(user_id: int, op_type: str, details: dict | None = None) -> None:
    try:
        await _db().operations.insert_one(
            {"user_id": user_id, "type": op_type,
             "details": details or {}, "at": datetime.now(timezone.utc)}
        )
    except Exception:
        pass


async def count_users() -> int:
    try:
        return await _db().users.count_documents({})
    except Exception:
        return 0


async def count_ops(op_type: str | None = None) -> int:
    try:
        q = {"type": op_type} if op_type else {}
        return await _db().operations.count_documents(q)
    except Exception:
        return 0

# ─────────────────────────────────────────────────────────────────────────────
#  FSM STATES
# ─────────────────────────────────────────────────────────────────────────────

class EncryptionStates(StatesGroup):
    waiting_for_mode = State()
    waiting_for_file = State()

class ExpiryStates(StatesGroup):
    waiting_for_days     = State()
    waiting_for_datetime = State()

class LogicChangerStates(StatesGroup):
    waiting_for_file = State()

class DecoderStates(StatesGroup):
    waiting_for_input = State()

class MiniFileStates(StatesGroup):
    waiting_for_file = State()

# ─────────────────────────────────────────────────────────────────────────────
#  KEYBOARDS
# ─────────────────────────────────────────────────────────────────────────────

def main_menu_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔐 Premium Encryption", callback_data="menu:encryption"),
          InlineKeyboardButton(text="⏳ Expiry Generator",   callback_data="menu:expiry"))
    b.row(InlineKeyboardButton(text="🔀 Logic Changer",      callback_data="menu:logic"),
          InlineKeyboardButton(text="🔓 Decoder Board",      callback_data="menu:decoder"))
    b.row(InlineKeyboardButton(text="📦 MiniFile",           callback_data="menu:minifile"),
          InlineKeyboardButton(text="📊 Statistics",         callback_data="menu:stats"))
    b.row(InlineKeyboardButton(text="ℹ️ Help",               callback_data="menu:help"),
          InlineKeyboardButton(text="👑 Owner",              callback_data="menu:owner"))
    return b.as_markup()

def encryption_menu_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📖 Introduction", callback_data="enc:intro"))
    b.row(InlineKeyboardButton(text="🔐 Mode 1 — Base64+Zlib",   callback_data="enc:mode:1"),
          InlineKeyboardButton(text="🔏 Mode 2 — Marshal+B64",   callback_data="enc:mode:2"))
    b.row(InlineKeyboardButton(text="🛡 Mode 3 — Multi-Layer",   callback_data="enc:mode:3"),
          InlineKeyboardButton(text="⚔️ Mode 4 — XOR+Base64",    callback_data="enc:mode:4"))
    b.row(InlineKeyboardButton(text="🌀 Mode 5 — CFG Flatten",   callback_data="enc:mode:5"),
          InlineKeyboardButton(text="💎 Mode 6 — Full Obfusc",   callback_data="enc:mode:6"))
    b.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"))
    return b.as_markup()

def expiry_menu_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📅 Days Based Expiry",  callback_data="expiry:days"),
          InlineKeyboardButton(text="🕐 Date & Time Based",  callback_data="expiry:datetime"))
    b.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"))
    return b.as_markup()

def decoder_menu_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🅱 Base64",  callback_data="dec:base64"),
          InlineKeyboardButton(text="🔢 Base32",  callback_data="dec:base32"))
    b.row(InlineKeyboardButton(text="📦 Base85",  callback_data="dec:base85"),
          InlineKeyboardButton(text="🔣 Hex",     callback_data="dec:hex"))
    b.row(InlineKeyboardButton(text="⊕ XOR",     callback_data="dec:xor"),
          InlineKeyboardButton(text="🗜 Zlib",   callback_data="dec:zlib"))
    b.row(InlineKeyboardButton(text="💨 Gzip",   callback_data="dec:gzip"),
          InlineKeyboardButton(text="🐍 Marshal", callback_data="dec:marshal"))
    b.row(InlineKeyboardButton(text="λ Lambda",  callback_data="dec:lambda"),
          InlineKeyboardButton(text="🔄 ROT13",  callback_data="dec:rot13"))
    b.row(InlineKeyboardButton(text="🔤 URL",    callback_data="dec:url"),
          InlineKeyboardButton(text="📝 HTML",   callback_data="dec:html"))
    b.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"))
    return b.as_markup()

def cancel_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Cancel", callback_data="action:cancel"))
    return b.as_markup()

def back_kb(target: str = "menu:main"):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Back", callback_data=target))
    return b.as_markup()

# ─────────────────────────────────────────────────────────────────────────────
#  ENCRYPTION ENGINE  (6 Modes)
# ─────────────────────────────────────────────────────────────────────────────

def _rvar(n: int = 8) -> str:
    return "_" + "".join(random.choices(string.ascii_lowercase, k=n))

def _enc_mode1(source: str) -> str:
    b64 = base64.b64encode(zlib.compress(source.encode(), 9)).decode()
    v1, v2, v3 = _rvar(), _rvar(), _rvar()
    return (f"#!/usr/bin/env python3\nimport base64,zlib\n"
            f"{v1}={b64!r}\n{v2}=base64.b64decode({v1}.encode())\n"
            f"{v3}=zlib.decompress({v2})\nexec(compile({v3},'<e>','exec'))\n")

def _enc_mode2(source: str) -> str:
    b64 = base64.b64encode(marshal.dumps(compile(source, "<e>", "exec"))).decode()
    v1, v2 = _rvar(), _rvar()
    return (f"#!/usr/bin/env python3\nimport base64,marshal\n"
            f"{v1}={b64!r}\n{v2}=marshal.loads(base64.b64decode({v1}.encode()))\nexec({v2})\n")

def _enc_mode3(source: str) -> str:
    raw = zlib.compress(marshal.dumps(compile(source, "<e>", "exec")), 9)
    chunks = [base64.b64encode(raw).decode()[i:i+76] for i in range(0, len(base64.b64encode(raw).decode()), 76)]
    cv, v1, v2 = _rvar(), _rvar(), _rvar()
    lines = f"{cv}=(\n" + "".join(f"    {c!r}\n" for c in chunks) + ")\n"
    return (f"#!/usr/bin/env python3\nimport base64,zlib,marshal\n"
            f"{lines}{v1}=zlib.decompress(base64.b64decode({cv}.encode()))\n"
            f"{v2}=marshal.loads({v1})\nexec({v2})\n")

def _enc_mode4(source: str) -> str:
    key = random.randint(1, 254)
    b64 = base64.b64encode(bytes(b ^ key for b in source.encode())).decode()
    v1, v2, v3, vk = _rvar(), _rvar(), _rvar(), _rvar()
    return (f"#!/usr/bin/env python3\nimport base64\n{vk}={key}\n{v1}={b64!r}\n"
            f"{v2}=base64.b64decode({v1}.encode())\n"
            f"{v3}=bytes(b^{vk} for b in {v2}).decode('utf-8')\n"
            f"exec(compile({v3},'<e>','exec'))\n")

def _enc_mode5(source: str) -> str:
    try:
        flat = _flatten_source(source)
    except Exception:
        flat = source
    b64 = base64.b64encode(zlib.compress(flat.encode(), 9)).decode()
    v1, v2 = _rvar(), _rvar()
    return (f"#!/usr/bin/env python3\n# control-flow obfuscated\nimport base64,zlib\n"
            f"{v1}={b64!r}\n{v2}=zlib.decompress(base64.b64decode({v1}.encode()))\n"
            f"exec(compile({v2},'<e>','exec'))\n")

_ANTIDEBUG = """\
import sys as _s,os as _o,threading as _t,time as _tm
def _g():
 while True:
  try:
   if _s.gettrace() or _s.getprofile(): _o._exit(1)
   with open('/proc/self/status') as _f:
    for _l in _f:
     if _l.startswith('TracerPid:') and int(_l.split(':')[1])!=0: _o._exit(1)
  except Exception: pass
  _tm.sleep(3)
_t.Thread(target=_g,daemon=True).start()
"""

def _enc_mode6(source: str) -> str:
    try:
        flat = _flatten_source(source)
    except Exception:
        flat = source
    key = random.randint(1, 254)
    raw = bytes(b ^ key for b in zlib.compress(marshal.dumps(compile(flat,"<e>","exec")),9))
    b64_full = base64.b64encode(raw).decode()
    chunks = [b64_full[i:i+72] for i in range(0, len(b64_full), 72)]
    cv, v1, v2, v3, vk = _rvar(), _rvar(), _rvar(), _rvar(), _rvar()
    lines = f"{cv}=(\n" + "".join(f"    {c!r}\n" for c in chunks) + ")\n"
    return (f"#!/usr/bin/env python3\nimport base64,zlib,marshal,sys,os,threading,time\n"
            f"{_ANTIDEBUG}{lines}{vk}={key}\n"
            f"{v1}=bytes(b^{vk} for b in base64.b64decode({cv}.encode()))\n"
            f"{v2}=zlib.decompress({v1})\n{v3}=marshal.loads({v2})\nexec({v3})\n")

ENC_MODE_NAMES = {
    1: "Base64 + Zlib",
    2: "Marshal + Base64",
    3: "Multi-Layer (Zlib→Marshal→Base64)",
    4: "XOR + Base64 (random key)",
    5: "Control-Flow Flatten + Base64",
    6: "Full Obfuscation (all layers + anti-debug)",
}

_ENC_FNS = {1: _enc_mode1, 2: _enc_mode2, 3: _enc_mode3,
            4: _enc_mode4, 5: _enc_mode5, 6: _enc_mode6}

def encrypt_file(source: str, mode: int) -> str:
    if mode not in _ENC_FNS:
        raise ValueError(f"Mode {mode} not supported. Use 1–6.")
    return _ENC_FNS[mode](source)

# ─────────────────────────────────────────────────────────────────────────────
#  FLATTENING ENGINE
# ─────────────────────────────────────────────────────────────────────────────

try:
    from ast import unparse as _ast_unparse
    _HAS_UNPARSE = True
except ImportError:
    _HAS_UNPARSE = False


class _FlattenTransformer(ast.NodeTransformer):
    def __init__(self):
        super().__init__()
        self._c = 0

    def _ns(self) -> int:
        self._c += 1
        return self._c

    def visit_FunctionDef(self, node):
        node.body = self._fb(node.body)
        self.generic_visit(node)
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def _fb(self, body):
        if not body or (len(body) == 1 and isinstance(body[0], ast.Pass)):
            return body
        blocks = self._bb(body)
        sv = ast.Name("__s__", ast.Store())
        init = ast.Assign(targets=[sv], value=ast.Constant(0), lineno=0, col_offset=0)
        wbody = self._dispatch(blocks, "__s__")
        wloop = ast.While(test=ast.Constant(True), body=wbody, orelse=[], lineno=0, col_offset=0)
        return [init, wloop]

    def _bb(self, stmts):
        blocks, cur = [], []
        for s in stmts:
            if isinstance(s, (ast.If, ast.While, ast.For, ast.Try,
                               ast.Break, ast.Continue, ast.Return, ast.Raise)):
                if cur: blocks.append(cur); cur = []
                t = self._tb(s)
                blocks.append(t if isinstance(t, list) else [t])
            else:
                cur.append(s)
        if cur: blocks.append(cur)
        return blocks

    def _tb(self, s):
        if isinstance(s, ast.If):
            ts, es = self._ns(), self._ns()
            a = ast.Assign(
                targets=[ast.Name("__s__", ast.Store(), lineno=0, col_offset=0)],
                value=ast.IfExp(test=s.test, body=ast.Constant(ts),
                                orelse=ast.Constant(es), lineno=0, col_offset=0),
                lineno=0, col_offset=0)
            return a
        if isinstance(s, ast.While):
            ls, es = self._ns(), self._ns()
            return ast.Assign(
                targets=[ast.Name("__s__", ast.Store(), lineno=0, col_offset=0)],
                value=ast.IfExp(test=s.test, body=ast.Constant(ls),
                                orelse=ast.Constant(es), lineno=0, col_offset=0),
                lineno=0, col_offset=0)
        if isinstance(s, ast.For):
            ia = ast.Assign(
                targets=[ast.Name("__i__", ast.Store(), lineno=0, col_offset=0)],
                value=ast.Call(func=ast.Name("iter", ast.Load(), lineno=0, col_offset=0),
                               args=[s.iter], keywords=[], lineno=0, col_offset=0),
                lineno=0, col_offset=0)
            tb = [ast.Assign(targets=[s.target],
                             value=ast.Call(func=ast.Name("next", ast.Load(), lineno=0, col_offset=0),
                                            args=[ast.Name("__i__", ast.Load(), lineno=0, col_offset=0)],
                                            keywords=[], lineno=0, col_offset=0),
                             lineno=0, col_offset=0)]
            eh = ast.ExceptHandler(type=ast.Name("StopIteration", ast.Load(), lineno=0, col_offset=0),
                                   name=None, body=[ast.Break(lineno=0, col_offset=0)],
                                   lineno=0, col_offset=0)
            ts = ast.Try(body=tb, handlers=[eh], orelse=[], finalbody=[], lineno=0, col_offset=0)
            wn = ast.While(test=ast.Constant(True), body=[ts]+s.body, orelse=[], lineno=0, col_offset=0)
            return [ia, self._tb(wn)]
        return s

    def _dispatch(self, blocks, sv_name):
        sv = ast.Name(sv_name, ast.Load(), lineno=0, col_offset=0)
        d = [ast.If(
            test=ast.Compare(left=sv, ops=[ast.Eq()], comparators=[ast.Constant(0)],
                             lineno=0, col_offset=0),
            body=[ast.Assign(targets=[ast.Name(sv_name, ast.Store(), lineno=0, col_offset=0)],
                             value=ast.Constant(1), lineno=0, col_offset=0)],
            orelse=[], lineno=0, col_offset=0)] if blocks else []
        for idx, block in enumerate(blocks, 1):
            bs = list(block)
            if not any(isinstance(s, (ast.Return, ast.Break, ast.Continue, ast.Raise)) for s in bs):
                ns = idx + 1 if idx < len(blocks) else len(blocks) + 1
                bs.append(ast.Assign(targets=[ast.Name(sv_name, ast.Store(), lineno=0, col_offset=0)],
                                     value=ast.Constant(ns), lineno=0, col_offset=0))
            d.append(ast.If(
                test=ast.Compare(left=sv, ops=[ast.Eq()], comparators=[ast.Constant(idx)],
                                 lineno=0, col_offset=0),
                body=bs, orelse=[], lineno=0, col_offset=0))
        fs = len(blocks) + 1
        d.append(ast.If(
            test=ast.Compare(left=sv, ops=[ast.Eq()], comparators=[ast.Constant(fs)],
                             lineno=0, col_offset=0),
            body=[ast.Break(lineno=0, col_offset=0)], orelse=[], lineno=0, col_offset=0))
        return d


def _flatten_source(source: str) -> str:
    tree = ast.parse(source)
    t = _FlattenTransformer()
    ast.fix_missing_locations(t.visit(tree))
    if _HAS_UNPARSE:
        return ast.unparse(tree)
    try:
        import astor
        return astor.to_source(tree)
    except ImportError:
        raise RuntimeError("Python <3.9: install astor — pip install astor")

# ─────────────────────────────────────────────────────────────────────────────
#  EXPIRY ENGINE
# ─────────────────────────────────────────────────────────────────────────────

_DAYS_TMPL = '''\
import sys,os,threading,tempfile
from datetime import datetime as _dt
_EXP="{expiry_date}"
def _gt():
 try:
  import urllib.request,json
  with urllib.request.urlopen("http://worldtimeapi.org/api/timezone/Etc/UTC",timeout=3) as r:
   return _dt.strptime(json.loads(r.read())["datetime"][:10],"%Y-%m-%d").date()
 except Exception:
  return _dt.now().date()
def _ce():
 exp=_dt.strptime(_EXP,"%Y-%m-%d").date();now=_gt()
 tf=os.path.join(tempfile.gettempdir(),".exp_tok")
 try:
  with open(tf) as f:
   last=_dt.strptime(f.read().strip(),"%Y-%m-%d").date()
   if last>now: print("Script Expired. Contact Support.");os._exit(1)
 except Exception: pass
 with open(tf,"w") as f: f.write(now.strftime("%Y-%m-%d"))
 if now>exp: print("Script Expired. Contact Support.");os._exit(1)
 print(f"[✓] Active — {{(exp-now).days}} day(s) remaining.")
threading.Thread(target=_ce,daemon=True).start();_ce()
# ─── END EXPIRY ───
'''

_DT_TMPL = '''\
import sys,os,threading,tempfile
from datetime import datetime as _dt
_EXP="{expiry_datetime}"
def _gt():
 try:
  import urllib.request,json
  with urllib.request.urlopen("http://worldtimeapi.org/api/timezone/Etc/UTC",timeout=3) as r:
   return _dt.strptime(json.loads(r.read())["datetime"][:19],"%Y-%m-%dT%H:%M:%S")
 except Exception:
  return _dt.now()
def _ce():
 exp=_dt.strptime(_EXP,"%Y-%m-%d %I:%M %p");now=_gt()
 tf=os.path.join(tempfile.gettempdir(),".exp_tok_dt")
 try:
  with open(tf) as f:
   last=_dt.strptime(f.read().strip(),"%Y-%m-%d %H:%M:%S")
   if last>now: print("Script Expired. Contact Support.");os._exit(1)
 except Exception: pass
 with open(tf,"w") as f: f.write(now.strftime("%Y-%m-%d %H:%M:%S"))
 if now>exp: print("Script Expired. Contact Support.");os._exit(1)
 diff=exp-now
 print(f"[✓] Active — {{diff.days}}d {{diff.seconds}}s remaining.")
threading.Thread(target=_ce,daemon=True).start();_ce()
# ─── END EXPIRY ───
'''


def gen_days_expiry(days: int) -> tuple[str, dict]:
    expiry = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
    return _DAYS_TMPL.format(expiry_date=expiry), {"expiry_date": expiry, "days": days}


def gen_datetime_expiry(dt_str: str) -> tuple[str, dict]:
    expiry = datetime.strptime(dt_str, "%Y-%m-%d %I:%M %p")
    now    = datetime.now()
    diff   = expiry - now
    return (_DT_TMPL.format(expiry_datetime=dt_str),
            {"expiry_datetime": dt_str,
             "days_left":    max(diff.days, 0),
             "seconds_left": max(int(diff.total_seconds()), 0),
             "expired":      now > expiry})

# ─────────────────────────────────────────────────────────────────────────────
#  DECODER ENGINE  (12 methods)
# ─────────────────────────────────────────────────────────────────────────────

def _dec_base64(d: bytes):
    try:    return True, base64.b64decode(d.strip())
    except Exception as e: return False, f"Base64 error: {e}"

def _dec_base32(d: bytes):
    try:
        p = d.strip(); missing = len(p) % 8
        if missing: p += b"=" * (8 - missing)
        return True, base64.b32decode(p, casefold=True)
    except Exception as e: return False, f"Base32 error: {e}"

def _dec_base85(d: bytes):
    try:    return True, base64.b85decode(d.strip())
    except Exception:
        try:    return True, base64.a85decode(d.strip())
        except Exception as e: return False, f"Base85 error: {e}"

def _dec_hex(d: bytes):
    try:
        cleaned = re.sub(rb"\s+|\\x|0x|,", b"", d.strip())
        return True, binascii.unhexlify(cleaned)
    except Exception as e: return False, f"Hex error: {e}"

def _dec_xor(d: bytes):
    try:    return True, bytes(b ^ 0x42 for b in d)
    except Exception as e: return False, f"XOR error: {e}"

def _dec_zlib(d: bytes):
    try:    return True, zlib.decompress(d)
    except Exception:
        try:    return True, zlib.decompress(base64.b64decode(d.strip()))
        except Exception as e: return False, f"Zlib error: {e}"

def _dec_gzip(d: bytes):
    try:
        with gzip.open(io.BytesIO(d)) as f: return True, f.read()
    except Exception:
        try:
            with gzip.open(io.BytesIO(base64.b64decode(d.strip()))) as f: return True, f.read()
        except Exception as e: return False, f"Gzip error: {e}"

def _dec_marshal(d: bytes):
    try:
        obj = marshal.loads(d)
        buf = io.StringIO(); __import__("dis").dis(obj, file=buf)
        return True, buf.getvalue().encode()
    except Exception:
        try:
            obj = marshal.loads(base64.b64decode(d.strip()))
            buf = io.StringIO(); __import__("dis").dis(obj, file=buf)
            return True, buf.getvalue().encode()
        except Exception as e: return False, f"Marshal error: {e}"

def _dec_lambda(d: bytes):
    try:
        src = d.decode("utf-8", errors="replace")
        matches = re.findall(r'base64\.b64decode\(b?["\']([A-Za-z0-9+/=\n]+)["\']\)', src)
        if matches:
            parts = []
            for m in matches:
                try:    parts.append("# Decoded:\n" + base64.b64decode(m.strip()).decode("utf-8", errors="replace"))
                except Exception: pass
            if parts: return True, "\n\n".join(parts).encode()
        cleaned = re.sub(r"^(exec|eval)\s*\(", "", src.strip())
        cleaned = re.sub(r"\)\s*$", "", cleaned)
        if cleaned != src.strip(): return True, cleaned.encode()
        return False, "No recognisable lambda obfuscation found."
    except Exception as e: return False, f"Lambda error: {e}"

def _dec_rot13(d: bytes):
    try:    return True, codecs.decode(d.decode("utf-8", errors="replace"), "rot_13").encode()
    except Exception as e: return False, f"ROT13 error: {e}"

def _dec_url(d: bytes):
    try:    return True, urllib.parse.unquote_plus(d.decode("utf-8", errors="replace")).encode()
    except Exception as e: return False, f"URL error: {e}"

def _dec_html(d: bytes):
    try:    return True, html.unescape(d.decode("utf-8", errors="replace")).encode()
    except Exception as e: return False, f"HTML error: {e}"

DECODERS = {
    "base64": ("Base64",              _dec_base64),
    "base32": ("Base32",              _dec_base32),
    "base85": ("Base85",              _dec_base85),
    "hex":    ("Hex",                 _dec_hex),
    "xor":    ("XOR (key=0x42)",      _dec_xor),
    "zlib":   ("Zlib",                _dec_zlib),
    "gzip":   ("Gzip",                _dec_gzip),
    "marshal":("Marshal→Disassembly", _dec_marshal),
    "lambda": ("Lambda Deobfusc",     _dec_lambda),
    "rot13":  ("ROT13",               _dec_rot13),
    "url":    ("URL Decode",          _dec_url),
    "html":   ("HTML Entities",       _dec_html),
}

def decode_data(method: str, data: bytes):
    if method not in DECODERS: return False, f"Unknown method: {method}"
    _, fn = DECODERS[method]
    ok, result = fn(data)
    if ok and isinstance(result, str): result = result.encode()
    return ok, result

# ─────────────────────────────────────────────────────────────────────────────
#  MINIFILE ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def minify_source(source: str) -> tuple[str, dict]:
    orig_lines = len(source.splitlines())
    orig_size  = len(source.encode())
    result = None
    try:
        from python_minifier import minify
        result = minify(source, remove_literal_statements=True, remove_annotations=True,
                        remove_pass=True, remove_asserts=True, remove_debug=True,
                        remove_explicit_return_none=True, remove_object_base=True,
                        combine_imports=True, hoist_literals=False,
                        rename_globals=False, rename_locals=False, preserve_shebang=True)
    except ImportError:
        pass
    except Exception:
        pass
    if result is None:
        try:
            toks = list(tokenize.generate_tokens(io.StringIO(source).readline))
            out, prev_nl = [], False
            for tt, ts, *_ in toks:
                if tt == tokenize.COMMENT: continue
                if tt in (tokenize.NEWLINE, tokenize.NL):
                    if not prev_nl: out.append((tt, ts))
                    prev_nl = True
                else:
                    prev_nl = False; out.append((tt, ts))
            result = tokenize.untokenize(out)
        except Exception:
            result = "\n".join(l for l in source.splitlines() if l.strip() and not l.strip().startswith("#"))
    result = re.sub(r"\n{3,}", "\n\n", result).strip() + "\n"
    rs, rz = len(result.splitlines()), len(result.encode())
    return result, {"original_lines": orig_lines, "result_lines": rs,
                    "original_size": orig_size, "result_size": rz,
                    "reduction_pct": round((1 - rz / max(orig_size, 1)) * 100, 1)}

# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _uptime() -> str:
    s = int(time.time() - _START_TIME)
    h, r = divmod(s, 3600); m, s = divmod(r, 60)
    return f"{h}h {m}m {s}s"

async def _dl(message: Message, doc) -> bytes:
    file = await message.bot.get_file(doc.file_id)
    raw  = await message.bot.download_file(file.file_path)
    return raw.read()

# ─────────────────────────────────────────────────────────────────────────────
#  ROUTER & HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

router = Router()

# ── /start ───────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    await upsert_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    name = msg.from_user.first_name or "User"
    await msg.answer(
        f"👋 <b>Welcome, {name}!</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 <b>Multi-Tool Bot</b> — Premium Edition\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔹 <b>Available Tools:</b>\n"
        "  🔐 Premium Encryption — 6 cipher modes\n"
        "  ⏳ Expiry Generator — days or datetime\n"
        "  🔀 Logic Changer — control-flow flattening\n"
        "  🔓 Decoder Board — 12 decode methods\n"
        "  📦 MiniFile — compress Python code\n\n"
        "Choose a section below 👇",
        reply_markup=main_menu_kb()
    )

@router.callback_query(F.data == "menu:main")
async def cb_main(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer(); await state.clear()
    await call.message.edit_text(
        f"👋 <b>Welcome back!</b>\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 <b>Multi-Tool Bot</b> — Premium Edition\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\nChoose a section below 👇",
        reply_markup=main_menu_kb()
    )

@router.callback_query(F.data == "action:cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer("Cancelled."); await state.clear()
    await call.message.edit_text("❌ Action cancelled.", reply_markup=back_kb())

# ── Stats ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:stats")
async def cb_stats(call: CallbackQuery) -> None:
    await call.answer()
    uc = await count_users(); total = await count_ops()
    ec = await count_ops("encryption"); dc = await count_ops("decoder")
    xc = await count_ops("expiry");     lc = await count_ops("logic_changer")
    mc = await count_ops("minifile")
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"))
    await call.message.edit_text(
        f"📊 <b>Live Statistics</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users      : <code>{uc}</code>\n"
        f"⚙️  Total Operations : <code>{total}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔐 Encryptions      : <code>{ec}</code>\n"
        f"🔓 Decodings        : <code>{dc}</code>\n"
        f"⏳ Expiry Generated : <code>{xc}</code>\n"
        f"🔀 Logic Changes    : <code>{lc}</code>\n"
        f"📦 MiniFiles        : <code>{mc}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️  Uptime           : <code>{_uptime()}</code>\n"
        f"🤖 Version          : <code>v{BOT_VERSION}</code>",
        reply_markup=b.as_markup()
    )

# ── Help ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:help")
async def cb_help(call: CallbackQuery) -> None:
    await call.answer()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"))
    await call.message.edit_text(
        "ℹ️ <b>Help & Commands</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Commands:</b>\n  /start — Open main menu\n\n"
        "<b>Sections:</b>\n"
        "  🔐 <b>Encryption</b> — Upload .py → choose mode 1–6\n"
        "  ⏳ <b>Expiry</b> — Choose days or datetime expiry\n"
        "  🔀 <b>Logic Changer</b> — Upload .py → get flattened file\n"
        "  🔓 <b>Decoder</b> — Select method → send text/file\n"
        "  📦 <b>MiniFile</b> — Upload .py → get minified file\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Max file size: <code>5 MB</code>  |  Format: <code>.py</code> / <code>.txt</code>",
        reply_markup=b.as_markup()
    )

# ── Owner ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:owner")
async def cb_owner(call: CallbackQuery) -> None:
    await call.answer()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="💬 Open Chat with Owner", url=OWNER_CONTACT))
    b.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"))
    await call.message.edit_text(
        f"👑 <b>Owner & Support</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  Telegram : <code>{OWNER_USERNAME}</code>\n\n"
        f"💬 <b>Tap the button below</b> to open a\n"
        f"direct chat with the owner.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"For bugs, features or custom tools — DM anytime.",
        reply_markup=b.as_markup(),
        disable_web_page_preview=True
    )

# ─────────────────────────────────────────────────────────────────────────────
#  ENCRYPTION HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

_ENC_INTRO = (
    "🔐 <b>Premium Encryption</b>\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "  <b>Mode 1</b> — Base64 + Zlib\n"
    "  <b>Mode 2</b> — Marshal + Base64\n"
    "  <b>Mode 3</b> — Multi-Layer\n"
    "  <b>Mode 4</b> — XOR + Base64 (random key)\n"
    "  <b>Mode 5</b> — Control-Flow Flatten + Base64\n"
    "  <b>Mode 6</b> — Full Obfuscation + Anti-Debug\n\n"
    "Select a mode to begin 👇"
)

@router.callback_query(F.data == "menu:encryption")
async def cb_enc_menu(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer(); await state.clear()
    await call.message.edit_text(_ENC_INTRO, reply_markup=encryption_menu_kb())

@router.callback_query(F.data == "enc:intro")
async def cb_enc_intro(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.edit_text(_ENC_INTRO, reply_markup=encryption_menu_kb())

@router.callback_query(F.data.startswith("enc:mode:"))
async def cb_enc_mode(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    mode = int(call.data.split(":")[-1])
    await state.update_data(enc_mode=mode)
    await state.set_state(EncryptionStates.waiting_for_file)
    await call.message.edit_text(
        f"🔐 <b>Mode {mode} — {ENC_MODE_NAMES[mode]}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📤 Upload your <code>.py</code> file now.",
        reply_markup=cancel_kb()
    )

@router.message(EncryptionStates.waiting_for_file, F.document)
async def handle_enc_file(msg: Message, state: FSMContext) -> None:
    doc = msg.document
    if not doc.file_name.endswith(".py"):
        await msg.answer("⚠️ Only <code>.py</code> files accepted.", reply_markup=cancel_kb()); return
    if doc.file_size > MAX_FILE_SIZE:
        await msg.answer("⚠️ File too large (max 5 MB)."); await state.clear(); return
    d = await state.get_data(); mode = d.get("enc_mode", 1)
    pm = await msg.answer("⏳ Encrypting…")
    try:
        source    = (await _dl(msg, doc)).decode("utf-8", errors="replace")
        encrypted = encrypt_file(source, mode)
        out_name  = f"encrypted_mode{mode}_{doc.file_name}"
        out_bytes = encrypted.encode()
        await msg.answer_document(BufferedInputFile(out_bytes, filename=out_name),
            caption=(f"✅ <b>Encryption Complete</b>\n\n"
                     f"  Mode     : <code>{mode} — {ENC_MODE_NAMES[mode]}</code>\n"
                     f"  Original : <code>{len(source.encode()):,} bytes</code>\n"
                     f"  Encrypted: <code>{len(out_bytes):,} bytes</code>"))
        await log_op(msg.from_user.id, "encryption", {"mode": mode, "file": doc.file_name})
    except SyntaxError as e:
        await msg.answer(f"❌ Syntax error: <code>{e}</code>")
    except Exception as e:
        await msg.answer(f"❌ Failed: <code>{e}</code>")
        logger.error("Enc error: %s", e, exc_info=True)
    finally:
        await pm.delete(); await state.clear()
        await msg.answer("🔐 Encrypt another?", reply_markup=back_kb("menu:encryption"))

# ─────────────────────────────────────────────────────────────────────────────
#  EXPIRY HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:expiry")
async def cb_expiry_menu(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer(); await state.clear()
    await call.message.edit_text(
        "⏳ <b>Expiry Generator</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Generates a self-contained expiry block.\n"
        "When expired shows:\n"
        "<code>Script Expired. Contact Support.</code>\n\n"
        "Choose your expiry type 👇",
        reply_markup=expiry_menu_kb()
    )

@router.callback_query(F.data == "expiry:days")
async def cb_expiry_days(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer(); await state.set_state(ExpiryStates.waiting_for_days)
    await call.message.edit_text(
        "📅 <b>Days-Based Expiry</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Send number of days until expiry.\n"
        "Example: <code>30</code>",
        reply_markup=cancel_kb()
    )

@router.message(ExpiryStates.waiting_for_days, F.text)
async def handle_days(msg: Message, state: FSMContext) -> None:
    raw = msg.text.strip()
    if not raw.isdigit() or int(raw) <= 0:
        await msg.answer("⚠️ Send a positive number. Example: <code>30</code>"); return
    days = int(raw); code, info = gen_days_expiry(days)
    await msg.answer_document(
        BufferedInputFile(code.encode(), filename=f"expiry_{days}days.py"),
        caption=(f"✅ <b>Days Expiry Generated</b>\n\n"
                 f"  Days  : <code>{days}</code>\n"
                 f"  Expiry: <code>{info['expiry_date']}</code>\n\n"
                 "Prepend to top of your script.")
    )
    await log_op(msg.from_user.id, "expiry", info)
    await state.clear()
    await msg.answer("⏳ Generate another?", reply_markup=back_kb("menu:expiry"))

@router.callback_query(F.data == "expiry:datetime")
async def cb_expiry_dt(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer(); await state.set_state(ExpiryStates.waiting_for_datetime)
    await call.message.edit_text(
        "🕐 <b>Date & Time Based Expiry</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Format: <code>YYYY-MM-DD HH:MM AM/PM</code>\n"
        "Example: <code>2026-12-31 11:59 PM</code>",
        reply_markup=cancel_kb()
    )

_DT_PAT = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}\s+(AM|PM)$", re.I)

@router.message(ExpiryStates.waiting_for_datetime, F.text)
async def handle_datetime(msg: Message, state: FSMContext) -> None:
    raw = msg.text.strip()
    if not _DT_PAT.match(raw):
        await msg.answer("⚠️ Format: <code>YYYY-MM-DD HH:MM AM/PM</code>\nExample: <code>2026-12-31 11:59 PM</code>"); return
    try: datetime.strptime(raw, "%Y-%m-%d %I:%M %p")
    except ValueError as e: await msg.answer(f"⚠️ Invalid: <code>{e}</code>"); return
    code, info = gen_datetime_expiry(raw)
    status = "⚠️ ALREADY EXPIRED" if info["expired"] else "✅ Active"
    await msg.answer_document(
        BufferedInputFile(code.encode(), filename="expiry_datetime.py"),
        caption=(f"✅ <b>DateTime Expiry Generated</b>\n\n"
                 f"  Expiry : <code>{raw}</code>\n"
                 f"  Status : {status}\n"
                 f"  Days   : <code>{info['days_left']}</code>\n"
                 f"  Seconds: <code>{info['seconds_left']:,}</code>\n\n"
                 "Prepend to top of your script.")
    )
    await log_op(msg.from_user.id, "expiry", info)
    await state.clear()
    await msg.answer("⏳ Generate another?", reply_markup=back_kb("menu:expiry"))

# ─────────────────────────────────────────────────────────────────────────────
#  LOGIC CHANGER HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:logic")
async def cb_logic_menu(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer(); await state.clear()
    await state.set_state(LogicChangerStates.waiting_for_file)
    await call.message.edit_text(
        "🔀 <b>Logic Changer</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Converts control flow into state machines.\n"
        "Makes your code much harder to reverse.\n\n"
        "📤 Upload your <code>.py</code> file.",
        reply_markup=cancel_kb()
    )

@router.message(LogicChangerStates.waiting_for_file, F.document)
async def handle_logic_file(msg: Message, state: FSMContext) -> None:
    doc = msg.document
    if not doc.file_name.endswith(".py"):
        await msg.answer("⚠️ Only <code>.py</code> files accepted.", reply_markup=cancel_kb()); return
    if doc.file_size > MAX_FILE_SIZE:
        await msg.answer("⚠️ File too large (max 5 MB)."); await state.clear(); return
    pm = await msg.answer("⏳ Flattening control flow…")
    try:
        source   = (await _dl(msg, doc)).decode("utf-8", errors="replace")
        flat     = _flatten_source(source)
        out_name = f"flattened_{doc.file_name}"
        await msg.answer_document(
            BufferedInputFile(flat.encode(), filename=out_name),
            caption=(f"✅ <b>Logic Flattening Complete</b>\n\n"
                     f"  Original lines : <code>{len(source.splitlines())}</code>\n"
                     f"  Result lines   : <code>{len(flat.splitlines())}</code>")
        )
        await log_op(msg.from_user.id, "logic_changer", {"file": doc.file_name})
    except SyntaxError as e: await msg.answer(f"❌ Syntax error: <code>{e}</code>")
    except RuntimeError as e: await msg.answer(f"❌ Error: <code>{e}</code>")
    except Exception as e:
        await msg.answer(f"❌ Failed: <code>{e}</code>")
        logger.error("Logic error: %s", e, exc_info=True)
    finally:
        await pm.delete(); await state.clear()
        await msg.answer("🔀 Flatten another?", reply_markup=back_kb("menu:logic"))

# ─────────────────────────────────────────────────────────────────────────────
#  DECODER HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:decoder")
async def cb_decoder_menu(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer(); await state.clear()
    await call.message.edit_text(
        "🔓 <b>Decoder Board</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Base64 · Base32 · Base85 · Hex · XOR\n"
        "Zlib · Gzip · Marshal · Lambda\n"
        "ROT13 · URL Decode · HTML Entities\n\n"
        "Select a method 👇",
        reply_markup=decoder_menu_kb()
    )

@router.callback_query(F.data.startswith("dec:"))
async def cb_dec_method(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    method = call.data.split(":", 1)[1]
    if method not in DECODERS: await call.answer("Unknown method.", show_alert=True); return
    method_name, _ = DECODERS[method]
    await state.update_data(dec_method=method)
    await state.set_state(DecoderStates.waiting_for_input)
    await call.message.edit_text(
        f"🔓 <b>Method: {method_name}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Send your data as:\n"
        "  • A <code>.txt</code> or <code>.py</code> file, <b>or</b>\n"
        "  • A plain text message",
        reply_markup=cancel_kb()
    )

@router.message(DecoderStates.waiting_for_input, F.document)
async def handle_dec_file(msg: Message, state: FSMContext) -> None:
    doc = msg.document
    if doc.file_size > MAX_FILE_SIZE:
        await msg.answer("⚠️ File too large (max 5 MB)."); await state.clear(); return
    d = await state.get_data(); method = d.get("dec_method", "base64")
    mn, _ = DECODERS.get(method, (method, None))
    pm = await msg.answer("⏳ Decoding…")
    try:
        data     = await _dl(msg, doc)
        ok, res  = decode_data(method, data)
        if not ok:
            await msg.answer(f"❌ <b>Failed:</b> <code>{res.decode() if isinstance(res, bytes) else res}</code>"); return
        await msg.answer_document(
            BufferedInputFile(res, filename=f"decoded_{method}_{doc.file_name}"),
            caption=(f"✅ <b>Decoded with {mn}</b>\n\n"
                     f"  Input : <code>{len(data):,} bytes</code>\n"
                     f"  Output: <code>{len(res):,} bytes</code>")
        )
        await log_op(msg.from_user.id, "decoder", {"method": method, "file": doc.file_name})
    except Exception as e:
        await msg.answer(f"❌ Error: <code>{e}</code>")
        logger.error("Decoder error: %s", e, exc_info=True)
    finally:
        await pm.delete(); await state.clear()
        await msg.answer("🔓 Decode another?", reply_markup=back_kb("menu:decoder"))

@router.message(DecoderStates.waiting_for_input, F.text)
async def handle_dec_text(msg: Message, state: FSMContext) -> None:
    d = await state.get_data(); method = d.get("dec_method", "base64")
    mn, _ = DECODERS.get(method, (method, None))
    ok, res = decode_data(method, msg.text.strip().encode())
    if not ok:
        err = res.decode() if isinstance(res, bytes) else str(res)
        await msg.answer(f"❌ <b>Failed:</b> <code>{err}</code>"); await state.clear(); return
    if len(res) <= 3800:
        await msg.answer(f"✅ <b>Decoded with {mn}:</b>\n\n<code>{res.decode('utf-8', errors='replace')}</code>")
    else:
        await msg.answer_document(BufferedInputFile(res, filename=f"decoded_{method}.txt"),
                                  caption=f"✅ Decoded with {mn} — <code>{len(res):,} bytes</code>")
    await log_op(msg.from_user.id, "decoder", {"method": method})
    await state.clear()
    await msg.answer("🔓 Decode another?", reply_markup=back_kb("menu:decoder"))

# ─────────────────────────────────────────────────────────────────────────────
#  MINIFILE HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:minifile")
async def cb_mini_menu(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer(); await state.clear()
    await state.set_state(MiniFileStates.waiting_for_file)
    await call.message.edit_text(
        "📦 <b>MiniFile</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "  ✂️  Remove comments\n"
        "  🗑️  Remove blank lines\n"
        "  📝  Remove docstrings\n"
        "  📎  Combine imports\n"
        "  🔧  Strip debug / asserts\n"
        "  📏  Remove type annotations\n\n"
        "📤 Upload your <code>.py</code> file.",
        reply_markup=cancel_kb()
    )

@router.message(MiniFileStates.waiting_for_file, F.document)
async def handle_mini_file(msg: Message, state: FSMContext) -> None:
    doc = msg.document
    if not doc.file_name.endswith(".py"):
        await msg.answer("⚠️ Only <code>.py</code> files accepted.", reply_markup=cancel_kb()); return
    if doc.file_size > MAX_FILE_SIZE:
        await msg.answer("⚠️ File too large (max 5 MB)."); await state.clear(); return
    pm = await msg.answer("⏳ Minifying…")
    try:
        source      = (await _dl(msg, doc)).decode("utf-8", errors="replace")
        minified, s = minify_source(source)
        out_name    = f"mini_{doc.file_name}"
        await msg.answer_document(
            BufferedInputFile(minified.encode(), filename=out_name),
            caption=(f"✅ <b>MiniFile Complete</b>\n\n"
                     f"  Original : <code>{s['original_lines']} lines</code> (<code>{s['original_size']:,} bytes</code>)\n"
                     f"  Result   : <code>{s['result_lines']} lines</code> (<code>{s['result_size']:,} bytes</code>)\n"
                     f"  Reduced  : <code>{s['reduction_pct']}%</code>")
        )
        await log_op(msg.from_user.id, "minifile", {"file": doc.file_name, **s})
    except Exception as e:
        await msg.answer(f"❌ Failed: <code>{e}</code>")
        logger.error("MiniFile error: %s", e, exc_info=True)
    finally:
        await pm.delete(); await state.clear()
        await msg.answer("📦 Minify another?", reply_markup=back_kb("menu:minifile"))

# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    logger.info("Starting bot...")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    storage = MongoStorage.from_url(MONGODB_URI)
    dp = Dispatcher(storage=storage)

    await db_connect()

    me = await bot.get_me()
    logger.info("Bot ready: @%s", me.username)

    dp.include_router(router)

    logger.info("Polling started.")

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types()
        )
    finally:
        await db_close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
