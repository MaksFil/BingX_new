import re
import time
from decimal import Decimal, InvalidOperation
from typing import List, Optional

FLOAT_RE = re.compile(r"[-+]?\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d+)?")

def format_symbol_for_exchange(symbol: str, exchange_name: str) -> str:
    if '/' not in symbol and 'USDT' in symbol:
        symbol = symbol.replace('USDT', '/USDT')
    if exchange_name.lower() == 'bingx':
        return symbol.replace('/', '-')
    elif exchange_name.lower() == 'binance':
        return symbol.replace('/', '')
    return symbol

def normalize_symbol(raw_symbol: str) -> str:
    symbol = raw_symbol.strip().upper()
    symbol = re.sub(r'(/USDT)+', '/USDT', symbol)
    if not symbol.endswith('/USDT') and not symbol.endswith('USDT'):
        symbol = f"{symbol}/USDT"
    symbol = symbol.replace('USDT/USDT', '/USDT')
    return symbol

def normalize_number(num_str: str) -> str:
    if not isinstance(num_str, str):
        return "0"
    s = num_str.lower().replace("x", "").strip()
    has_comma = "," in s
    has_dot = "." in s
    if has_comma and has_dot:
        last_comma_pos = s.rfind(",")
        last_dot_pos = s.rfind(".")
        if last_comma_pos > last_dot_pos:
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma:
        s = s.replace(",", ".")
    try:
        float(s)
        return s
    except ValueError:
        return "0"

def parse_decimal(num_str: str) -> Optional[Decimal]:
    try:
        return Decimal(normalize_number(num_str))
    except InvalidOperation:
        return None

def extract_numbers(text: str) -> List[Decimal]:
    matches = FLOAT_RE.findall(text)
    numbers = []
    for m in matches:
        val = parse_decimal(m)
        if val is not None:
            numbers.append(val)
    return numbers
