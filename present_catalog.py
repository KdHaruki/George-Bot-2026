"""Bot gift categories. Stable item IDs retain inventories and title progress."""
from progress_profiles import profile_for


CATEGORIES = {
    'food': ('食べ物・飲み物', ('sweets', 'food')),
    'fashion': ('ファッション・美容', ('fashion', 'mirror')),
    'knowledge': ('本・知識', ('book', 'pen')),
    'play': ('遊び・芸術', ('game', 'music')),
    'adventure': ('運動・冒険', ('towel', 'charm')),
    'craft': ('魔法・機械', ('magic', 'tools')),
    'comfort': ('花・癒やし', ('plant', 'aroma')),
}
ITEMS = {
    'sweets': ('🍪', 'チョコクッキー'), 'food': ('☕', '紅茶'),
    'fashion': ('🎀', 'リボン'), 'mirror': ('🪞', '手鏡'),
    'book': ('📖', '本'), 'pen': ('🖋️', '万年筆'),
    'game': ('🧸', 'ぬいぐるみ'), 'music': ('🎵', 'オルゴール'),
    'towel': ('🧺', 'タオル'), 'charm': ('🧿', 'お守り'),
    'magic': ('📕', '魔道書'), 'tools': ('🧰', '工具セット'),
    'plant': ('🪴', '鉢植え'), 'aroma': ('🕯️', 'アロマセット'),
    'rare': ('💐', '虹色の花束'),
}
NORMAL_ITEMS = tuple(key for key in ITEMS if key != 'rare')

# Selection is explicit per character and per item; categories only organize the catalogue.
from present_preferences import PREFERENCES


def preferred_items(character):
    record = profile_for(character)
    return PREFERENCES.get(record['progressName'], ()) if record else ()


def preferred_labels(character):
    return '、'.join(ITEMS[item][1] for item in preferred_items(character)) or '設定なし'
