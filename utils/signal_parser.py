import re
import requests
from decimal import Decimal, getcontext
from typing import List, Optional, Tuple
from dataclasses import dataclass, field
import statistics
import logging
import unicodedata

getcontext().prec = 20

@dataclass
class Signal:
    symbol: str
    side: str
    entry: Decimal = None
    entry_range: List[Decimal] = field(default_factory=list)
    targets: List[Decimal] = field(default_factory=list)
    sl: Optional[Decimal] = None
    leverage: Optional[int] = None
    is_market: bool = False
    raw_text: str = ""

    def __repr__(self):
        def fmt(d): return format(d.normalize(), 'f')
        entries = [fmt(e) for e in self.entry_range] if self.entry_range else "MARKET"
        tps = [fmt(t) for t in self.targets]
        sl = fmt(self.sl) if self.sl else "None"
        entry = format_decimal(self.entry) if self.entry else "MARKET"
        return f"<{self.side} {self.symbol} | E: {entry} | E_range: {entries} | TP: {tps} | SL: {sl} | {self.leverage}x>"

def format_decimal(d: Optional[Decimal]) -> str:
    """Форматирует Decimal для красивого отображения без научной нотации"""
    if d is None:
        return "None"
    
    d = d.normalize()
    
    if d == d.to_integral_value():
        return format(d, 'f')
    
    s = format(d, 'f')
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s

class SignalParser:
    def __init__(self):
        self.num_pattern = r'\b\d+(?:[\.,]\d+)*(?:[eE][+-]?\d+)?(?:\s*[kKмМ%])?(?!\d)'
        # Стоп-слова, которые не могут быть тикерами
        self.invalid_symbols = {
            'FREE', 'VIP', 'PAID', 'EXCLUSIVE', 'THE', 'WOLF', 'SCALPER', 
            'NOW', 'ZONE', 'ENTRY', 'LONG', 'SHORT', 'BUY', 'SELL', 'TARGET',
            'STOP', 'LIMIT', 'MARKET', 'PRICE', 'COIN', 'PAIR', 'SYMBOL', 'ASSET',
            'LEVERAGE', 'RISK', 'TRADE', 'SIGNAL', 'ALERT', 'UPDATE'
        }

    def get_current_price(self, symbol: str) -> Optional[Decimal]:
        try:
            api_symbol = symbol + "-USDT"
            url = f"https://open-api.bingx.com/openApi/swap/v2/quote/price?symbol={api_symbol}"
            response = requests.get(url, timeout=5)
            data = response.json()
            return Decimal(str(data['data']['price'])) if data.get('code') == 0 else None
        except: return None

    def _clean_decimal(self, val: str) -> Tuple[Decimal, bool]:
        is_pct = '%' in val
        mult = Decimal(1000) if any(x in val.upper() for x in ['K', 'К']) else \
               Decimal(1000000) if any(x in val.upper() for x in ['M', 'М']) else Decimal(1)
        clean = re.sub(r'[^\d\.,]', '', val).replace(',', '.')
        try: return Decimal(clean) * mult, is_pct
        except: return Decimal(0), False

    def _extract_numbers(self, text: str, is_tp: bool = False) -> List[Tuple[Decimal, bool]]:
        text = re.sub(r'\b\d{1,3}\s*[xX]\b', ' ', text)
        text = re.sub(r'(?m)^\s*\d+\s*[)\.\-]\s+', ' ', text)
        text = re.sub(r'(?:[\d]️⃣|🥇|🥈|🥉|🎯|➡️)\s*', ' ', text)
        text = re.sub(r'\b\d+\s*[)\.]\s+(?=\d)', ' ', text)

        found = re.findall(self.num_pattern, text)
        results = []
        for f in found:
            d, pct = self._clean_decimal(f)
            if d <= 0: continue
            if not pct and '.' not in f and d < 9:
                if len(found) > 1: continue
            results.append((d, pct))
        return results

    def _extract_symbol(self, text: str) -> Optional[str]:
        """Улучшенный метод поиска символа"""
        # Сначала ищем паттерны с явным разделителем /USD или /USDT
        sym_match = re.search(r'#?\s*([A-Z0-9]{1,12})\s*[/\(]\s*USD[T]?\b', text, re.I)
        if sym_match:
            candidate = sym_match.group(1).upper()
            if candidate not in self.invalid_symbols:
                return candidate
            
        sym_match = re.search(r'\b([A-Z0-9]{1,12})\s+USDT\b', text, re.I)
        if sym_match:
            candidate = sym_match.group(1).upper()
            if candidate not in self.invalid_symbols:
                return candidate
        
        # Поиск по ключевым словам (Pair: XAUUSD)
        sym_match = re.search(
            r'(?:Pair|Coin|Symbol|Name|Asset|Trading)[\s\:\-]*#?\$?\s*([A-Z0-9]{1,12})',
            text, re.I
        )
        if sym_match:
            candidate = sym_match.group(1).upper()
            if candidate not in self.invalid_symbols:
                return candidate
        
        # Поиск тикера с приставкой # или $ (#XAUUSD)
        sym_match = re.findall(r'[#$]([A-Z0-9]{1,12})\b', text, re.I)
        for candidate in sym_match:
            candidate = candidate.upper()
            if candidate not in self.invalid_symbols:
                return candidate
        
        # Поиск паттерна "SIDE SYMBOL" или "SYMBOL SIDE"
        # Но исключаем слова, которые часто встречаются в тексте
        side_pattern = r'\b(LONG|SHORT|BUY|SELL)\s+([A-Z0-9]{1,12})\b|([A-Z0-9]{2,12})\s+(LONG|SHORT|BUY|SELL)\b'
        sym_match = re.search(side_pattern, text, re.I)
        if sym_match:
            candidate = (sym_match.group(2) or sym_match.group(3)).upper()
            if candidate not in self.invalid_symbols:
                return candidate
        
        # Поиск по контексту - ищем тикер, который может быть рядом с ценовыми уровнями
        # Ищем что-то похожее на тикер в начале текста или после #/$
        lines = text.split('\n')
        for line in lines[:3]:  # Проверяем первые 3 строки
            # Ищем слово из 2-12 заглавных букв или цифр
            candidates = re.findall(r'\b([A-Z0-9]{1,12})\b', line.upper())
            for candidate in candidates:
                if (candidate not in self.invalid_symbols and 
                    not candidate.isdigit() and  # не чисто число
                    not candidate.endswith('X') and  # не плечо (20X)
                    len(candidate) >= 2):
                    return candidate
        
        return None
    
    def remove_outlier(self, tps, factor=5):
        """
        Убираем крайние TP, если они сильно отличаются от остальных.
        Смотрим сначала с конца списка.
        """
        tps = [Decimal(tp) for tp in tps]
        
        while len(tps) > 1:
            # Проверяем последний элемент
            last, rest = tps[-1], tps[:-1]
            median_rest = statistics.median(rest)
            if (median_rest != 0 and (last >= median_rest * factor or last <= median_rest / factor)) or last == 1:
                tps.pop(-1)
                continue

            # Если ни первый, ни последний не выбросили — всё ок
            break

        return tps


    def parse(self, text: str) -> Optional[Signal]:
        try:
            if not text:
                return None
            if text.strip().upper().startswith(("SET TP", "SET SL")):
                logging.info("ℹ️ Пропуск повідомлення оновлення (SET TP/SL)")
                return None
            logging.info("=" * 60)
            logging.info(f"\nSignal parse: {text}\n")
            logging.info("=" * 60)
            if not text or len(text) < 5:
                return None

            text = unicodedata.normalize('NFKD', text)

            # --- SYMBOL ---
            symbol = self._extract_symbol(text)
            if not symbol:
                return None

            symbol = re.sub(r'USDT$|USD$', '', symbol)

            if symbol in self.invalid_symbols or symbol.isdigit():
                return None

            # --- SIDE ---
            side_text = text.upper()
            if re.search(r'\b(SHORT|SELL|🔴|ШОРТ|📉|DOWN)\b', side_text):
                side = 'SHORT'
            else:
                side = 'LONG'

            is_market = bool(re.search(r'(Market|CMP|Now|Enter at|Current|@)', text, re.I))

            # --- CLEAN TEXT ---
            clean_text = re.sub(r'[()➡️\[\]\-\–\—/]', ' ', text)

            entry_m = r'(Entry|Limit|Вход|Zon|Entries|@)'
            tp_m = r'(Take|Target|TP|Тейк)'
            sl_m = r'(Stop|SL|Стоп|ST\s*\:)'

            markers = []
            for m in re.finditer(entry_m, clean_text, re.I):
                markers.append((m.start(), 'entry'))
            for m in re.finditer(tp_m, clean_text, re.I):
                markers.append((m.start(), 'tp'))
            for m in re.finditer(sl_m, clean_text, re.I):
                markers.append((m.start(), 'sl'))

            markers.sort()

            entries_raw, tps_raw, sl_val = [], [], None

            # --- EXTRACTION ---
            if not markers:
                nums = self._extract_numbers(clean_text)
                if len(nums) >= 3:
                    entries_raw = [nums[0]]
                    tps_raw = nums[1:-1]
                    sl_val = nums[-1][0]
            else:
                if markers[0][1] != 'entry' and not is_market:
                    entries_raw = self._extract_numbers(clean_text[:markers[0][0]])

                for i in range(len(markers)):
                    start, role = markers[i]
                    end = markers[i+1][0] if i+1 < len(markers) else len(clean_text)
                    chunk = clean_text[start:end]
                    nums = self._extract_numbers(chunk, is_tp=(role == 'tp'))

                    if role == 'entry':
                        entries_raw.extend(nums)
                    elif role == 'tp':
                        tps_raw.extend(nums)
                    elif role == 'sl':
                        # Убираем нумерацию типа "1) "
                        cleaned_chunk = re.sub(r'(?m)^\s*\d+\s*[)\-]\s*', ' ', chunk)

                        # Убираем проценты типа 3-5%
                        cleaned_chunk = re.sub(r'\d+\s*-\s*\d+\s*%', ' ', cleaned_chunk)
                        cleaned_chunk = re.sub(r'\d+\s*%', ' ', cleaned_chunk)

                        nums = self._extract_numbers(cleaned_chunk)

                        if nums:
                            # Берём ПЕРВОЕ найденное число
                            sl_val = nums[0][0]

            # --- LEVERAGE ---
            lev_match = re.search(r'(\d{1,3})\s*[xX]\b', text)
            leverage = int(lev_match.group(1)) if lev_match else 25

            # --- BUILD FINAL ---
            final_entries = [e[0] for e in entries_raw][:2]
            final_targets = [e[0] for e in tps_raw]

            # ==========================================================
            # 🔥 FALLBACK: если TP не нашли, но есть Entry и SL
            # (формат как в JELLYJELLY — тейки просто строками)
            # ==========================================================
            if final_entries and not final_targets and sl_val:
                entry_match = re.search(r'(Entry[^\n]*)', clean_text, re.I)
                sl_match = re.search(r'(Stop[^\n]*)', clean_text, re.I)

                if entry_match and sl_match and sl_match.start() > entry_match.end():
                    between_text = clean_text[entry_match.end():sl_match.start()]
                    extra_nums = self._extract_numbers(between_text)

                    for num, _ in extra_nums:
                        if side == "LONG" and num > final_entries[0]:
                            final_targets.append(num)
                        elif side == "SHORT" and num < final_entries[0]:
                            final_targets.append(num)

            clean_text_for_tp = re.sub(r'Trading risk.*?\d+\s*-\s*\d+%', '', text, flags=re.I)

            tp_percent_match = re.search(
                r'(?:TP|Target|Take\s*Profit)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*%?\s*[-–]\s*(\d+(?:\.\d+)?)\s*%?',
                clean_text_for_tp, re.I
            )

            if tp_percent_match:
                tp1_pct = Decimal(tp_percent_match.group(1))
                tp2_pct = Decimal(tp_percent_match.group(2))
                if(len(final_entries) > 0):
                    entry_price = final_entries[0]
                else:
                    currency_price = self.get_current_price(symbol)
                    entry_price = currency_price
                
                factor = Decimal(1) / Decimal(leverage)
                final_targets = [
                    entry_price * (1 + tp1_pct * factor / 100),
                    entry_price * (1 + tp2_pct * factor / 100)
                ]

            # Ограничение тейков
            final_targets = final_targets[:10]

            tp_set = set(final_targets)
            final_entries = [e for e in final_entries if e not in tp_set]

            if final_entries:
                final_entries = self.remove_outlier(final_entries)
            
            final_targets = self.remove_outlier(final_targets)

            entry = None
            if len(final_entries) > 1:
                entry = (final_entries[0] + final_entries[1]) / 2
            elif len(final_entries) == 1:
                entry = final_entries[0]

            signal = Signal(
                symbol=symbol,
                side=side,
                entry = entry,
                entry_range=final_entries,
                targets=final_targets,
                sl=sl_val,
                leverage=leverage,
                is_market=is_market,
                raw_text=text
            )

            logging.info("=" * 60)
            logging.info("✅ СИГНАЛ УСПЕШНО РАСПОЗНАН")
            logging.info(f"   Symbol: {signal.symbol}")
            logging.info(f"   Side: {signal.side.upper()}")
            logging.info(f"   Entry: {format_decimal(signal.entry) if signal.entry else 'MARKET'}")
            if signal.entry_range:
                if len(signal.entry_range) == 1:
                    logging.info(f"   Entry Range: ({format_decimal(signal.entry_range[0])})")
                else:
                    logging.info(f"   Entry Range: ({format_decimal(signal.entry_range[0])}, {format_decimal(signal.entry_range[1])})")

            if signal.targets:
                tp_parts = [f"TP{i+1}: {format_decimal(tp)}" for i, tp in enumerate(signal.targets)]
                logging.info(f"   {', '.join(tp_parts)}")
            else:
                logging.info("   TP: None")

            logging.info(f"   SL: {format_decimal(signal.sl)}")
            logging.info(f"   Leverage: {signal.leverage}x")
            logging.info("=" * 60)

            return signal
        
        except Exception as e:
            logging.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА ПАРСИНГА: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return None
    
# --- ТЕСТ ПАРСЕРА ---
if __name__ == "__main__":
    parser = SignalParser()

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        filename='signal_parser.log',  # имя файла для логов
        filemode='a',                  # 'a' = добавлять, 'w' = перезаписать
        encoding='utf-8',              # сохраняем в UTF-8
        force=True
    )
        
    test_signals = [
        """
        $BTC  Next Target : 134K$

            #BTC  ZON LONG : 

            1) 105K$
            2) 102K$

            Target : 

            1) 125K$
            2) 130K$
            3) 133K$

            ST : 100K$
        """,

        """
            🙈 Exclusive #VIP Signal 🙈

            Pair: #COAI/USDT  
            Position :  Long 🟢  
            Leverage : Cross 10x 
            Entry: 9.95 - 9.50

            Targets
            1) 🎯 10.40
            2) 🎯 10.90
            3) 🎯 11.40
            4) 🎯 11.80
            5) 🎯 …🙉

            🚨Stop Loss: 9

            Risk Management: Enter in parts, use 2-3% of your portfolio
        """,
        """
            ✨ Project Type :- SCALP✨

            🌈PAIR:- RVV
            ⚡️ Direction : Long
            🛠 Leverage: 50x Cross

            💘 Entrys : 0.01130 - 0.01090

            🏆 Targets:-

            🥇 0.01210
            🥈 0.01300
            🥉 0.01500

            🚫 Stop-Loss:   
              0.01050
            (15 Minutes candle closing Below)

            🛡Account Usage:- 1-2%
            (According To your Risk Setting) 


            Published By - @James_Wilhelm36
        """,
        """
            ✨ Project Type :- SCALP✨

            🌈PAIR:- xpin
            ⚡️ Direction : Long
            🛠 Leverage: 50x Cross

            💘 Entrys : 0.003800 - 0.003680

            🏆 Targets:-

            🥇 0.00400
            🥈 0.004300
            🥉 0.004600

            🚫 Stop-Loss:   
              0.003580
            (15 Minutes candle closing Below)

            🛡Account Usage:- 1-2%
            (According To your Risk Setting) 


            Published By - @James_Wilhelm36
        """,
        """
            💥 LONG SIGNAL ALERT: #AIA/USDT 💥

            ⛈ Leverage: Cross 25x – 50x
            🎯 Entry: 1.0439

            📈 Take Profits:
            ➡️ TP1 →1.0640
            ➡️ TP2 →1.1050
            ➡️ TP3 →1.1850


            ❌ Stop Loss: 0.9844

            ⚡️ Risk Management: Use only 3% – 7% of your portfolio.
            📍 Stay disciplined — precision wins profitable
        """,
        """
            📍Coin : #MITO/USDT

            🔴 SHORT 

            👉 Entry: 0.1248 - 0.1272

            🌐 Leverage: 20x

            🎯 Target 1: 0.1236
            🎯 Target 2: 0.1224
            🎯 Target 3: 0.1212
            🎯 Target 4: 0.1200
            🎯 Target 5: 0.1188
            🎯 Target 6: 0.1175

            ❌ StopLoss: 0.1310
        """,
        """
        #AIA/USDT LONG NOW ⚡️

        ➡️ Entry Market Price 1.0420

        👑 TP(1.0685- 1.1030-1.1650-1.2888)

        ⛔️ SL = (0.9710)
        """,
        """
            #NFP round2

            Entry: $0.044
            SL: $0.03491

            TP1:0.04582
            TP2:0.04800
            TP3:0.05237
            TP4:0.06110
            TP5:0.06982
            TP6:0.08728
        """,
        """
            ACTIVE ♻️ PAID CHANNEL SIGNALS 

            #MLN/USDT {Long} ✅


            Leverage: 50x


            🎗️Entry Targets: 5.428


            Take-Profit
            1) 5.651
            2) 5.908
            3) 6.217
            4) 6.491
            5) 6.714


            🎗️Stop-Loss: 5.325
        """,
        """
            #MITO

            Entry: $0.12574
            SL: $0.10059

            TP1:0.13203
            TP2:0.13831
            TP3:0.15089
            TP4:0.17604
            TP5:0.20118
            TP6:0.25148
        """,
        """
            Long ENAUSDT 

            Order Type : Market Price 

            Leverage : 10X

            TP : 50% - 100%

            SL : 0.4439

            Apply Proper Risk Management
        """,


        """
            #EDU SHORT SETUP 

            Target 1: $0.1635
            Target 2: $0.1615
            Target 3: $0.1580

            STOP : $0.1730
        """,
        """
            ✨SOL/USDT

            🎗 Trade Type = SHORT 🔴

            ⭐️ Leverage :- 20x

            ⚡️ Entry = [ 183.84 TO 183.38 ]

            ❌ StopLoss :- 190.50

            ✅ Take profit = [ 181.93, 179.83, 178.21, 176.39, 174.08, 172.02 ]
        """,
        """
            💎 #Free Signal

            🔴 Short

            Pair: #KNC/USDT

            📊 Entry Price: 

            1) 0.29170
            2) 0.30045

            📈 Targets:

            1) 0.28999
            2) 0.28383
            3) 0.27767
            4) 0.27151

            Stop Loss: 0.31007

            Leverage: 10x-20x
        """,
        """
            👍THE WOLF SCALPER👍

            ✔️COIN NAME: MLN(USDT)

            LEVERAGE: 75x

            🔼TRADE TYPE: LONG 📈

            ✔️ENTRY PRICE (8.284-7.850)

            ☄️TAKE-PROFITS 

            1️⃣ 8.400

            2️⃣ 8.700

            3️⃣ 9.00

            STOP LOSS:  7.500
        """,
        """
            💥 Futures (Free Signal)

            🔴 SHORT

            #LQTY/USDT

            Entry zone : 0.553831 - 0.537700

            Take Profits : 

            0.534984
            0.518772
            0.502561
            0.486349
            0.470137

            Stop loss :0.575339

            Leverage: 10x
        """,
        """
            ⚡️$FIL/USDT { 25X }

            📈 DIRECTION : { SHORT }

            🔍 ENTER ➡️1.510 - 1.506

            💥 TARGETS 💯 ✨

            ➡️1.493
            ➡️1.478
            ➡️1.461
            ➡️1.445
            ➡️1.429
            ➡️1.407

            🔴STOPLOSS : 1.598
        """,
        """
            #TAO/USDT  📊

            Signal type: LONG 

            Entry : 388.56


            Take Profit Targets:

            Target 1 - 396.00
            Target 2 - 404.00
            Target 3 - 408.00
            Target 4 - 412.00
            Target 5 - 415.05

            📊leverege: 50x


            🚨Stop Loss: 386.90
        """,
        """
            LONG $COAIUSDT 

            ENTER: MARKET ORDER 

            TP:12.2883

            SL: 5.8740

            Apply properly risk management
        """,
        """
            DOGE/USDT
            Long
            20X. To 150X

            TP 0.2035/0.2124/2290

            SL   0.19

            Manage your risk properly.
            USE ONLY 1% of wallet
        """,
        """
            $tao long 
            350–393

            Sl 300

            Tp 410 430 450 470 500 600 700 800 900 1000
        """,

        """
            👍THE WOLF SCALPER👍

            ✔️COIN NAME: H(USDT)

            LEVERAGE: 75x

            🔼TRADE TYPE: LONG 📈

            ✔️ENTRY PRICE (0.1550-0.1500)

            ☄️TAKE-PROFITS 

            1️⃣ 0.1585

            2️⃣ 0.1625

            3️⃣ 0.1676

            STOP LOSS:  0.1465
        """,
        """
            SHORT 🔴

            APEX/USDT

            LIMIT ORDER (1.3051)

            SL 1.3634

            TP 1.0821

            USE GOOD RISK MANAGEMENT

            NO GREEDY

            PATIENT IS THE KEY
        """,
        """
            🔥 RFD Indicator 🔥

            15 Minutes Timeframe

            ✅ LONG

            #LAB/USDT

            Entry zone : 0.1710595 - 0.1763500

            Take Profits : 

            0.1772229
            0.1824869
            0.1877510
            0.1930150
            0.1982791

            Stop loss :0.1640055

            Leverage: 10x

            🆔 @JAMES_CRYPT11
        """,
        """
            #STBL/USDT  📊

            Signal type: LONG 

            Entry : 0.08166


            Take Profit Targets:

            Target 1 - 0.08600
            Target 2 - 0.08800
            Target 3 - 0.09000
            Target 4 - 0.09200
            Target 5 - 0.09458

            📊leverege: 50x


            🚨Stop Loss: 0.08000
        """,
        """
            Snx long

            1.2-1.43

            Sl 1

            Tp 1.47 1.55 1.6 1.7 1.8 1.9 2 2.5 3 3.5 4
        """,
        """
            #H/USDT LONG NOW ⚡️

            ➡️ Entry Market Price 0.1620

            👑 TP(0.1650-0.1690-0.1739-0.1799)

            ⛔️ SL = (0.1500)
        """,
        """
            #Free

            #Futures_signal

            🔴 SHORT

            #CHR/USDT

            Entry : 

            1) 0.0733
            2) 0.0754

            Targets : 

            1) 0.0728
            2) 0.0713
            3) 0.0697
            4) 0.0682

            🛑 Stop : 0.0779

            Leverage : 10x (isolated)

            @JAMES_CRYPT11
        """,
        """
            Coin #AUCTION/USDT 

            Position: LONG 

            Leverage:  Cross25X

            Entries: 8.45 - 8.20

            Targets: 🎯 8.70, 8.95, 9.20, 9.45, 9.70

            Stop Loss: 7.95

            📌 Published by

            @JAMES_CRYPT11
        """,
        """
            $ARCUSDT  (🟢 Long  )                 

            
            Limits:  CMP/0.01350

            Target :-➡️   0.01482
                            ➡️   0.01579
                            ➡️   0.01674
                            ➡️   0.01841


            Stop loss 🔴 0.01305
        """,
        """
            LONG 🟢

            COAI/USDT

            LIMIT ORDER (4.9317)

            SL 3.4115🔴

            TP 12.5218🟢

            USE GOOD RISK MANAGEMENT

            NO GREEDY

            PATIENT IS THE KEY
    """,
    
    """
        XAUUSD BUY NOW @ 4252.5-4248

        Sl : 4246

        TP1 : 4263
        TP2 : Open

        Use Proper Lot Size Okay🥂
    """,
    """
        ⚡️HYPE/USDT ⚡️

        LONG 🟢

        💥Leverage: 10x

        Entry Limit : - 38.40-37.50

        📌Take-Profit Targets:

        1)  39.80
        2) 41$
        3) 43$

        ❌ SL: 36.6$
    """,
    """
        ✅Entry   0.3460 - 0.3300

        (LONG USELESS USDT  5-20x🆘)

        🏹 Target 1 $0.3495
        🏹Target 2. $0.3530
        🏹Target 3  $0.3565
        🏹Target 4  $0.3602
        🏹Target 5  $0.3640
        🏹Target 6  $0.3680

        🚫Stop loss - 0.3210
    """,
    """
        ✅XAUUSD BUY 4256/4252

        TP¹ 4258
        TP² 4260
        TP³ 4262
        TP⁴ 4264
        TP⁵ 4266


        SL_ 4248
    """,
    """
        🟢 Long

        🔰 Price Action : 🥇 Ember Strategy

        #EDU/USDT

        Entry : 

        1) 0.1666000
        2) 0.161602

        Targets : 

        1) 0.1675567
        2) 0.1710371
        3) 0.1745175
        4) 0.1779979

        🛑 Stop : 0.1561042

        Leverage : 10x (isolated)

        @James_Wilhelm36
    """,
    """
        ✨MIRA/USDT

        🎗 Trade Type = LONG 🟢

        ⭐️ Leverage :- 20x

        ⚡️ Entry = [ 0.3122 TO 0.3114 ]

        ❌ StopLoss :- 0.2970

        ✅ Take profit = [ 0.3150, 0.3181, 0.3211, 0.3248, 0.3278, 0.3314 ]
    """,
    """
        LONG TRADE SETUP🔝

        COIN: #AIA/USDT

        ENTRY: 1.0238

        LEVERAGE: 50X

        TARGET 🎯 
        💰1.0458
        💰1.0683
        💰1.0885
        💰1.1104
        💰1.1325

        ⛔️ STOP LOSS : 1.9971

        Apply proper risk 🔉management, overtrading can lead to poor decisions and unnecessary losses🚨

        @James_Wilhelm36
    """,
    """
        MTC Indicator 🔥

        15 Minutes Timeframe

        🔴 SHORT

        #COAI/USDT

        Entry zone : 6.12232 - 5.9440000

        Take Profits : 

        5.9139828
        5.7347712
        5.5555596
        5.376348
        5.1971364

        Stop loss :6.36008

        Leverage: 10x

        🆔 @James_Wilhelm36
    """,
    """
        📩 #STRKUSDT 30m | Mid-Term
        📉 Long Entry Zone: 0.1221-0.1154

        🎯 - Strategy Accuracy:  91.41%
        Last 5 signals:  100.0%
        Last 10 signals:  95.0%
        Last 20 signals:  85.0%

        ⏳ - Signal details:
        Target 1:  0.1245
        Target 2:  0.1270
        Target 3:  0.1294
        Target 4:  0.1368
        _
        🧲Trend-Line: 0.1154
        ❌Stop-Loss: 0.1131
    """,
    """
        CoinPulse VIP Trade 

        Pair: HYPE/USDT #LONG
        Leverage: cross 25x

        Entry 
        38.4

        Targets : 43
        Stop loss : 36.1
    """,

    """
        #SKATE

        Entry: $0.04511
        SL: $0.03609

        TP1:0.04737
        TP2:0.04962
        TP3:0.05413
        TP4:0.06315
        TP5:0.07218
        TP6:0.09022
    """,
    """
        ⚡️$LSK/USDT { 25X }

        📈 DIRECTION : { SHORT }

        🔍 ENTER ➡️0.2266 - 0.2260

        💥 TARGETS 💯 ✨

        ➡️0.2240
        ➡️0.2221
        ➡️0.2193
        ➡️0.2164
        ➡️0.2146
        ➡️0.2119

        🔴STOPLOSS : 0.2385
    """,
    """
        👍THE WOLF SCALPER👍

        ✔️COIN NAME: 1000FLOKI(USDT)

        LEVERAGE: 75x

        🔼TRADE TYPE: LONG 📈

        ✔️ENTRY PRICE (0.08770-0.08420)

        ☄️TAKE-PROFITS 

        1️⃣ 0.08950

        2️⃣ 0.09200

        3️⃣ 0.09500

        STOP LOSS:  0.08080
    """,
    """
        🟢 LONG  - $SYN - RISK ORDER - SMALL VOL

        - Entry: 0.0862
        - SL: 0.0794
        🎯 TP: 0.2141

        ⚠️ Disclaimer
        This is not financial advice. Trade at your own risk.
    """,
    """
        🟢 LONG  - $H - RISK ORDER - SMALL VOL

        - Entry: 0.117765
        - SL: 0.103110
        🎯 **TP: 0.238600**

        ⚠️ Disclaimer
        This is not financial advice. Trade at your own risk.
    """,
    """
        🟢 LONG  - $API3 - RISK ORDER - SMALL VOL

        - Entry: 0.7267
        - Entry limit: 0.6927
        - SL: 0.6737
        🎯 **TP:1.0255**

        ⚠️ Disclaimer
        This is not financial advice. Trade at your own risk.
    """,
    """
        🟢 LONG  - $MORPHO - RISK ORDER - SMALL VOL

        - Entry: 2.1568
        - Entry limit: 2.0638
        - SL: 1.9976
        🎯 **TP: 2.8656**

        ⚠️ Disclaimer
        This is not financial advice. Trade at your own risk.
    """,
    """
        🟢 LONG  - $BROCCOLI714 - RISK ORDER - SMALL VOL

        - Entry: 0.02613
        - Entry limit: 0.02443
        - SL: 0.02357
        🎯 **TP: 0.04002**

        ⚠️ Disclaimer
        This is not financial advice. Trade at your own risk.
    """,
    """
        🚨 SIGNAL ALERT 🚨

        #UB/USDT (25x LONG)

        🎯 ENTRY: 0.039/ 0.038

        🎯 TARGETS: 0.040/ 0.042/ 0.045

        ❌ STOP LOSS: 0.036

        🔐 Signal Powered by @MaheeCrypto
    """,
    """
        🚨 SIGNAL ALERT 🚨

        #EDEN/USDT (25x LONG)

        🎯 ENTRY: 0.160/ 0.155

        🎯 TARGETS: 0.164/ 0.173/ 0.195

        ❌ STOP LOSS: 0.140

        🔐 Signal Powered by @MaheeCrypto
    """,
    """
        🚨 SIGNAL ALERT 🚨

        #ZEC/USDT (25x LONG)

        🎯 ENTRY: 228/ 218

        🎯 TARGETS: 235/ 247/ 260

        ❌ STOP LOSS: 209

        🔐 Signal Powered by @MaheeCrypto
    """,

    """
        Pair: 1000RATS/USDT
        #LONG
        Leverage: 20x

        Entry Zone: 0.02880- 0.028

        Targets:
        1) 0.02950
        2) 0.03050
        3) 0.033

        Stoploss: 0.026
    """,
    """
        LONG #币安人生 50X

        TAKE ENTRY 0.3420

        SET TP 1 0.3500

        SET TP 2 0.3610

        SET SL 0.3210
    """,
    """
        LONG #RIVER 50X

        TAKE ENTRY 4.600

        SET TP 1 4.700

        SET TP 2 4.900

        SET SL 4.300
    """,
    """
        👍THE WOLF SCALPER👍

        ✔️COIN NAME: EVAA(USDT)

        LEVERAGE: 75x

        🔼TRADE TYPE: LONG 📈

        ✔️ENTRY PRICE (4.2725-4.1450)

        ☄️TAKE-PROFITS 

        1️⃣ 4.3900

        2️⃣ 4.5300

        3️⃣ 4.7200

        STOP LOSS:  3.9600

        #WE_STAND_WITH_PALESTINE

        REACTIONS?
    """,
    """
        LONG #SNX 50X

        TAKE ENTRY 1.768

        SET TP 1 1.810

        SET TP 2 1.870

        SET SL 1.670
    """,
    """
        Coin #ASTER/USDT 

        Position: LONG 

        Leverage:  Cross25X

        Entries: 1.69 - 1.60

        Targets: 🎯 1.79, 1.89, 1.99, 2.09, 2.20

        Stop Loss: 1.51

        📌 Published by @Liam_Ricardo1
    """,
    """
        Coin #AIA/USDT 

        Position: SHORT 

        Leverage:  Cross25X

        Entries: 1.53 - 1.56

        Targets: 🎯 1.49, 1.45, 1.41, 1.37, 1.33

        Stop Loss: 1.61

        📌 Published by @Liam_Ricardo1
    """,
    """
        Coin #ZEC/USDT 

        Position: LONG 

        Leverage:  Cross25X

        Entries: 180 - 175

        Targets: 🎯 185, 190, 195, 200, 205

        Stop Loss: 170

        📌 Published by @Liam_Ricardo1
    """,
    """
        Coin #MORPHO/USDT 

        Position: SHORT 

        Leverage:  Cross50X

        Entries: 1.970 - 1.995

        Targets: 🎯 1.945, 1.920, 1.895, 1.870, 1.845

        Stop Loss: 2.02

        📌 Published by @Liam_Ricardo1
    """,
    """
        Coin #ETH/USDT 

        Position: LONG 

        Leverage:  Cross100X

        Entries: 3900 - 3875

        Targets: 🎯 3925, 3950, 3975, 4000, 4025

        Stop Loss: 3850

        📌 Published by @Liam_Ricardo1
    """,

    """
        🚀Заходим SOL long 25x

        Вход: по рынку 
        Тейк: 180.46, 182.14, 188.43
        Стоп: 171.37

        Фиксируем 50% на первой цели, 25% на второй цели и 25% на оставшейся и после первой цели ставим стоп в без убыток
        Торгуем на 📈BYBIT (https://partner.bybit.com/b/bonus59) и 🔀BingX (https://bingx.com/partner/QCZQR3/1Okf7a)
    """,
    """
        🚀Заходим TIA long 25x

        Вход: по рынку 
        Тейк: 1.0136 / 1.0231 / 1.0619
        Стоп: 0.9620

        Фиксируем 50% на первой цели, 25% на второй цели и 25% на оставшейся и после первой цели ставим стоп в без убыток

        Торгуем на 📈BYBIT (https://partner.bybit.com/b/bonus59) и 🔀BingX (https://bingx.com/partner/QCZQR3/1Okf7a)
    """,
    """
        🚀Заходим NEAR long 25x

        Вход: по рынку 
        Тейк: 2.180, 2.203, 2.283
        Стоп: 2.062

        Фиксируем 50% на первой цели, 25% на второй цели и 25% на оставшейся и после первой цели ставим стоп в без убыток
        Торгуем на 📈BYBIT (https://partner.bybit.com/b/bonus59) и 🔀BingX (https://bingx.com/partner/QCZQR3/1Okf7a)
    """,
    """
        MTC Indicator 🔥

        15 Minutes Timeframe

        🔴 SHORT

        #KGEN/USDT

        Entry zone : 0.3775259 - 0.3665300

        Take Profits : 

        0.3646790
        0.3536281
        0.3425772
        0.3315263
        0.3204755

        Stop loss :0.3921871

        Leverage: 10x
    """,
    """
        #BTC/USD SELL 

        Entry : $ 110601

        Target1: $ 110031
        Target2: $ 107023
        Target3: $ 105256

        SL : $ 112568
    """,
    """
        Pair: #ZEC/USDT
        Type: LONG Leverage: 25x
        Risk: Use only 1% capital ⚠️


        🎯 ENTRY:

        ➤ 256

        🎯 TARGETS:

        🥇 262

        ❌ STOP LOSS: 250

        ⚡️ Trade the setup, not the hype
        📌 DYOR. Not financial advice.
        💡 Never risk more than 1%
    """,
    """
        #SHORT 🔴 🔤🔤🔤🔤🔤

        #TRX/USDT 

        Margin Mode : Isolated💎
        Signal Type : Scalp Trade 🔥

        BUY :

        1) 0.32294- 100%

        Take Profit Targets: 
        1)🟥 0.31969
        2)🟥 0.31636
        3)🟥 0.31270
        4)🟥 0.30986
        5)🟥 0.30649

        🟩 SL : 0.32848 - 100%

        📊 LEV : 30X

        🏆 Premium
    """,
    """
        💰 Coin: $GALA LONG

        ✔️ Entry: 0.01157$
        ✔️ Target: 100 -120%

        ‼️ Trading risk should be between 3-5% of your balance.
    """,
    """
        #AGT SHORT SETUP 

        Target 1: $0.004470
        Target 2: $0.004400
        Target 3: $0.004320

        STOP : $0.004750
    """,
    """
        🚀 #JELLYJELLY/USDT – Long Setup Alert 🕯

        💥 Leverage: 25x – 75x
        🎯 Entry Point: 0.07950(precision is key)


        🐮 Profit Zones Ahead:🙂

        ⬇️ 0.08135– First Breakout

        ⬇️ 0.08380– Momentum Builds

        ⬇️ 0.08880–Bullish Surge
            
        ⬇️ 0.09800Boom

        ⛔️ Stop-Loss: 0.07470– Protect your capital!

        📥 Risk Note:
        Only deploy a fraction of your margin – stay smart, stay safe 🛡🤑
    """,
    """
        🟢LONG #BTCUSDT

        🔶 Entry : 111000 - 111050

        ➡️ Leverage : 100X

        🔥 Take Profit Targets :

        👉 111700

        🛑 Stop Loss : 110400
    """,
    """
        #AUCTION/USDT SHORT NOW ⚡️

        ➡️ Entry Market Price 10.10

        👑 TP(10.30-10.60 -10.99-11.30)

        ⛔️ SL = (9.00)
    """,
    """
        📊 SCALP Signal Alert 📊

        💎PAIR: NOM/USDT
        🟢DIRECTION: LONG

        ━━━━━━━━━━━━━━━
        🏹Entry Price
        1) 0.02335

        🎯Take Profit (TP):
        1) 0.02600

        ❌Stop-Loss (SL):
        1) 0.02210
        ━━━━━━━━━━

        ⚡️Leverage: 50x (Cross)
        💡Risk Reminder: Use only 2% of your capital per trade

        ━━━━━━━━━━━━━━━
    """,
    """
        📊ESTR SCALP Signal Alert 📊

        💎PAIR: RECALL/USDT
        🟢DIRECTION: LONG

        ━━━━━━━━━━━━━━━
        🏹Entry Price
        1) 0.525

        🎯Take Profit (TP):
        1) 0.585

        ❌Stop-Loss (SL):
        1) 0.490
        ━━━━━━━━━━

        ⚡️Leverage: 50x (Cross)
        💡Risk Reminder: Use only 2% of your capital per trade

        ━━━━━━━━━━━━━━━
        📌Published by @ESTR_ADMIN
    """,
    """
        📊ESTR SCALP Signal Alert 📊

        💎PAIR: PIPPIN/USDT
        🟢DIRECTION: LONG

        ━━━━━━━━━━━━━━━
        🏹Entry Price
        1) 0.01915

        🎯Take Profit (TP):
        1) 0.02125

        ❌Stop-Loss (SL):
        1) 0.01790
        ━━━━━━━━━━

        ⚡️Leverage: 50x (Cross)
        💡Risk Reminder: Use only 2% of your capital per trade

        ━━━━━━━━━━━━━━━
        📌Published by @ESTR_ADMIN
    """,
    """
        📊ESTR SCALP Signal Alert 📊

        💎PAIR: DASH/USDT
        🟢DIRECTION: LONG

        ━━━━━━━━━━━━━━━
        🏹Entry Price
        1) 43.50

        🎯Take Profit (TP):
        1) 48.50

        ❌Stop-Loss (SL):
        1) 41.00
        ━━━━━━━━━━

        ⚡️Leverage: 50x (Cross)
        💡Risk Reminder: Use only 2% of your capital per trade

        ━━━━━━━━━━━━━━━
        📌Published by @ESTR_ADMIN
    """,
    """
        📊ESTR SCALP Signal Alert 📊

        💎PAIR: RIVER/USDT
        🟢DIRECTION: LONG

        ━━━━━━━━━━━━━━━
        🏹Entry Price
        1) 4.540

        🎯Take Profit (TP):
        1) 4.800

        ❌Stop-Loss (SL):
        1) 4.350
        ━━━━━━━━━━

        ⚡️Leverage: 50x (Cross)
        💡Risk Reminder: Use only 2% of your capital per trade

        ━━━━━━━━━━━━━━━
        📌Published by @ESTR_ADMIN
    """,
    """
        #STABLEUSDT On Binance   ( Futures ) ‼️

        📉SHORT: 0.0294

        Leverage : 10x

        Target  : 0.0290 - 0.0286 - 0.0282

        Stoploss : My Instruction
    """,
    """
        #STABLEUSDT On Binance ( Futures ) ‼️

        📈LONG: 0.0290

        Leverage : 10x

        Target  : 0.03 - 0.0308 - 0.0317

        Stoploss : My Instruction
    """

    ]

    for s in test_signals:
        result = parser.parse(s)
        print(f"Result: {result}")