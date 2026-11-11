# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "brotli>=1.1.0",
#     "cffsubr>=0.3.0",
#     "chws-tool>=1.4.0",
#     "fonttools>=4.50.0",
#     "glyphsLib>=6.9.0",
#     "ufo2ft>=3.11.0",
#     "ufoLib2>=0.16.0",
# ]
# ///

"""Unified build script for Holon Sans (Static & Variable) and Holon Mono (Static & Variable).

Features:
- Automatic upstream download pinned by immutable Git commit hash & release tags with SHA-256 verification
- Holon Sans: Dual-scale (Japanese CJK 0.97x, Latin/symbols 1.02x), 11.0° Italic, JIS X 4051 chws/vchw
- Holon Mono: Strict 2:1 duospace (550 / 1100 UPM), 9.0° Italic, box-drawing alignment, terminal metrics
- Variable Fonts: 2-file Roman & Italic architecture for Sans & Mono with wght (100..700), GRAD (-100..+100), and avar
- Subsetter, post 3.0, GDEF/STAT synthesis, and modal-advance glyph order clustering for compact hmtx/vmtx/HVAR/VVAR
- Reproducible builds (SOURCE_DATE_EPOCH) and strict compliance with SIL OFL 1.1 metadata and naming requirements
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import copy
import datetime
import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

import cffsubr
import ufo2ft
import ufoLib2
from east_asian_spacing import Builder, Config
from fontTools.designspaceLib import (
    AxisDescriptor,
    DesignSpaceDocument,
    InstanceDescriptor,
    SourceDescriptor,
)
from fontTools.otlLib.builder import buildStatTable, buildValue
from fontTools.otlLib.optimize import compact as compact_otl
from fontTools.pens.recordingPen import (
    DecomposingRecordingPen,
    DecomposingRecordingPointPen,
)
from fontTools.pens.transformPen import TransformPen, TransformPointPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.subset import Options as SubsetOptions
from fontTools.subset import Subsetter
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
from fontTools.ttLib.tables._h_e_a_d import mac_epoch_diff
from glyphsLib import GSFont, to_designspace
from glyphsLib.builder.constants import ORIGINAL_WIDTH_KEY

# --- Constants & Metadata ---

SANS_FAMILY, MONO_FAMILY = "Holon Sans", "Holon Mono"
VENDOR_ID, VENDOR_URL = "HLON", "https://github.com/Daiji256/holon"
COPYRIGHT_SANS = (
    "Copyright 2026 Daiji Suzuki. Copyright 2018 IBM Corp. All rights reserved."
)
COPYRIGHT_MONO = (
    "Copyright 2026 Daiji Suzuki. Copyright 2018 IBM Corp. All rights reserved. "
    "Copyright 2017 IBM Corp. All rights reserved."
)
DESIGNER_STRING = (
    "Mike Abbink; Paul van der Laan; Pieter van Rosmalen; "
    "Wujin Sim; Yejin Wi; Jinhee Kim; Boomi Park; Yona Kim; Kichan Ma; Daiji Suzuki"
)
LICENSE_DESCRIPTION = (
    "This Font Software is licensed under the SIL Open Font License, Version 1.1. "
    "This license is available with a FAQ at: https://openfontlicense.org"
)
LICENSE_URL = "https://openfontlicense.org"

SCALE_SANS, SCALE_JP = 1.02, 0.97
JP_CENTER_X, JP_CENTER_Y = 500.0, 400.0
SANS_ITALIC_ANGLE, MONO_ITALIC_ANGLE = -11.0, -9.0

HALF_WIDTH, FULL_WIDTH = 550, 1100
SCALE_MONO_X, SCALE_MONO_Y = HALF_WIDTH / 600.0, 0.98
MONO_JP_OFFSET_X = (FULL_WIDTH - 1000.0 * SCALE_JP) / 2.0  # 65.0
MONO_JP_OFFSET_Y = JP_CENTER_Y * (1.0 - SCALE_JP)  # 12.0

WEIGHTS = [
    "Thin",
    "ExtraLight",
    "Light",
    "Regular",
    "Text",
    "Medium",
    "SemiBold",
    "Bold",
]
WEIGHT_VALUES = {
    "Thin": 100,
    "ExtraLight": 200,
    "Light": 300,
    "Regular": 400,
    "Text": 450,
    "Medium": 500,
    "SemiBold": 600,
    "Bold": 700,
}
WEIGHT_DESIGN_MAP = [
    (100, 100),
    (200, 165),
    (300, 275),
    (400, 360),
    (450, 450),
    (500, 525),
    (600, 620),
    (700, 700),
]
PANOSE_WEIGHTS = {
    "Thin": 2,
    "ExtraLight": 3,
    "Light": 4,
    "Regular": 5,
    "Text": 5,
    "Medium": 6,
    "SemiBold": 7,
    "Bold": 8,
}

JP_FULLWIDTH_SYMBOLS = {0x2015, 0x2025, 0x2026, 0x2103}
HW_SPACES = {0x2000, 0x2002, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200A}
MONO_SAFE_FEATURES = [
    "ccmp",
    "locl",
    "vert",
    "vrt2",
    "vkna",
    "hkna",
    "jp78",
    "jp83",
    "jp90",
    "nlck",
    "trad",
    "hojo",
    "expt",
    "ruby",
    "fwid",
    "zero",
    "ss01",
    "ss02",
    "ss03",
    "ss04",
]

OUTPUT_DIR, SUBSET_DIR, TMP_DIR = Path("fonts/full"), Path("fonts/subset"), Path("tmp")

# --- Deterministic Build Timestamp (Reproducible Builds) ---

DEFAULT_BUILD_EPOCH = 1767225600  # 2026-01-01 00:00:00 UTC
_BUILD_STATE: dict[str, int | None] = {"unix_ts": None, "mac_ts": None}


def get_git_commit_timestamp() -> int | None:
    """Return unix timestamp of latest git commit, or None if git is unavailable."""
    try:
        res = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            capture_output=True,
            text=True,
            check=True,
        )
        if ct := res.stdout.strip():
            return int(ct)
    except Exception:
        pass
    return None


def resolve_build_timestamp(explicit: int | None = None) -> int:
    """Resolve deterministic build timestamp in Unix epoch seconds.

    Priority:
    1. Explicit CLI argument (--timestamp)
    2. SOURCE_DATE_EPOCH environment variable (Reproducible Builds standard)
    3. Latest Git commit timestamp
    4. Project default epoch (2026-01-01 00:00:00 UTC)
    """
    if explicit is not None:
        return int(explicit)
    if "SOURCE_DATE_EPOCH" in os.environ:
        try:
            return int(os.environ["SOURCE_DATE_EPOCH"])
        except ValueError:
            pass
    if git_ts := get_git_commit_timestamp():
        return git_ts
    return DEFAULT_BUILD_EPOCH


def configure_build_timestamp(explicit: int | None = None) -> int:
    """Configure deterministic build timestamp for the current process and return Unix epoch."""
    unix_ts = resolve_build_timestamp(explicit)
    _BUILD_STATE["unix_ts"] = unix_ts
    _BUILD_STATE["mac_ts"] = unix_ts - mac_epoch_diff
    os.environ["SOURCE_DATE_EPOCH"] = str(unix_ts)
    return unix_ts


def get_build_mac_timestamp() -> int:
    """Return active OpenType Mac epoch timestamp, initializing lazily if needed."""
    if _BUILD_STATE["mac_ts"] is None:
        configure_build_timestamp()
    assert _BUILD_STATE["mac_ts"] is not None
    return _BUILD_STATE["mac_ts"]


def set_font_deterministic_timestamp(font: TTFont, mac_ts: int | None = None) -> None:
    """Ensure font has deterministic timestamp and disables automatic recalculation on save."""
    ts = mac_ts if mac_ts is not None else get_build_mac_timestamp()
    font.recalcTimestamp = False
    if "head" in font:
        font["head"].created = ts
        font["head"].modified = ts


SUBSET_CHARACTERS = " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~\xa0¡¢£¤¥¦§¨©ª«¬\xad®¯°±²³´µ¶·¸¹º»¼½¾¿ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ―‘’“”…‰′″※€℃←↑→↓⇄⇆−√∞≒≠≦≧■□▲△▶▷▼▽◀◁◆◇○◎●★☆✓\u3000、。〈〉《》「」『』【】〒〔〕〜ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをんゔゕゖ゙゚ゝゞァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴヵヶヷヸヹ・ーヽヾ一丁七万丈三上下不与且世丘丙両並中串丸丹主丼久乏乗乙九乞乱乳乾亀了予争事二互五井亜亡交享京亭人仁今介仏仕他付仙代令以仮仰仲件任企伎伏伐休会伝伯伴伸伺似但位低住佐体何余作佳併使例侍供依価侮侯侵侶便係促俊俗保信修俳俵俸俺倉個倍倒候借倣値倫倹偉偏停健側偵偶偽傍傑傘備催傲債傷傾僅働像僕僚僧儀億儒償優元兄充兆先光克免児党入全八公六共兵具典兼内円冊再冒冗写冠冥冬冶冷凄准凍凝凡処凶凸凹出刀刃分切刈刊刑列初判別利到制刷券刹刺刻則削前剖剛剝剣剤副剰割創劇力功加劣助努励労効劾勃勅勇勉動勘務勝募勢勤勧勲勺勾匁匂包化北匠匹区医匿十千升午半卑卒卓協南単博占印危即却卵卸厄厘厚原厳去参又及友双反収叔取受叙口古句叫召可台史右号司各合吉同名后吏吐向君吟否含吸吹呂呈呉告周呪味呼命和咲咽哀品員哲哺唄唆唇唐唯唱唾商問啓善喉喚喜喝喩喪喫営嗅嗣嘆嘱嘲器噴嚇囚四回因団困囲図固国圏園土圧在地坂均坊坑坪垂型垣埋城域執培基埼堀堂堅堆堕堤堪報場塀塁塊塑塔塗塚塞塡塩塾境墓増墜墨墳墾壁壇壊壌士壮声壱売変夏夕外多夜夢大天太夫央失奇奈奉奏契奔奥奨奪奮女奴好如妃妄妊妖妙妥妨妬妹妻姉始姓委姫姻姿威娘娠娯婆婚婦婿媒媛嫁嫉嫌嫡嬢子孔字存孝季孤学孫宅宇守完宗官宙定宛宜宝実客宣室宮宰害宴宵家容宿寂寄密富寒寛寝察寡寧審寮寸寺対寿封専射将尉尊尋導小少尚就尺尻尼尽尾尿局居屈届屋展属層履屯山岐岡岩岬岳岸峠峡峰島崇崎崖崩嵐川州巡巣工左巧巨差己巻巾市布帆希帝帥師席帯帰帳常帽幅幕幣干平年幸幹幻幼幽幾庁広床序底店府度座庫庭庶康庸廃廉廊延廷建弁弄弊式弐弓弔引弟弥弦弧弱張強弾当彙形彩彫彰影役彼往征径待律後徐徒従得御復循微徳徴徹心必忌忍志忘忙応忠快念怒怖思怠急性怨怪恋恐恒恣恥恨恩恭息恵悔悟悠患悦悩悪悲悼情惑惜惧惨惰想愁愉意愚感慄慈態慌慎慕慢慣慨慮慰慶憂憎憤憧憩憬憲憶憾懇懐懲懸成我戒戚戦戯戴戸戻房所扇扉手才打払扱扶批承技抄把抑投抗折抜択披抱抵抹押抽担拉拍拐拒拓拘拙招拝拠拡括拭拳拶拷拾持指挑挙挟挫振挿捉捕捗捜捨据捻掃授掌排掘掛採探接控推措掲描提揚換握揮援揺損搬搭携搾摂摘摩摯撃撤撮撲擁操擦擬支改攻放政故敏救敗教敢散敬数整敵敷文斉斎斑斗料斜斤斥斬断新方施旅旋族旗既日旦旧旨早旬旺昆昇明易昔星映春昧昨昭是昼時晩普景晴晶暁暇暑暖暦暫暮暴曇曖曜曲更書曹曽替最月有服朕朗望朝期木未末本札朱朴机朽杉材村束条来杯東松板析枕林枚果枝枠枢枯架柄某染柔柱柳柵査柿栃栄栓校株核根格栽桁桃案桑桜桟梅梗梨械棄棋棒棚棟森棺椅植椎検業極楷楼楽概構様槽標模権横樹橋機欄欠次欧欲欺款歌歓止正武歩歯歳歴死殉殊残殖殴段殺殻殿毀母毎毒比毛氏民気水氷永氾汁求汎汗汚江池汰決汽沃沈沖沙没沢河沸油治沼沿況泉泊泌法泡波泣泥注泰泳洋洗洞津洪活派流浄浅浜浦浪浮浴海浸消涙涯液涼淑淡淫深混添清渇済渉渋渓減渡渦温測港湖湧湯湾湿満源準溝溶溺滅滋滑滝滞滴漁漂漆漏演漠漢漫漬漸潔潜潟潤潮潰澄激濁濃濫濯瀬火灯灰災炉炊炎炭点為烈無焦然焼煎煙照煩煮熊熟熱燃燥爆爪爵父爽片版牙牛牧物牲特犠犬犯状狂狙狩独狭猛猟猫献猶猿獄獣獲玄率玉王玩珍珠班現球理琴瑠璃璧環璽瓦瓶甘甚生産用田由甲申男町画界畏畑畔留畜畝略番異畳畿疎疑疫疲疾病症痕痘痛痢痩痴瘍療癒癖発登白百的皆皇皮皿盆益盗盛盟監盤目盲直相盾省眉看県真眠眺眼着睡督睦瞬瞭瞳矛矢知短矯石砂研砕砲破硝硫硬碁碑確磁磨礁礎示礼社祈祉祖祝神祥票祭禁禅禍福秀私秋科秒秘租秩称移程税稚種稲稼稽稿穀穂積穏穫穴究空突窃窒窓窟窮窯立竜章童端競竹笑笛符第筆等筋筒答策箇箋算管箱箸節範築篤簡簿籍籠米粉粋粒粗粘粛粧精糖糧糸系糾紀約紅紋納純紙級紛素紡索紫累細紳紹紺終組経結絞絡給統絵絶絹継続維綱網綻綿緊総緑緒線締編緩緯練緻縁縄縛縦縫縮績繁繊織繕繭繰缶罪置罰署罵罷羅羊美羞群羨義羽翁翌習翻翼老考者耐耕耗耳聖聞聴職肉肌肖肘肝股肢肥肩肪肯育肺胃胆背胎胞胴胸能脂脅脇脈脊脚脱脳脹腎腐腕腫腰腸腹腺膚膜膝膨膳臆臓臣臨自臭至致臼興舌舎舗舞舟航般舶舷船艇艦良色艶芋芝芯花芳芸芽苗苛若苦英茂茎茨茶草荒荘荷菊菌菓菜華萎落葉著葛葬蒸蓄蓋蔑蔵蔽薄薦薪薫薬藍藤藩藻虎虐虚虜虞虫虹蚊蚕蛇蛍蛮蜂蜜融血衆行術街衛衝衡表衰衷袋袖被裁裂装裏裕補裸製裾複褐褒襟襲西要覆覇見規視覚覧親観角解触言訂訃計討訓託記訟訪設許訳訴診証詐詔評詞詠詣試詩詮詰話該詳誇誉誌認誓誕誘語誠誤説読誰課調談請論諦諧諭諮諸諾謀謁謄謎謙講謝謡謹識譜警議譲護谷豆豊豚象豪貌貝貞負財貢貧貨販貪貫責貯貴買貸費貼貿賀賂賃賄資賊賓賛賜賞賠賢賦質賭購贈赤赦走赴起超越趣足距跡路跳践踊踏踪蹴躍身車軌軍軒軟転軸軽較載輝輩輪輸轄辛辞辣辱農辺込迅迎近返迫迭述迷追退送逃逆透逐逓途通逝速造連逮週進逸遂遅遇遊運遍過道達違遜遠遡遣適遭遮遵遷選遺避還那邦邪邸郊郎郡部郭郵郷都酌配酎酒酔酢酪酬酵酷酸醒醜醸采釈里重野量金釜針釣鈍鈴鉄鉛鉢鉱銀銃銅銑銘銭鋭鋳鋼錘錠錦錬錮錯録鍋鍛鍵鎌鎖鎮鏡鐘鑑長門閉開閑間関閣閥閲闇闘阜阪防阻附降限陛院陣除陥陪陰陳陵陶陸険陽隅隆隊階随隔隙際障隠隣隷隻雄雅集雇雌雑離難雨雪雰雲零雷電需震霊霜霧露青静非面革靴韓音韻響頂頃項順須預頑頒頓領頭頰頻頼題額顎顔顕願類顧風飛食飢飯飲飼飽飾餅養餌餓館首香馬駄駅駆駐駒騎騒験騰驚骨骸髄高髪鬱鬼魂魅魔魚鮮鯨鳥鳴鶏鶴鹿麓麗麦麺麻黄黒黙鼓鼻齢！％（）＋：；＜＝＞？［］～￥𠮟"

# --- Pinned Upstream Sources & SHA-256 Checksums ---

UPSTREAM_PLEX_COMMIT = "71f558992315a12ca1f06a2215d57962a1992162"

TTF_SHA256: dict[str, str] = {
    # IBM Plex Sans (16 styles)
    "plex-sans/fonts/complete/ttf/IBMPlexSans-Thin.ttf": "d2fdd87b43039f5e05c7749b6b7937837d074bbf14af2d26dba09b67abf6aca1",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-ThinItalic.ttf": "e1056650d0a4511372fa44f539a65c92e2ede7fe19ff5560c05e4490275c41a8",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-ExtraLight.ttf": "c13105ca8fb60874c8db103e8ff058f0dfa0e2194e20ee5c9b0f8b7dd5e1fe85",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-ExtraLightItalic.ttf": "b8a4390ab03889949e6621f7ad635b459c0e520db70fccd833034103b6cf6d3f",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-Light.ttf": "2218b5f3f1fc9d3a793343f45c3be5ee7eae9584a7a52391bb8cf2d37622b3e0",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-LightItalic.ttf": "54ad6d58d163b6b1f850fcbab3c46a1ed6c1ec3050524abb904c076a52c6bb1a",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-Regular.ttf": "975dcda37d80f038dcd143c22e33ca2d97a0cc5a929aace1c749153b0fe1afa5",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-Italic.ttf": "a9c6ef9942c49e49d11e11a6dacc0b3a087978757e9b22a06b8ac22a6400fb15",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-Text.ttf": "4abc4919d313b56a5e3ffdb249ed2450392a5df21478aa4e25ff23901398b1fb",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-TextItalic.ttf": "622e67ffee610160f135c3636825625095cb112b83275ee88752648fad56d89c",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-Medium.ttf": "331c8639d7598b2cde62a911a71db195e30cb655cd6bdf2e324a7e984955f907",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-MediumItalic.ttf": "9928852bf60d82fdbbfe30eac86bcecd611e4188f0fa4d98938560659fa99c64",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-SemiBold.ttf": "a20caf8286023a6a7a85e40b1d2a4ae9fc3e3b1f9eda8f4c542dd4986af67bb1",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-SemiBoldItalic.ttf": "147106b619423a82b40f6d64bace074ad5b786e59f48023bda69d63b1755fb82",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-Bold.ttf": "9e6c74a889a700d707613d24548fe4ffa6bc59559a0689d2cf9e133bdcdafb2f",
    "plex-sans/fonts/complete/ttf/IBMPlexSans-BoldItalic.ttf": "0e3142ba2ef31fe5c02f0c6c36424f251609cd6b73880076e21c2e81931ba2b9",
    # IBM Plex Mono (16 styles)
    "plex-mono/fonts/complete/ttf/IBMPlexMono-Thin.ttf": "171c32cbb133646b6d5e16d0ffbbd39f1ade134932d8a21cefc61e1669fd072e",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-ThinItalic.ttf": "9bb7624f34ec3f7443ce1189b94f0c4321360c6beb846f4bc618daa194ce5ed3",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-ExtraLight.ttf": "4b6acddc27bf7b98c5d28764d0617fc76b7f34c403583145237356e738327c54",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-ExtraLightItalic.ttf": "cd88e7df6e06b14bce0ce8a4b4530cc6791e3d27e8b6955bf553158200559f02",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-Light.ttf": "feca3787130b6e71a0edb1cfc17c2ae7780443888554207a8981de43ef755d36",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-LightItalic.ttf": "eaf46dcb971a93849643c9f1249bbaf9abf92d712227ff6ce68ef48dc3df69e6",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-Regular.ttf": "7c6fbddca4b700be918f5f6183d9bd4464fa427fe435f0b480d77fe2bb8c5a43",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-Italic.ttf": "a55368deb953f594ac18336a1029009ed820e2d9abbb57ad601f61e22bec072b",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-Text.ttf": "bb43e352f1d4aeedfd9e2e33449660a2b9473010d57a6013ceff976242ea5456",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-TextItalic.ttf": "bdfc5b6ea2ffba1880313c73773630c85fa3a6e56d7f7a777da52702e7d65532",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-Medium.ttf": "98fbd727aae340b236955879dabed4d991aac9e8e90b3b2a67ce4a59221cc97c",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-MediumItalic.ttf": "100852349a441076bb03aca3a3c7786eaf5d59a91dca3e4677ee8337805817fb",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-SemiBold.ttf": "f04d7c488ddf7d1fa99f2574efc3406ea4cbe17bb1af3a1ab960f84d0c96a172",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-SemiBoldItalic.ttf": "d2039ddfa9236d642fafae5aa46446c54eb7961b3771a1ca3e9bba960172b9bb",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-Bold.ttf": "74e5eedcfa4596497d34e19023cabdabd3a8c852b903007a5654a59591a72ffb",
    "plex-mono/fonts/complete/ttf/IBMPlexMono-BoldItalic.ttf": "c8b00068fd2fd69bbcf62059148623f09d19e9ada8bf9e8caf1aedd01347046a",
    # IBM Plex Sans JP unhinted (8 weights)
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Thin.ttf": "aa28c0a68a8040c7082a85d34b1fef0e31d726cfc904db1ac542b349797a71e9",
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-ExtraLight.ttf": "40ed45b01a733c0c797017a9b5498a4a4d05cdb3beb09eb78010dc7d74a1555f",
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Light.ttf": "6d265357c213600e1f129b5662d474b266a163564205cbdb8e0bb9b0fc2b5c70",
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Regular.ttf": "0168493ae143d16e4c0d374c090b1ee5eab9ee475536d2e429368dbcfc4a6abe",
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Text.ttf": "34d906500faca7a7995eddc5171ef2b04813bc809b7125d8525ca54ea2a5cb60",
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Medium.ttf": "ed9257c94b0a540bac56a0faa70ec554b18ea7271fa4f0d33512583dd4bf9c0c",
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-SemiBold.ttf": "3ae17af73062926b013afdec8949923a8adfd4ec8c4f689876c0a359e63e4ceb",
    "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Bold.ttf": "070c08915b21a9484e31a73594e4aae69991e4477959a96a6ab4031f4e30ec9f",
}

ZIP_SOURCES = {
    "sans-jp": {
        "tag": "@ibm/plex-sans-jp@3.0.0",
        "sha256": "4ac6374873b634a9dc19cd2b8f40e9acfe55ea37c269c08c0dcdb9b2abdce3de",
        "url": "https://github.com/IBM/plex/releases/download/%40ibm/plex-sans-jp%403.0.0/sources.zip",
        "target_rel": Path("sources/masters/IBM Plex Sans JP.glyphs"),
    },
    "sans-variable": {
        "tag": "@ibm/plex-sans-variable@0.2.0",
        "sha256": "50c6ff678938adc30c6c0b3dbde6fd4961f76422c4b814d741ba43caf3cfde69",
        "url": "https://github.com/IBM/plex/releases/download/%40ibm/plex-sans-variable%400.2.0/sources.zip",
        "target_rel": Path("sources/IBM Plex Sans Var-Regular.ufo"),
    },
    "mono-variable": {
        "tag": "@ibm/plex-mono-variable@1.0.0",
        "sha256": "cead332365e44b09552581533bae5dcbbd6e6ac80265afa915981260ba75eef3",
        "url": "https://github.com/IBM/plex/releases/download/%40ibm/plex-mono-variable%401.0.0/sources.zip",
        "target_rel": Path("source/IBM Plex Mono Var-Regular.ufo"),
    },
}

CJK_MARKERS = (
    "hira",
    "kata",
    ".vert",
    ".hori",
    ".jp78",
    ".jp83",
    ".jp90",
    ".trad",
    ".nlck",
    ".hojo",
    ".expt",
    ".ruby",
    "Square",
    "leftjust",
    ".circled",
    ".paren",
    ".box",
    ".roundBox",
    ".blackBox",
    ".blackCircled",
    ".roundBlackBox",
    ".roundedBox",
    ".qartwidth",
    ".thirdwidths",
    "comb_kana",
    "T_E_L",
    "K_K",
    "s_e_c",
    "m_i_n",
    "watto",
    "sento",
    "peeji",
    "haitsu",
    "herutsu",
    "koopo",
    "inchi",
    "yaado",
    "hoon",
    "blackScissors",
    ".full",
    ".prop",
    "uni21F5",
)

_CHWS_PATCHED = False
_BASE_JP_UFOS: list[ufoLib2.Font] | None = None


# --- Upstream Downloading & Verification ---


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _download_with_sha256(url: str, dest: Path, expected_sha256: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
    print(f"Downloading {url} -> {dest}...")
    req = urllib.request.Request(url, headers={"User-Agent": "HolonFontBuilder/1.0"})
    with urllib.request.urlopen(req) as resp, open(tmp_dest, "wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    if (actual := _sha256_file(tmp_dest)) != expected_sha256:
        tmp_dest.unlink(missing_ok=True)
        raise RuntimeError(
            f"SHA-256 mismatch for {url}: expected {expected_sha256}, got {actual}"
        )
    tmp_dest.replace(dest)


def ensure_ttf_source(rel_path: str) -> Path:
    """Return local path to an upstream file, downloading from pinned commit hash if needed."""
    expected_sha = TTF_SHA256[rel_path]
    local_path = TMP_DIR / "plex" / "packages" / rel_path
    if not local_path.exists() or _sha256_file(local_path) != expected_sha:
        _download_with_sha256(
            f"https://raw.githubusercontent.com/IBM/plex/{UPSTREAM_PLEX_COMMIT}/packages/{rel_path}",
            local_path,
            expected_sha,
        )
    return local_path


def ensure_zip_source(key: str) -> Path:
    """Ensure release zip source is downloaded and atomically extracted, returning target file path."""
    info = ZIP_SOURCES[key]
    extract_dir = TMP_DIR / f"sources-{key}" / "unzipped"
    target, sentinel = extract_dir / info["target_rel"], extract_dir / ".extracted"
    if sentinel.exists() and target.exists():
        return target
    zip_path = TMP_DIR / f"sources-{key}" / "sources.zip"
    if not zip_path.exists() or _sha256_file(zip_path) != info["sha256"]:
        _download_with_sha256(info["url"], zip_path, info["sha256"])
    print(f"Extracting {zip_path} ({info['tag']})...")
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(
            extract_dir,
            members=[m for m in zf.namelist() if not m.startswith("__MACOSX/")],
        )
    for ufo_zip in extract_dir.rglob("*.ufo.zip"):
        if (
            not ufo_zip.name.startswith("._")
            and not (ufo_dest := ufo_zip.parent / ufo_zip.stem).exists()
        ):
            with zipfile.ZipFile(ufo_zip, "r") as uzf:
                uzf.extractall(ufo_dest)
    sentinel.touch()
    return target


def ensure_variable_sources(for_family: str = "sans") -> tuple[Path, Path]:
    """Ensure variable font master sources (.glyphs and Sans/Mono .ufo) exist in tmp/."""
    return ensure_zip_source("sans-jp"), ensure_zip_source(
        "mono-variable" if for_family == "mono" else "sans-variable"
    ).parent


# --- Shared Glyph, Transform & OpenType Helpers ---


def is_cjk_glyph(gname: str, u: int | None = None, box_is_latin: bool = False) -> bool:
    """Classify whether a glyph (encoded or unencoded) belongs to Japanese/CJK metrics."""
    if any(m in gname for m in CJK_MARKERS) or gname.startswith(
        ("cid", "u1F", "u20", "u30", "uniFE1")
    ):
        return True
    if gname.endswith(
        (
            ".half",
            ".narrow",
            ".italic",
            ".rotat",
            ".sups",
            ".subs",
            ".numr",
            ".dnom",
            ".ordn",
            ".nut",
        )
    ):
        return False
    if u is not None:
        if (0x2000 <= u <= 0x200B) or u == 0x3000:
            return False
        if not box_is_latin and u in JP_FULLWIDTH_SYMBOLS:
            return True
        if box_is_latin and (0x2500 <= u <= 0x25FF or 0xFB00 <= u <= 0xFB4F):
            return False
        if 0x229E <= u <= 0x22A1:
            return True
        return not (u < 0x02B0 or 0x0370 <= u <= 0x052F or 0x200C <= u <= 0x23FF)
    m = re.match(r"^uni([0-9A-Fa-f]{4})", gname)
    return (
        is_cjk_glyph("", int(m.group(1), 16), box_is_latin=box_is_latin) if m else False
    )


def _transform_tt_glyph(glyph_set, gname: str, matrix: tuple[float, ...], glyf_table):
    rec_pen = DecomposingRecordingPen(glyph_set)
    glyph_set[gname].draw(rec_pen)
    tt_pen = TTGlyphPen(None)
    rec_pen.replay(TransformPen(tt_pen, matrix))
    g = tt_pen.glyph()
    g.recalcBounds(glyf_table)
    return g


def _transform_ufo_glyph(glyph, matrix: tuple[float, ...]) -> None:
    """Apply 6-tuple affine matrix (a, b, c, d, e, f) to all points in a UFO glyph."""
    a, b, c, d, e, f = matrix
    for contour in glyph.contours:
        for p in contour.points:
            p.x, p.y = a * p.x + c * p.y + e, b * p.x + d * p.y + f


def _set_tt_glyph(
    font: TTFont,
    name: str,
    glyph,
    h_adv: int,
    lsb: int | None = None,
    v_adv: int | None = None,
) -> None:
    """Store glyph in glyf table and update hmtx and vmtx tables with standard tsb calculation."""
    font["glyf"][name] = glyph
    font["hmtx"][name] = (h_adv, glyph.xMin if lsb is None else lsb)
    if "vmtx" in font:
        tsb = 880 - (glyph.yMax if getattr(glyph, "numberOfContours", 0) != 0 else 0)
        adv = (
            v_adv
            if v_adv is not None
            else font["vmtx"].metrics.get(name, (1000, tsb))[0]
        )
        font["vmtx"].metrics[name] = (adv, tsb)


def _snap_tt_box_drawing_glyph(glyph, glyf_table, is_line: bool = False) -> None:
    """Snap Box-drawing and Block Elements vertical boundaries to 950 (Ascent) and -225 (Descent),
    and add pointed tips to line overhanging end caps so FreeType autohinter aligns all stems."""
    if glyph.numberOfContours <= 0:
        return
    coords, endPts, flags = glyph.getCoordinates(glyf_table)
    if not is_line:
        glyph.coordinates = GlyphCoordinates(
            (x, 950 if y >= 800 else (-225 if y <= -250 else y)) for x, y in coords
        )
        glyph.recalcBounds(glyf_table)
        return

    new_coords, new_endPts, new_flags, s = [], [], [], 0
    for e in endPts:
        pts = [
            (x, 950 if y >= 800 else (-225 if y <= -250 else y))
            for x, y in list(coords)[s : e + 1]
        ]
        fls = list(flags)[s : e + 1]
        c_pts, c_fls = [], []
        for i, (x1, y1) in enumerate(pts):
            x2, y2 = pts[(i + 1) % len(pts)]
            c_pts.append((x1, y1))
            c_fls.append(fls[i])
            if x1 == x2 and (x1 < 0 or x1 > 550) and abs(y2 - y1) > 0:
                c_pts.append((x1 - 18 if x1 < 0 else x1 + 18, (y1 + y2) // 2))
                c_fls.append(1)
            elif y1 == y2 and (y1 >= 900 or y1 <= -200) and abs(x2 - x1) > 0:
                c_pts.append(((x1 + x2) // 2, 968 if y1 >= 900 else -243))
                c_fls.append(1)
        new_coords.extend(c_pts)
        new_flags.extend(c_fls)
        new_endPts.append(len(new_coords) - 1)
        s = e + 1

    glyph.coordinates, glyph.endPtsOfContours, glyph.flags = (
        GlyphCoordinates(new_coords),
        new_endPts,
        bytearray(new_flags),
    )
    glyph.recalcBounds(glyf_table)


def add_vertical_semicolon(font_jp: TTFont) -> None:
    """Add uniFF1B.vert (rotated 90° CW around (500, 378)) and update vert/vrt2 in GSUB."""
    glyf = font_jp["glyf"]
    if "uniFF1B" not in glyf or "uniFF1B.vert" in glyf:
        return
    _set_tt_glyph(
        font_jp,
        "uniFF1B.vert",
        _transform_tt_glyph(
            font_jp.getGlyphSet(), "uniFF1B", (0.0, -1.0, 1.0, 0.0, 122.0, 878.0), glyf
        ),
        1000,
    )

    order = font_jp.getGlyphOrder()
    if "uniFF1B.vert" not in order:
        order.append("uniFF1B.vert")
        font_jp.setGlyphOrder(order)
        font_jp["maxp"].numGlyphs = len(order)

    if "GSUB" in font_jp:
        gsub = font_jp["GSUB"].table
        for rec in gsub.FeatureList.FeatureRecord:
            if rec.FeatureTag in ("vert", "vrt2"):
                for idx in rec.Feature.LookupListIndex:
                    lookup = gsub.LookupList.Lookup[idx]
                    if lookup.LookupType == 1:
                        for st in lookup.SubTable:
                            if hasattr(st, "mapping") and "uniFF1A" in st.mapping:
                                st.mapping["uniFF1B"] = "uniFF1B.vert"


def _cjk_compat_pairs(known_codes) -> dict[int, int]:
    """Return {compat_cp: canonical_cp} for unmapped CJK Compatibility Ideographs (U+F900..U+FAFF)."""
    return {
        code: ord(d)
        for code in range(0xF900, 0xFB00)
        if code not in known_codes
        and len(d := unicodedata.normalize("NFKD", chr(code))) == 1
        and ord(d) in known_codes
    }


def add_cjk_compatibility_mappings(font_jp: TTFont) -> None:
    """Map missing CJK Compatibility Ideographs (U+F900..U+FAFF) to canonical unified ideographs."""
    cmap_jp = font_jp.getBestCmap()
    new_map = {c: cmap_jp[can] for c, can in _cjk_compat_pairs(cmap_jp).items()}
    for table in font_jp["cmap"].tables:
        if table.isUnicode():
            table.cmap.update(new_map)


def add_cjk_compatibility_mappings_to_ufos(ufos: list[ufoLib2.Font]) -> None:
    """Map missing CJK Compatibility Ideographs (U+F900..U+FAFF) across UFO masters."""
    code_to_gname = {u: g.name for g in ufos[0] for u in (g.unicodes or [])}
    pairs = _cjk_compat_pairs(code_to_gname)
    for code, can in pairs.items():
        cg = code_to_gname[can]
        for ufo in ufos:
            if cg in ufo:
                ufo[cg].unicodes = [*(ufo[cg].unicodes or []), code]


def _fix_u3000(font: TTFont, full_width: int = 1000) -> None:
    """Ensure fullwidth space (U+3000) advance is exact 1000 or 1100 UPM."""
    if 0x3000 in (cmap := font.getBestCmap()):
        g = cmap[0x3000]
        font["hmtx"][g] = (full_width, 0)
        if "vmtx" in font:
            font["vmtx"].metrics[g] = (full_width, 880)


def _apply_mono_metrics_and_cleanup(font: TTFont, clean_gsub: bool = True) -> None:
    """Apply terminal & editor compatible vertical metrics (950 / -225) and duospace cleanup."""
    os2, hhea, head = font["OS/2"], font["hhea"], font["head"]
    os2.sTypoAscender = hhea.ascent = 950
    os2.sTypoDescender = hhea.descent = -225
    os2.usWinAscent, os2.usWinDescent = max(950, head.yMax), max(225, -head.yMin)
    (
        os2.sTypoLineGap,
        hhea.lineGap,
        os2.panose.bProportion,
        font["post"].isFixedPitch,
    ) = 0, 0, 9, 1

    for tag in ("GPOS", "BASE"):
        if tag in font:
            del font[tag]

    if clean_gsub and "GSUB" in font:
        gsub = font["GSUB"].table
        vert_idx = next(
            (
                list(r.Feature.LookupListIndex)
                for r in gsub.FeatureList.FeatureRecord
                if r.FeatureTag == "vert"
            ),
            [],
        )
        for rec in gsub.FeatureList.FeatureRecord:
            if rec.FeatureTag == "vrt2" and vert_idx:
                rec.Feature.LookupListIndex = list(vert_idx)
            elif rec.FeatureTag in ("vert", "vrt2"):
                for lidx in rec.Feature.LookupListIndex:
                    for st in gsub.LookupList.Lookup[lidx].SubTable:
                        if hasattr(st, "mapping"):
                            st.mapping = {
                                k: v
                                for k, v in st.mapping.items()
                                if not (
                                    "box" in k.lower()
                                    or "box" in v.lower()
                                    or "uni25" in k.lower()
                                    or "uni25" in v.lower()
                                )
                            }
            elif rec.FeatureTag == "zero":
                for lidx in rec.Feature.LookupListIndex:
                    for st in gsub.LookupList.Lookup[lidx].SubTable:
                        if hasattr(st, "mapping"):
                            st.mapping = {"zero": "zero.alt01"}


def _is_eaw_wide(ucode: int) -> bool:
    return 0 < ucode < 0x110000 and unicodedata.east_asian_width(chr(ucode)) in (
        "W",
        "F",
    )


def _latin_metrics(
    ucode: int, orig_w: int, orig_lsb: int, is_mono: bool
) -> tuple[int, int]:
    """Calculate scaled advance width and lsb for merged Latin/symbol glyphs."""
    if is_mono:
        if orig_w == 0:
            return 0, round(orig_lsb * SCALE_MONO_X)
        if _is_eaw_wide(ucode):
            return FULL_WIDTH, round(
                orig_lsb * SCALE_MONO_X + (FULL_WIDTH - HALF_WIDTH) / 2.0
            )
        return HALF_WIDTH, round(orig_lsb * SCALE_MONO_X)
    if ucode in (0x2001, 0x2003):
        return 1000, 0
    if ucode in (0x2000, 0x2002):
        return 500, 0
    return (0 if orig_w == 0 else round(orig_w * SCALE_SANS)), round(
        orig_lsb * SCALE_SANS
    )


def _get_jp_glyph_transform(
    family_name: str, gname: str, ucode: int | None, orig_w: int, slant: float
) -> tuple[tuple[float, ...], int]:
    """Calculate affine transform matrix and target advance width for remaining Japanese glyphs."""
    if family_name == MONO_FAMILY:
        is_hw = (
            orig_w == 500
            or gname.endswith((".half", ".narrow", ".rotat"))
            or ucode in HW_SPACES
            or (orig_w != 1000 and not is_cjk_glyph(gname, ucode, box_is_latin=True))
        )
        if is_hw:
            sx, sy = (
                (1.0 if orig_w <= 500 else 500.0 / orig_w),
                (1.0 if orig_w == 500 else SCALE_MONO_Y),
            )
            return (
                sx,
                0.0,
                sy * slant,
                sy,
                (HALF_WIDTH - orig_w * sx) / 2.0,
                0.0,
            ), HALF_WIDTH
        return (
            SCALE_JP,
            0.0,
            SCALE_JP * slant,
            SCALE_JP,
            MONO_JP_OFFSET_X + (MONO_JP_OFFSET_Y - JP_CENTER_Y) * slant,
            MONO_JP_OFFSET_Y,
        ), FULL_WIDTH

    if is_cjk_glyph(gname, ucode, box_is_latin=False):
        dx, dy = (
            (orig_w / 2.0 if orig_w > 0 else JP_CENTER_X) * (1.0 - SCALE_JP),
            JP_CENTER_Y * (1.0 - SCALE_JP),
        )
        return (
            SCALE_JP,
            0.0,
            SCALE_JP * slant,
            SCALE_JP,
            dx + (dy - JP_CENTER_Y) * slant,
            dy,
        ), orig_w

    return (SCALE_SANS, 0.0, SCALE_SANS * slant, SCALE_SANS, 0.0, 0.0), (
        orig_w if gname.endswith(".rotat") else round(orig_w * SCALE_SANS)
    )


# --- Style Names, Metadata, STAT/GDEF, CHWS, Subsetter & Export ---


def style_names(weight: str, italic: bool) -> tuple[str, str, str]:
    """Return (style_name, ps_suffix, ribbon_subfamily) consistently across all families."""
    style_name = (
        ("Italic" if weight == "Regular" else f"{weight} Italic") if italic else weight
    )
    subfamily = (
        ("Bold Italic" if italic else "Bold")
        if weight == "Bold"
        else ("Italic" if italic else "Regular")
    )
    return style_name, style_name.replace(" ", ""), subfamily


def build_family_stat_table(
    font: TTFont,
    weight: str = "Regular",
    italic: bool = False,
    is_variable: bool = False,
) -> None:
    """Build OpenType 1.8+ STAT table for both Static and Variable fonts."""
    if is_variable:
        wght_values = [
            {
                "value": v,
                "name": n,
                **({"flags": 2, "linkedValue": 700} if v == 400 else {}),
            }
            for v, n in zip(WEIGHT_VALUES.values(), WEIGHTS)
        ]
    else:
        wv = WEIGHT_VALUES.get(weight, 400)
        wght_values = [
            {
                "value": wv,
                "name": weight,
                **({"flags": 2, "linkedValue": 700} if wv == 400 else {}),
            }
        ]
    stat_axes = [
        {"tag": "wght", "name": "Weight", "ordering": 0, "values": wght_values}
    ]
    if is_variable:
        stat_axes.append(
            {
                "tag": "GRAD",
                "name": "Grade",
                "ordering": 1,
                "values": [{"value": 0, "name": "Normal", "flags": 2}],
            }
        )
    stat_axes.append(
        {
            "tag": "ital",
            "name": "Italic",
            "ordering": len(stat_axes),
            "values": [
                {"value": 1.0, "name": "Italic", "flags": 0}
                if italic
                else {"value": 0.0, "name": "Regular", "flags": 2, "linkedValue": 1.0}
            ],
        }
    )
    buildStatTable(font, stat_axes)


def ensure_gdef_table(font: TTFont) -> None:
    """Ensure a valid GDEF table with GlyphClassDef exists (Base=1, Ligature=2, Mark=3)."""
    if "GDEF" in font:
        return
    hmtx = font["hmtx"].metrics
    gdef = newTable("GDEF")
    gdef.table = otTables.GDEF()
    gdef.table.Version = 0x00010000
    gdef.table.GlyphClassDef = otTables.GlyphClassDef()
    gdef.table.GlyphClassDef.classDefs = {
        g: (
            3
            if (hmtx[g][0] == 0 or "comb" in g)
            else (2 if g in ("fi", "fl", "f_f_i", "f_f_l") else 1)
        )
        for g in font.getGlyphOrder()
        if g != ".notdef"
    }
    gdef.table.AttachList = gdef.table.LigCaretList = gdef.table.MarkAttachClassDef = (
        None
    )
    font["GDEF"] = gdef


def apply_opentype_metadata(
    font: TTFont,
    family_name: str,
    weight: str,
    italic: bool,
    italic_angle: float,
    is_variable: bool = False,
) -> str:
    """Update name, OS/2, head, hhea, post, STAT, and GDEF tables conforming strictly to SIL OFL 1.1."""
    family_compact, is_mono = family_name.replace(" ", ""), (family_name == MONO_FAMILY)
    if is_variable:
        style_name = "Italic" if italic else "Regular"
        ribbi_family, ribbi_subfamily = family_name, style_name
        ps_suffix, ps_name = (
            ("Italic-Variable" if italic else "Variable"),
            f"{family_compact}-{'ItalicVariable' if italic else 'Variable'}",
        )
    else:
        style_name, ps_suffix, ribbi_subfamily = style_names(weight, italic)
        ps_name = f"{family_compact}-{ps_suffix}"
        ribbi_family = (
            family_name if weight in ("Regular", "Bold") else f"{family_name} {weight}"
        )

    name_records = {
        0: COPYRIGHT_MONO if is_mono else COPYRIGHT_SANS,
        1: ribbi_family,
        2: ribbi_subfamily,
        3: f"1.000;{VENDOR_ID};{ps_name}",
        4: f"{family_name} {style_name}",
        5: "Version 1.000",
        6: ps_name,
        7: "",
        8: "Holon Project",
        9: DESIGNER_STRING,
        11: VENDOR_URL,
        12: VENDOR_URL,
        13: LICENSE_DESCRIPTION,
        14: LICENSE_URL,
        16: family_name,
        17: style_name,
        20: "",
        25: f"{family_compact}{'Italic' if italic else ''}" if is_variable else "",
    }
    name_table = font["name"]
    name_table.names = [r for r in name_table.names if r.nameID not in name_records]
    for name_id, val in name_records.items():
        if val:
            name_table.addMultilingualName({"en": val}, nameID=name_id)

    os2 = font["OS/2"]
    os2.achVendID, os2.usWeightClass, os2.fsType = (
        VENDOR_ID,
        WEIGHT_VALUES.get(weight, 400),
        0,
    )
    os2.panose.bWeight = PANOSE_WEIGHTS.get(weight, 5)
    os2.fsSelection = (
        0x180
        | (0x01 if italic else 0)
        | (
            0x20
            if weight == "Bold"
            else (0x40 if weight == "Regular" and not italic else 0)
        )
    )
    os2.recalcUnicodeRanges(font)

    head = font["head"]
    head.fontRevision, head.macStyle = (
        1.0,
        (0x02 if italic else 0) | (0x01 if weight == "Bold" else 0),
    )
    set_font_deterministic_timestamp(font)
    font["post"].italicAngle = italic_angle if italic else 0.0
    font["hhea"].caretSlopeRise, font["hhea"].caretSlopeRun = (
        (1000, round(1000.0 * math.tan(math.radians(-italic_angle))))
        if italic
        else (1, 0)
    )

    build_family_stat_table(font, weight=weight, italic=italic, is_variable=is_variable)
    ensure_gdef_table(font)
    return ps_suffix


def install_enhanced_chws() -> None:
    """Enhance east_asian_spacing GlyphSets with comprehensive JIS X 4051 yakumono rules."""
    global _CHWS_PATCHED
    if _CHWS_PATCHED:
        return
    from east_asian_spacing.spacing import (
        ChainContextPosBuilder,
        ChainContextualRule,
        Font,
        GlyphSets,
        PairPosBuilder,
    )

    def custom_build_chws_lookup(self, font: Font, lookups, pos: GlyphSets.PosValues):
        self.assert_font(font)
        lookup_indices, ttfont = [], font.ttfont
        glyph_order, em = set(ttfont.getGlyphOrder()), font.fullwidth_advance
        half_em, quad_em = math.floor(em / 2), math.floor(math.floor(em / 2) / 2)

        if font.is_vertical:
            for g in ("uniFF1B.vert", "semicolon.full.vert", "uniFF1B"):
                if g in glyph_order and g not in pos.middle:
                    pos.middle = (*pos.middle, g)

        axis, sign = ("Y", 1) if font.is_vertical else ("X", -1)
        half_left_val, quad_left_val = (
            buildValue({f"{axis}Advance": -half_em}),
            buildValue({f"{axis}Advance": -quad_em}),
        )
        half_right_val = buildValue(
            {f"{axis}Placement": sign * half_em, f"{axis}Advance": -half_em}
        )
        quad_right_val = buildValue(
            {f"{axis}Placement": sign * quad_em, f"{axis}Advance": -quad_em}
        )

        pair_pos_builder = PairPosBuilder(ttfont, None)
        pair_pos_builder.addClassPair(
            None,
            pos.left,
            half_left_val,
            pos.left + pos.right + pos.middle + pos.space + pos.na_left,
            None,
        )
        if pos.middle:
            pair_pos_builder.addClassPair(
                None, pos.middle, half_left_val, pos.middle, None
            )
            if pos.space:
                pair_pos_builder.addClassPair(
                    None, pos.middle, half_left_val, pos.space, None
                )
            if pos.left:
                pair_pos_builder.addClassPair(
                    None, pos.middle, quad_left_val, pos.left, None
                )

        for sp_g in ("space", "space.rotat"):
            if sp_g in glyph_order:
                for col_g in (
                    "uniFF1A",
                    "uniFF1B",
                    "uniFF1A.vert",
                    "uniFF1B.vert",
                    "semicolon.full.vert",
                ):
                    if col_g in glyph_order:
                        pair_pos_builder.addGlyphPair(
                            None, col_g, half_left_val, sp_g, None
                        )

        lookup = pair_pos_builder.build()
        assert lookup
        lookup_indices.append(len(lookups))
        lookups.append(lookup)

        sl_r = self._build_single_pos_lookup(
            font, lookups, ((pos.right, half_right_val),)
        )
        sl_m_half = self._build_single_pos_lookup(
            font, lookups, ((pos.middle, half_right_val),)
        )
        sl_m_quad = self._build_single_pos_lookup(
            font, lookups, ((pos.middle, quad_right_val),)
        )

        chain_builder = ChainContextPosBuilder(ttfont, None)
        chain_builder.rules.append(
            ChainContextualRule(
                [pos.right + pos.middle + pos.space + pos.na_right],
                [pos.right],
                [],
                [[sl_r]],
            )
        )
        if pos.right and pos.middle:
            chain_builder.rules.append(
                ChainContextualRule([pos.right], [pos.middle], [], [[sl_m_quad]])
            )
        if pos.space and pos.middle:
            chain_builder.rules.append(
                ChainContextualRule([pos.space], [pos.middle], [], [[sl_m_half]])
            )

        lookup2 = chain_builder.build()
        assert lookup2
        lookup_indices.append(len(lookups))
        lookups.append(lookup2)
        return lookup_indices

    GlyphSets._build_chws_lookup = custom_build_chws_lookup
    _CHWS_PATCHED = True


async def apply_chws(input_path: Path, output_path: Path) -> None:
    """Inject chws and vchw OpenType feature rules using east_asian_spacing."""
    install_enhanced_chws()
    config = Config.default.clone()
    config.fullwidth_advance = 1000
    if not await Builder(str(input_path), config=config).build_and_save(output_path):
        raise RuntimeError(f"Failed to inject chws into {input_path}")


def _sync_otl_glyph_order(font: TTFont) -> None:
    """Filter and sort GSUB/GPOS subtables so all Coverage and PairSet arrays match font.getGlyphOrder()."""
    order = font.getGlyphOrder()
    valid, gid_map = set(order), {g: i for i, g in enumerate(order)}
    for tag in ("GSUB", "GPOS"):
        if tag not in font:
            continue
        for lookup in font[tag].table.LookupList.Lookup:
            new_sts = []
            for st in lookup.SubTable:
                s = st.ExtSubTable if hasattr(st, "ExtSubTable") else st
                if getattr(s, "Format", None) == 1 and hasattr(s, "PairSet"):
                    paired = []
                    for g, ps in zip(s.Coverage.glyphs, s.PairSet):
                        if g in valid:
                            ps.PairValueRecord = sorted(
                                [
                                    r
                                    for r in ps.PairValueRecord
                                    if r.SecondGlyph in valid
                                ],
                                key=lambda r: gid_map[r.SecondGlyph],
                            )
                            if ps.PairValueRecord:
                                paired.append((g, ps))
                    if not paired:
                        continue
                    paired.sort(key=lambda x: gid_map[x[0]])
                    s.Coverage.glyphs, s.PairSet = (
                        [x[0] for x in paired],
                        [x[1] for x in paired],
                    )
                elif getattr(s, "Format", None) == 2 and hasattr(s, "ClassDef1"):
                    s.Coverage.glyphs = sorted(
                        [g for g in s.Coverage.glyphs if g in valid],
                        key=gid_map.__getitem__,
                    )
                    if not s.Coverage.glyphs:
                        continue
                    s.ClassDef1.classDefs = {
                        g: c for g, c in s.ClassDef1.classDefs.items() if g in valid
                    }
                    s.ClassDef2.classDefs = {
                        g: c for g, c in s.ClassDef2.classDefs.items() if g in valid
                    }
                elif hasattr(s, "Coverage") and hasattr(s.Coverage, "glyphs"):
                    s.Coverage.glyphs = sorted(
                        [g for g in s.Coverage.glyphs if g in valid],
                        key=gid_map.__getitem__,
                    )
                    if not s.Coverage.glyphs:
                        continue
                for attr in ("BacktrackCoverage", "InputCoverage", "LookAheadCoverage"):
                    for cov in getattr(s, attr, ()):
                        cov.glyphs.sort(key=gid_map.__getitem__)
                new_sts.append(st)
            lookup.SubTable, lookup.SubTableCount = new_sts, len(new_sts)


def _cluster_modal_glyph_order(font: TTFont, full_width: int) -> None:
    """Cluster glyphs with modal (full_width, full_width) advances at the end of glyphOrder to compact hmtx & vmtx."""
    if "CFF2" in font:
        return
    for tag in list(font.keys()):
        _ = font[tag]
    hmtx, vmtx = font["hmtx"].metrics, (font["vmtx"].metrics if "vmtx" in font else {})
    font.setGlyphOrder(
        sorted(
            font.getGlyphOrder(),
            key=lambda g: (
                g != ".notdef",
                hmtx[g][0] == full_width
                and vmtx.get(g, (full_width, 0))[0] == full_width,
            ),
        )
    )
    _sync_otl_glyph_order(font)


def _remove_empty_pua_from_cmap(font: TTFont) -> None:
    """Remove unoutlined PUA codepoints (e.g., U+F860..U+F87F) from cmap tables."""
    if "cmap" not in font:
        return
    is_empty = (
        (lambda g: g in font["glyf"] and font["glyf"][g].numberOfContours == 0)
        if "glyf" in font
        else (lambda _: False)
    )
    for table in font["cmap"].tables:
        if table.isUnicode():
            for cp in [
                cp
                for cp, g in table.cmap.items()
                if 0xE000 <= cp <= 0xF8FF and (0xF860 <= cp <= 0xF87F or is_empty(g))
            ]:
                del table.cmap[cp]


def subset_and_export(
    font_path: Path,
    out_desktop: Path,
    out_woff2: Path,
    unicodes: set[int] | None = None,
    mac_ts: int | None = None,
) -> int:
    """Subset glyphs, drop obsolete tables, set post 3.0, and export desktop + WOFF2."""
    is_mono = "Mono" in out_desktop.name
    font = TTFont(font_path)
    if unicodes is None:
        _remove_empty_pua_from_cmap(font)
        target_unicodes = set(font.getBestCmap().keys())
        langs = "Jpan, Latn, Cyrl, Grek"
    else:
        target_unicodes = unicodes
        langs = "Jpan, Latn"

    opts = SubsetOptions()
    opts.layout_features = MONO_SAFE_FEATURES if is_mono else ["*"]
    opts.name_IDs, opts.name_languages = ["*"], ["*"]
    opts.notdef_outline = True
    opts.glyph_names = opts.hinting = False
    opts.drop_tables += ["DSIG", "meta"]

    subsetter = Subsetter(options=opts)
    subsetter.populate(unicodes=target_unicodes)
    subsetter.subset(font)

    meta = newTable("meta")
    meta.data = {"dlng": langs, "slng": langs}
    font["meta"] = meta

    if out_desktop.suffix == ".ttf":
        gasp = newTable("gasp")
        gasp.gaspRange = {0xFFFF: 15}
        font["gasp"] = gasp
        if "glyf" in font:
            glyf = font["glyf"]
            if outlined := [
                glyf[g]
                for g in font.getGlyphOrder()
                if getattr(glyf[g], "numberOfContours", 0) != 0
            ]:
                font["head"].yMax, font["head"].yMin = (
                    max(g.yMax for g in outlined),
                    min(g.yMin for g in outlined),
                )
        if is_mono:
            font["OS/2"].usWinAscent = max(950, font["head"].yMax)
            font["OS/2"].usWinDescent = max(225, -font["head"].yMin)

    if "GPOS" in font:
        compact_otl(font, level=7)

    out_desktop.parent.mkdir(parents=True, exist_ok=True)
    set_font_deterministic_timestamp(font, mac_ts=mac_ts)
    font.flavor = "woff2"
    font.save(out_woff2)
    font.flavor = None
    if "CFF2" in font or "CFF " in font:
        cffsubr.subroutinize(font)
    font.save(out_desktop)
    return font["maxp"].numGlyphs


def _export_and_chws(
    font: TTFont,
    inter_path: Path,
    out_font: Path,
    out_woff2: Path,
    is_mono: bool,
    label: str = "",
) -> None:
    """Save intermediate TTF/OTF, run CHWS if proportional, and export subsetted binaries."""
    _cluster_modal_glyph_order(font, FULL_WIDTH if is_mono else 1000)
    inter_path.parent.mkdir(parents=True, exist_ok=True)
    src_path = inter_path
    font.save(src_path)
    if not is_mono:
        chws_path = inter_path.with_suffix(".chws" + inter_path.suffix)
        if label:
            print(f"Injecting chws / vchw contextual spacing ({label})...")
        asyncio.run(apply_chws(src_path, chws_path))
        src_path.unlink(missing_ok=True)
        src_path = chws_path
    num_glyphs = subset_and_export(src_path, out_font, out_woff2)
    if src_path != out_font and src_path.exists():
        src_path.unlink()
    print(
        f"  Desktop: {out_font} ({out_font.stat().st_size:,} bytes, {num_glyphs:,} glyphs)"
    )
    print(f"  WOFF2:   {out_woff2} ({out_woff2.stat().st_size:,} bytes)")


# --- Static Font Builders (Sans & Mono) ---


def build_static_style(
    family_name: str, weight: str, italic: bool = False, output_dir: Path = OUTPUT_DIR
) -> None:
    """Build a static style for Holon Sans or Holon Mono."""
    is_mono = family_name == MONO_FAMILY
    style_name, _, _ = style_names(weight, italic)
    print(f"\n=== Building {family_name} {style_name} ===")

    italic_angle = MONO_ITALIC_ANGLE if is_mono else SANS_ITALIC_ANGLE
    full_width = FULL_WIDTH if is_mono else 1000
    sub_style = (
        ("Italic" if weight == "Regular" else f"{weight}Italic") if italic else weight
    )
    pkg_dir, prefix = (
        ("plex-mono", "IBMPlexMono") if is_mono else ("plex-sans", "IBMPlexSans")
    )

    font_latin = TTFont(
        ensure_ttf_source(f"{pkg_dir}/fonts/complete/ttf/{prefix}-{sub_style}.ttf")
    )
    font_jp = TTFont(
        ensure_ttf_source(
            f"plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-{weight}.ttf"
        )
    )

    add_vertical_semicolon(font_jp)

    cmap_latin, cmap_jp = font_latin.getBestCmap(), font_jp.getBestCmap()
    rev_cmap_jp = {g: u for u, g in cmap_jp.items()}
    glyf_jp, hmtx_jp = font_jp["glyf"], font_jp["hmtx"]
    glyph_set_latin, glyph_set_jp = font_latin.getGlyphSet(), font_jp.getGlyphSet()

    new_cmap_entries, replaced_glyphs = {}, set()
    latin_matrix = (
        (SCALE_MONO_X, 0.0, 0.0, SCALE_MONO_Y, 0.0, 0.0)
        if is_mono
        else (SCALE_SANS, 0.0, 0.0, SCALE_SANS, 0.0, 0.0)
    )

    def merge_latin(gname: str, ucode: int = 0) -> None:
        if gname in replaced_glyphs or gname not in font_latin["glyf"]:
            return
        mat = (
            (SCALE_MONO_X, 0.0, 0.0, SCALE_MONO_Y, (FULL_WIDTH - HALF_WIDTH) / 2.0, 0.0)
            if (is_mono and _is_eaw_wide(ucode))
            else latin_matrix
        )
        scaled = _transform_tt_glyph(glyph_set_latin, gname, mat, glyf_jp)
        orig_w, orig_lsb = font_latin["hmtx"][gname]
        if is_mono and (
            0x2500 <= ucode <= 0x259F or "bxd" in gname or "block" in gname
        ):
            _snap_tt_box_drawing_glyph(
                scaled, glyf_jp, is_line=(0x2500 <= ucode <= 0x257F)
            )
        new_w, new_lsb = _latin_metrics(ucode, orig_w, orig_lsb, is_mono)
        if is_mono and (0x2500 <= ucode <= 0x257F):
            new_lsb = scaled.xMin
        _set_tt_glyph(font_jp, gname, scaled, new_w, lsb=new_lsb, v_adv=full_width)
        replaced_glyphs.add(gname)
        if gname == "zero.alt01" and "zero.zero" in glyf_jp:
            _set_tt_glyph(
                font_jp,
                "zero.zero",
                copy.deepcopy(scaled),
                new_w,
                lsb=new_lsb,
                v_adv=full_width,
            )
            replaced_glyphs.add("zero.zero")

    for ucode, gname in cmap_latin.items():
        if (
            0x0020 <= ucode < 0xE000
            and ucode != 0x3000
            and (is_mono or ucode not in JP_FULLWIDTH_SYMBOLS)
        ):
            merge_latin(gname, ucode)
            new_cmap_entries[ucode] = gname

    extras_list = (
        ("zero.alt01", "zero.tosf.alt01", "a.alt01", "g.alt01")
        if is_mono
        else ("zero.alt01", "a.alt01", "g.alt01", "fi", "fl")
    )
    for alt_g in extras_list:
        merge_latin(alt_g)

    slant = math.tan(math.radians(-italic_angle)) if italic else 0.0
    for gname in list(glyf_jp.keys()):
        if gname in replaced_glyphs or (not is_mono and gname == ".notdef"):
            continue
        orig_glyph, (orig_w, _) = glyf_jp[gname], hmtx_jp[gname]
        if orig_w == 0 and is_mono:
            continue
        mat, new_w = _get_jp_glyph_transform(
            family_name, gname, rev_cmap_jp.get(gname), orig_w, slant
        )

        if orig_glyph.numberOfContours == 0:
            if is_mono:
                _set_tt_glyph(
                    font_jp, gname, orig_glyph, new_w, lsb=0, v_adv=FULL_WIDTH
                )
            continue

        _set_tt_glyph(
            font_jp,
            gname,
            _transform_tt_glyph(glyph_set_jp, gname, mat, glyf_jp),
            new_w,
            v_adv=full_width if is_mono else None,
        )

    order = font_jp.getGlyphOrder()
    new_order = order + [
        g
        for g in [*new_cmap_entries.values(), *extras_list]
        if g in glyf_jp and g not in order
    ]
    font_jp.setGlyphOrder(new_order)
    font_jp["maxp"].numGlyphs = len(new_order)
    for table in font_jp["cmap"].tables:
        if table.isUnicode():
            table.cmap.update(new_cmap_entries)

    add_cjk_compatibility_mappings(font_jp)
    _fix_u3000(font_jp, full_width)
    if is_mono:
        _apply_mono_metrics_and_cleanup(font_jp, clean_gsub=True)

    ps_suffix = apply_opentype_metadata(
        font_jp, family_name, weight, italic, italic_angle
    )
    family_compact = family_name.replace(" ", "")
    inter_path = TMP_DIR / f"{family_compact}-{ps_suffix}.inter.ttf"
    final_ttf, final_woff2 = (
        output_dir / f"{family_compact}-{ps_suffix}.ttf",
        output_dir / f"{family_compact}-{ps_suffix}.woff2",
    )

    _export_and_chws(font_jp, inter_path, final_ttf, final_woff2, is_mono)


# --- Variable Font Builders & Helpers ---


def _add_vertical_semicolon_to_ufo(ufo: ufoLib2.Font) -> None:
    src_name = (
        "semicolon.full"
        if "semicolon.full" in ufo
        else ("uniFF1B" if "uniFF1B" in ufo else None)
    )
    if not src_name or f"{src_name}.vert" in ufo:
        return
    vert_name = f"{src_name}.vert"
    ng = ufo.newGlyph(vert_name)
    ng.width, ng.height, ng.verticalOrigin = 1000, 1000, 880
    ufo[src_name].drawPoints(
        TransformPointPen(ng.getPointPen(), (0.0, -1.0, 1.0, 0.0, 122.0, 878.0))
    )
    ufo.lib.setdefault("public.postscriptNames", {})[vert_name] = "uniFF1B.vert"
    if "public.glyphOrder" in ufo.lib and vert_name not in ufo.lib["public.glyphOrder"]:
        ufo.lib["public.glyphOrder"].append(vert_name)

    fea = ufo.features.text or ""
    fea = re.sub(
        r"(feature\s+(?:vert|vrt2)\s*\{[^}]*?sub\s+colon\.full\s+by\s+colon\.full\.vert;)",
        r"\1\n    sub semicolon.full by semicolon.full.vert;",
        fea,
    )
    fea = re.sub(
        r"(feature\s+(?:vert|vrt2)\s*\{[^}]*?sub\s+uniFF1A\s+by\s+uniFF1A\.vert;)",
        r"\1\n    sub uniFF1B by uniFF1B.vert;",
        fea,
    )
    ufo.features.text = fea


def _apply_ufo_cjk_transform(
    ufo: ufoLib2.Font, family_name: str, italic: bool = False
) -> None:
    """Apply proportional dual-scale or strict duospace transform to all glyphs in a UFO master."""
    is_mono = family_name == MONO_FAMILY
    slant = (
        math.tan(math.radians(-MONO_ITALIC_ANGLE if is_mono else -SANS_ITALIC_ANGLE))
        if italic
        else 0.0
    )
    ps_names = ufo.lib.get("public.postscriptNames", {})

    for g in ufo:
        unicodes = set(g.unicodes or ([] if g.unicode is None else [g.unicode]))
        u_primary = max(unicodes) if unicodes else None
        orig_w = g.width
        if is_mono:
            g.height, g.verticalOrigin = FULL_WIDTH, 880
        elif g.height == 1000:
            g.verticalOrigin = 880

        if unicodes & {0x3000, 0x2003, 0x2001}:
            g.width = FULL_WIDTH if is_mono else 1000
            continue
        if unicodes & {0x2000, 0x2002}:
            g.width = HALF_WIDTH if is_mono else 500
            continue
        if is_mono and orig_w == 0:
            continue

        mat, target_w = _get_jp_glyph_transform(
            family_name, ps_names.get(g.name, g.name), u_primary, orig_w, slant
        )
        _transform_ufo_glyph(g, mat)
        g.width = target_w


def decompose_ufo(ufo: ufoLib2.Font) -> None:
    """Decompose all components into outlines within a UFO font."""
    for g in ufo:
        if g.components:
            rpen = DecomposingRecordingPointPen(ufo)
            g.drawPoints(rpen)
            g.clearComponents()
            g.clearContours()
            rpen.replay(g.getPointPen())


def _merge_variable_latin(
    dst_ufos: list[ufoLib2.Font],
    latin_masters_dir: Path,
    is_mono: bool,
    italic: bool = False,
) -> int:
    """Merge Latin/symbol glyphs from IBM Plex Sans/Mono masters into Japanese UFO masters."""
    prefix = "IBM Plex Mono Var" if is_mono else "IBM Plex Sans Var"
    stems = (
        ("Thin Italic", "Italic", "Bold Italic")
        if italic
        else ("Thin", "Regular", "Bold")
    )
    src_ufos = tuple(
        ufoLib2.Font.open(latin_masters_dir / f"{prefix}-{stem}.ufo") for stem in stems
    )
    for s_ufo in src_ufos:
        decompose_ufo(s_ufo)
    for u in dst_ufos:
        u.kerning.clear()

    ufo_reg = dst_ufos[1]
    u_to_jp_gname = {u: g.name for g in ufo_reg for u in (g.unicodes or [])}
    ps_to_jp_gname = {
        v: k for k, v in ufo_reg.lib.get("public.postscriptNames", {}).items()
    }
    all_src_unicodes = {
        u
        for g in src_ufos[1]
        for u in (g.unicodes or ([g.unicode] if g.unicode is not None else []))
    }
    full_v_adv = FULL_WIDTH if is_mono else 1000

    added = 0
    for g_r in src_ufos[1]:
        unicodes = set(g_r.unicodes or ([] if g_r.unicode is None else [g_r.unicode]))
        if not is_mono:
            if not unicodes and g_r.name not in (
                "zero.alt01",
                "a.alt01",
                "g.alt01",
                "fi",
                "fl",
            ):
                continue
            if unicodes & JP_FULLWIDTH_SYMBOLS or any(
                uc < 0x0020 or (0xE000 <= uc < 0xF900) for uc in unicodes
            ):
                continue
        if 0x3000 in unicodes:
            continue

        for prev_name in {g_r.name, ps_to_jp_gname.get(g_r.name)}:
            if prev_name and prev_name in ufo_reg:
                for extra_u in ufo_reg[prev_name].unicodes or []:
                    if (
                        extra_u not in all_src_unicodes
                        and extra_u != 0x3000
                        and (
                            is_mono
                            or (
                                extra_u not in JP_FULLWIDTH_SYMBOLS
                                and extra_u != 0x02C9
                            )
                        )
                    ):
                        unicodes.add(extra_u)

        for uc in unicodes:
            if uc in u_to_jp_gname and (old_g := u_to_jp_gname[uc]) != g_r.name:
                for dst_u in dst_ufos:
                    if old_g in dst_u:
                        dst_u[old_g].unicodes = [
                            x for x in (dst_u[old_g].unicodes or []) if x != uc
                        ]

        for dst_u in dst_ufos:
            ps_map = dst_u.lib.get("public.postscriptNames", {})
            ps_map.pop(g_r.name, None)
            if (old_jp := ps_to_jp_gname.get(g_r.name)) and old_jp != g_r.name:
                ps_map.pop(old_jp, None)

        is_box = is_mono and (
            bool(unicodes & set(range(0x2500, 0x25A0)))
            or "bxd" in g_r.name
            or "block" in g_r.name
        )
        is_wide = is_mono and (
            bool(unicodes & {0x2003}) or any(_is_eaw_wide(u) for u in unicodes)
        )
        dx = (
            (FULL_WIDTH - HALF_WIDTH) / 2.0
            if (is_mono and any(_is_eaw_wide(u) for u in unicodes))
            else 0.0
        )
        fixed_w = (
            1000
            if (unicodes & {0x2001, 0x2003})
            else (500 if (unicodes & {0x2000, 0x2002}) else None)
        )
        sorted_u = sorted(unicodes)

        for dst_u, src_u in zip(dst_ufos, src_ufos):
            src_g = src_u[g_r.name]
            ng = dst_u.newGlyph(g_r.name) if g_r.name not in dst_u else dst_u[g_r.name]
            ng.clear()
            ng.unicodes = sorted_u
            ng.height, ng.verticalOrigin = full_v_adv, 880
            if is_mono:
                ng.width = (
                    0 if src_g.width == 0 else (FULL_WIDTH if is_wide else HALF_WIDTH)
                )
                src_g.drawPoints(ng.getPointPen())
                for c in ng.contours:
                    for p in c.points:
                        p.x = p.x * SCALE_MONO_X + dx
                        p.y = (
                            950.0
                            if (is_box and p.y >= 800)
                            else (
                                -225.0
                                if (is_box and p.y <= -250)
                                else p.y * SCALE_MONO_Y
                            )
                        )
            else:
                ng.width = (
                    fixed_w
                    if fixed_w is not None
                    else (
                        round(src_g.width * SCALE_SANS)
                        if not g_r.name.endswith(".rotat")
                        else src_g.width
                    )
                )
                src_g.drawPoints(
                    TransformPointPen(
                        ng.getPointPen(), (SCALE_SANS, 0.0, 0.0, SCALE_SANS, 0.0, 0.0)
                    )
                )
                if g_r.name == "zero.alt01" and "zero.zero" in dst_u:
                    zg = dst_u["zero.zero"]
                    zg.clear()
                    zg.height, zg.verticalOrigin = full_v_adv, 880
                    zg.width = ng.width
                    src_g.drawPoints(
                        TransformPointPen(
                            zg.getPointPen(),
                            (SCALE_SANS, 0.0, 0.0, SCALE_SANS, 0.0, 0.0),
                        )
                    )
            if (
                "public.glyphOrder" in dst_u.lib
                and g_r.name not in dst_u.lib["public.glyphOrder"]
            ):
                dst_u.lib["public.glyphOrder"].append(g_r.name)
        added += 1

    if not is_mono:
        for dst_u in dst_ufos:
            if "macroncomb" in dst_u:
                dst_u["macroncomb"].width = 0
                if 0x02C9 not in (dst_u["macroncomb"].unicodes or []):
                    dst_u["macroncomb"].unicodes = [
                        *(dst_u["macroncomb"].unicodes or []),
                        0x02C9,
                    ]
            for g in dst_u:
                if g.name != "macroncomb" and 0x02C9 in (g.unicodes or []):
                    g.unicodes = [x for x in g.unicodes if x != 0x02C9]
    return added


def _make_grade_master(
    ufo_base: ufoLib2.Font,
    ufo_target: ufoLib2.Font,
    factor: float,
    name: str,
    family_name: str = SANS_FAMILY,
) -> ufoLib2.Font:
    """Create a Grade master by interpolating stroke weight while locking advance widths to base."""
    new_f = ufoLib2.Font()
    new_f.info = copy.deepcopy(ufo_base.info)
    new_f.info.familyName, new_f.info.styleName = family_name, name
    new_f.features.text, new_f.groups, new_f.lib = (
        ufo_base.features.text,
        copy.deepcopy(ufo_base.groups),
        copy.deepcopy(ufo_base.lib),
    )

    for g_base in ufo_base:
        gname = g_base.name
        ng = new_f.newGlyph(gname)
        ng.width, ng.height, ng.verticalOrigin = (
            g_base.width,
            g_base.height,
            g_base.verticalOrigin,
        )
        ng.unicodes = list(g_base.unicodes or [])

        if gname not in ufo_target or len(g_base.contours) != len(
            ufo_target[gname].contours
        ):
            g_base.drawPoints(ng.getPointPen())
            continue

        g_tgt = ufo_target[gname]
        if any(
            len(ca.points) != len(cb.points)
            for ca, cb in zip(g_base.contours, g_tgt.contours)
        ):
            g_base.drawPoints(ng.getPointPen())
            continue

        dx = -(factor * (g_tgt.width - g_base.width)) / 2.0
        ppen = ng.getPointPen()
        for ca, cb in zip(g_base.contours, g_tgt.contours):
            ppen.beginPath()
            for pa, pb in zip(ca.points, cb.points):
                ppen.addPoint(
                    (pa.x + factor * (pb.x - pa.x) + dx, pa.y + factor * (pb.y - pa.y)),
                    segmentType=pa.segmentType,
                    smooth=pa.smooth,
                    name=pa.name,
                )
            ppen.endPath()

    return new_f


def _make_variable_designspace(
    masters: list[ufoLib2.Font], italic: bool, family_name: str = SANS_FAMILY
) -> DesignSpaceDocument:
    var_ds = DesignSpaceDocument()
    ax_wght, ax_grad = AxisDescriptor(), AxisDescriptor()
    ax_wght.tag, ax_wght.name, ax_wght.minimum, ax_wght.default, ax_wght.maximum = (
        "wght",
        "Weight",
        100,
        400,
        700,
    )
    ax_wght.map = list(WEIGHT_DESIGN_MAP)
    ax_grad.tag, ax_grad.name, ax_grad.minimum, ax_grad.default, ax_grad.maximum = (
        "GRAD",
        "Grade",
        -100,
        0,
        100,
    )
    var_ds.addAxis(ax_wght)
    var_ds.addAxis(ax_grad)

    sfx = " Italic" if italic else ""
    for font_obj, loc, sname in [
        (masters[0], {"Weight": 100, "Grade": 0}, f"Thin{sfx}"),
        (masters[1], {"Weight": 360, "Grade": 0}, f"Regular{sfx}"),
        (masters[2], {"Weight": 700, "Grade": 0}, f"Bold{sfx}"),
        (masters[3], {"Weight": 360, "Grade": 100}, f"Regular{sfx} Grade+"),
        (masters[4], {"Weight": 360, "Grade": -100}, f"Regular{sfx} Grade-"),
    ]:
        src = SourceDescriptor()
        src.font, src.location, src.name, src.styleName, src.familyName = (
            font_obj,
            loc,
            sname,
            sname,
            family_name,
        )
        var_ds.addSource(src)

    for w_name in WEIGHTS:
        inst = InstanceDescriptor()
        inst.familyName, inst.styleName = family_name, style_names(w_name, italic)[0]
        inst.location = {
            "Weight": ax_wght.map_forward(WEIGHT_VALUES[w_name]),
            "Grade": 0,
        }
        var_ds.addInstance(inst)
    return var_ds


def _restore_sans_gpos_and_base(var_font: TTFont) -> None:
    """Copy full GPOS (kern, palt, vpal, halt, vhal, vkrn) and BASE from upstream JP Regular into Variable Sans."""
    ref_jp = TTFont(
        ensure_ttf_source(
            "plex-sans-jp/fonts/complete/ttf/unhinted/IBMPlexSansJP-Regular.ttf"
        )
    )
    for tag in ("BASE", "GPOS"):
        if tag in ref_jp:
            var_font[tag] = copy.deepcopy(ref_jp[tag])
    _sync_otl_glyph_order(var_font)


def _compile_and_export_vf(
    var_ds: DesignSpaceDocument,
    italic: bool,
    family_name: str = SANS_FAMILY,
    output_dir: Path = OUTPUT_DIR,
) -> None:
    style_label, family_compact = (
        ("Italic" if italic else "Roman"),
        family_name.replace(" ", ""),
    )
    is_mono = family_name == MONO_FAMILY
    inter_otf = TMP_DIR / f"{family_compact}-{style_label}-Variable.inter.otf"

    print(f"Compiling CFF2 variable font ({family_name} {style_label})...")
    var_font = ufo2ft.compileVariableCFF2(var_ds)

    ps_suffix = apply_opentype_metadata(
        var_font,
        family_name,
        "Regular",
        italic,
        MONO_ITALIC_ANGLE if is_mono else SANS_ITALIC_ANGLE,
        is_variable=True,
    )
    _fix_u3000(var_font, FULL_WIDTH if is_mono else 1000)

    if is_mono:
        if 0x0020 in (cmap_best := var_font.getBestCmap()) and "vmtx" in var_font:
            var_font["hmtx"][cmap_best[0x0020]] = (HALF_WIDTH, 0)
            var_font["vmtx"].metrics[cmap_best[0x0020]] = (FULL_WIDTH, 880)
        _apply_mono_metrics_and_cleanup(var_font, clean_gsub=False)
    else:
        _restore_sans_gpos_and_base(var_font)

    out_otf, out_woff2 = (
        output_dir / f"{family_compact}-{ps_suffix}.otf",
        output_dir / f"{family_compact}-{ps_suffix}.woff2",
    )
    _export_and_chws(
        var_font, inter_otf, out_otf, out_woff2, is_mono, label=style_label
    )


def _get_base_jp_ufos(glyphs_path: Path) -> list[ufoLib2.Font]:
    """Load, decompose, and prepare Japanese UFO masters once per process."""
    global _BASE_JP_UFOS
    if _BASE_JP_UFOS is None:
        t0 = time.time()
        ds = to_designspace(GSFont(str(glyphs_path)), minimal=True)
        print(f"Loaded Glyphs source in {time.time() - t0:.1f}s.")
        _BASE_JP_UFOS = [ds.sources[0].font, ds.sources[1].font, ds.sources[2].font]
        for u in _BASE_JP_UFOS:
            u.lib.pop("com.github.googlei18n.ufo2ft.filters", None)
            decompose_ufo(u)
            for g in u:
                if ORIGINAL_WIDTH_KEY in g.lib:
                    g.width = g.lib[ORIGINAL_WIDTH_KEY]
            if "uni51F0" in u:
                u["uni51F0"].width = 1000
            if "emptyset.full" in u and "emptyset" in u:
                u["emptyset.full"].unicodes, u["emptyset"].unicodes = [], [0x2205]
            _add_vertical_semicolon_to_ufo(u)
        add_cjk_compatibility_mappings_to_ufos(_BASE_JP_UFOS)
    return _BASE_JP_UFOS


def build_family_variable_fonts(
    family_name: str, style: str = "both", output_dir: Path = OUTPUT_DIR
) -> None:
    """Build 2-file Variable Fonts for Holon Sans or Holon Mono."""
    is_mono = family_name == MONO_FAMILY
    full_width = FULL_WIDTH if is_mono else 1000
    glyphs_path, latin_masters_dir = ensure_variable_sources(
        "mono" if is_mono else "sans"
    )
    print(f"\n=== Building {family_name} Variable Fonts (2-File Architecture) ===")
    base_ufos = _get_base_jp_ufos(glyphs_path)

    for s in ("roman", "italic") if style == "both" else (style,):
        italic = s == "italic"
        ufos = [copy.deepcopy(u) for u in base_ufos]
        for u in ufos:
            u.info.familyName = family_name
            _apply_ufo_cjk_transform(u, family_name, italic=italic)
        added = _merge_variable_latin(
            ufos, latin_masters_dir, is_mono=is_mono, italic=italic
        )
        print(
            f"Merged {added} IBM Plex {'Mono' if is_mono else 'Sans'} UFO glyphs ({'Italic' if italic else 'Roman'})."
        )

        order = sorted(
            ufos[1].glyphOrder,
            key=lambda g: (
                g != ".notdef",
                g in ufos[1]
                and all(
                    m[g].width == full_width and m[g].height == full_width for m in ufos
                ),
            ),
        )
        for u in ufos:
            u.glyphOrder = order
            cats = u.lib.get("public.openTypeCategories", {})
            for gname, cat in list(cats.items()):
                if cat == "mark" and gname in u and u[gname].width > 0:
                    cats[gname] = "base"

        suffix = " Italic" if italic else ""
        u_gp = _make_grade_master(
            ufos[1], ufos[2], 0.15, f"Regular{suffix} Grade+", family_name=family_name
        )
        u_gn = _make_grade_master(
            ufos[1], ufos[0], 0.15, f"Regular{suffix} Grade-", family_name=family_name
        )
        var_ds = _make_variable_designspace(
            [*ufos, u_gp, u_gn], italic=italic, family_name=family_name
        )
        _compile_and_export_vf(
            var_ds, italic, family_name=family_name, output_dir=output_dir
        )


# --- Font Subsetter ---


def subset_single_font(
    src_path: Path,
    out_dir: Path,
    unicodes: set[int],
    mac_timestamp: int | None = None,
) -> tuple[str, int, int, int]:
    """Subset a single font file into desktop (TTF/OTF) and WOFF2 formats."""
    out_desktop = out_dir / src_path.name
    out_woff2 = out_dir / (src_path.stem + ".woff2")
    subset_and_export(
        src_path, out_desktop, out_woff2, unicodes=unicodes, mac_ts=mac_timestamp
    )
    return (
        src_path.name,
        src_path.stat().st_size,
        out_desktop.stat().st_size,
        out_woff2.stat().st_size,
    )


def build_subset_fonts(
    input_dir: Path = OUTPUT_DIR, output_dir: Path = SUBSET_DIR
) -> None:
    """Subset all desktop fonts in input_dir to output_dir using the built-in Joyo Kanji character set."""
    if not input_dir.exists():
        print(f"Error: Input directory {input_dir} does not exist.", file=sys.stderr)
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    unicodes = {ord(c) for c in SUBSET_CHARACTERS}

    candidates = sorted(
        [p for p in input_dir.iterdir() if p.is_file() and p.suffix in (".ttf", ".otf")]
    )
    if not candidates:
        print(f"No matching font files found in {input_dir}.", file=sys.stderr)
        return

    print(
        f"Subsetting {len(candidates)} font files from {input_dir} to {output_dir}..."
    )
    t0 = time.time()
    mac_ts = get_build_mac_timestamp()
    results = []
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=os.cpu_count() or 4
    ) as executor:
        futures = {
            executor.submit(subset_single_font, src, output_dir, unicodes, mac_ts): src
            for src in candidates
        }
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            results.append(res)
            name, orig_sz, desk_sz, woff_sz = res
            pct = (1.0 - desk_sz / orig_sz) * 100
            print(
                f"  [OK] {name:32s}: {orig_sz / 1024 / 1024:5.2f} MB -> {desk_sz / 1024 / 1024:5.2f} MB ({pct:5.1f}% off) | WOFF2: {woff_sz / 1024 / 1024:5.2f} MB"
            )

    elapsed = time.time() - t0
    tot_orig = sum(r[1] for r in results)
    tot_desk = sum(r[2] for r in results)
    tot_pct = (1.0 - tot_desk / tot_orig) * 100 if tot_orig else 0
    print(
        f"Subsetting complete in {elapsed:.1f}s ({tot_orig / 1024 / 1024:.1f} MB -> {tot_desk / 1024 / 1024:.1f} MB, {tot_pct:.1f}% reduction)."
    )


# --- CLI Entry Point ---


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Holon Sans (Static & Variable) and Holon Mono (Static & Variable)."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Build full suite: Sans & Mono (all static weights + italics), variable fonts, and subset fonts",
    )
    parser.add_argument(
        "--full-only",
        action="store_true",
        help="Build all full fonts (Sans & Mono static + variable) without generating subsets",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove generated font directories (fonts/full, fonts/subset) and tmp/",
    )
    parser.add_argument(
        "--family",
        choices=["sans", "mono", "sans-variable", "mono-variable", "variable", "all"],
        default="sans",
        help="Font family to build (default: sans; use 'variable' for both VFs, 'all' for full suite)",
    )
    parser.add_argument(
        "--weight",
        choices=[*WEIGHTS, "all"],
        default="Regular",
        help="Weight to build for static fonts (default: Regular, or 'all')",
    )
    parser.add_argument(
        "--italic", action="store_true", help="Build Italic style for static fonts"
    )
    parser.add_argument(
        "--all-styles",
        action="store_true",
        help="Build all weights and styles (Upright and Italic)",
    )
    parser.add_argument(
        "--var-style",
        choices=["roman", "italic", "both"],
        default="both",
        help="Variable font style to build when --family is variable, mono-variable, sans-variable or all (default: both)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory where full fonts are saved (default: fonts/full)",
    )
    parser.add_argument(
        "--subset",
        action="store_true",
        help="Generate Joyo Kanji subset fonts (saved to fonts/subset)",
    )
    parser.add_argument(
        "--subset-only",
        action="store_true",
        help="Only run subset generation from full fonts without rebuilding",
    )
    parser.add_argument(
        "--subset-dir",
        type=Path,
        default=SUBSET_DIR,
        help="Directory where subset fonts are saved (default: fonts/subset)",
    )
    parser.add_argument(
        "--timestamp",
        type=int,
        default=None,
        help="Deterministic Unix timestamp for reproducible builds (default: latest git commit or 2026-01-01)",
    )
    args = parser.parse_args()

    if args.clean:
        for d in (args.output_dir, args.subset_dir, TMP_DIR):
            if d.exists():
                print(f"Cleaning {d}...")
                shutil.rmtree(d)
        fonts_parent = Path("fonts")
        if fonts_parent.is_dir() and not any(fonts_parent.iterdir()):
            fonts_parent.rmdir()
        print("Clean completed successfully.")
        return

    unix_ts = configure_build_timestamp(args.timestamp)
    utc_dt = datetime.datetime.fromtimestamp(unix_ts, datetime.UTC)
    print(
        f"=== Holon Font Builder (Deterministic Timestamp: {utc_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}, Unix: {unix_ts}) ==="
    )

    if args.all:
        args.family = "all"
        args.all_styles = True
        args.subset = True
    elif args.full_only:
        args.family = "all"
        args.all_styles = True
        args.subset = False

    if args.subset_only:
        build_subset_fonts(input_dir=args.output_dir, output_dir=args.subset_dir)
        return

    weights = WEIGHTS if (args.all_styles or args.weight == "all") else [args.weight]
    italics = [False, True] if args.all_styles else [args.italic]

    for fam_key, fam_name in (("sans", SANS_FAMILY), ("mono", MONO_FAMILY)):
        if args.family in (fam_key, "all"):
            for w in weights:
                for it in italics:
                    build_static_style(
                        fam_name, w, italic=it, output_dir=args.output_dir
                    )

    if args.family in ("sans-variable", "mono-variable", "variable", "all"):
        var_fams = (
            (SANS_FAMILY,)
            if args.family == "sans-variable"
            else (
                (MONO_FAMILY,)
                if args.family == "mono-variable"
                else (SANS_FAMILY, MONO_FAMILY)
            )
        )
        for fam_name in var_fams:
            build_family_variable_fonts(
                fam_name, style=args.var_style, output_dir=args.output_dir
            )

    if args.subset:
        build_subset_fonts(input_dir=args.output_dir, output_dir=args.subset_dir)


if __name__ == "__main__":
    main()
