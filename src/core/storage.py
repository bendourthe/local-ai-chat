"""
Persistent chat storage using JSON files under `data/chats/`.

Provides list, load, save, delete operations.

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""
import json
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

def _base_dir() -> str:
    """Return base data dir (LocalAppData on Windows, ~/.local/share otherwise)."""
    if os.name == 'nt':
        root = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    else:
        root = os.path.join(os.path.expanduser('~'), '.local', 'share')
    return os.path.join(root, 'FoundryLocalChat')

_CHATS_DIR = os.path.join(_base_dir(), 'data', 'chats')
_MODELS_FILE = os.path.join(_base_dir(), 'data', 'models.json')

def _ensure_dirs() -> None:
    """Create data directories if absent."""
    os.makedirs(_CHATS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(_MODELS_FILE), exist_ok=True)

def _chat_path(chat_id: str) -> str:
    """Return file path for a chat id."""
    return os.path.join(_CHATS_DIR, f"{chat_id}.json")

def list_chats() -> List[Dict]:
    """
    Return chat metadata list sorted by updated time desc.

    Returns:
        - list[dict]: [{id,title,created_at,updated_at}]
    """
    _ensure_dirs()
    items: List[Tuple[str, Dict]] = []
    for name in os.listdir(_CHATS_DIR):
        if not name.endswith('.json'):
            continue
        chat_id = name[:-5]
        try:
            with open(_chat_path(chat_id), 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue
        meta = {
            'id': chat_id,
            'title': data.get('title') or 'Untitled',
            'created_at': data.get('created_at') or datetime.utcnow().isoformat(),
            'updated_at': data.get('updated_at') or data.get('created_at') or datetime.utcnow().isoformat(),
        }
        items.append((meta['updated_at'], meta))
    items.sort(key=lambda t: t[0], reverse=True)
    return [m for _, m in items]

def create_chat(title: str) -> str:
    """
    Create a new chat with a title and return its id.

    Parameters:
        - title (str): Chat title

    Returns:
        - str: Chat id
    """
    _ensure_dirs()
    chat_id = uuid.uuid4().hex
    now = datetime.utcnow().isoformat()
    data = {'id': chat_id, 'title': title or 'New Chat', 'messages': [], 'created_at': now, 'updated_at': now}
    with open(_chat_path(chat_id), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return chat_id

def rename_chat(chat_id: str, title: str) -> None:
    """Rename an existing chat."""
    path = _chat_path(chat_id)
    if not os.path.exists(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data['title'] = title or data.get('title') or 'Untitled'
        data['updated_at'] = datetime.utcnow().isoformat()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_chat(chat_id: str) -> Optional[Dict]:
    """Load chat data by id."""
    path = _chat_path(chat_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def save_messages(chat_id: str, messages: List[Dict]) -> None:
    """Persist messages array to a chat and update timestamp."""
    path = _chat_path(chat_id)
    if not os.path.exists(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data['messages'] = messages
        data['updated_at'] = datetime.utcnow().isoformat()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def delete_chat(chat_id: str) -> None:
    """Delete chat file by id."""
    path = _chat_path(chat_id)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

# ---- Downloaded models registry ----

def _read_models() -> Dict:
    """Read models.json, returning structure with key 'downloaded'."""
    _ensure_dirs()
    if not os.path.exists(_MODELS_FILE):
        return {'downloaded': []}
    try:
        with open(_MODELS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'downloaded' in data and isinstance(data['downloaded'], list):
                return data
            return {'downloaded': []}
    except Exception:
        return {'downloaded': []}

def _write_models(data: Dict) -> None:
    """Write models.json safely."""
    _ensure_dirs()
    with open(_MODELS_FILE, 'w', encoding='utf-8') as f:
        json.dump({'downloaded': sorted(set(data.get('downloaded', [])))}, f, ensure_ascii=False, indent=2)

def get_downloaded_models() -> List[str]:
    """Return list of downloaded models tracked locally."""
    return sorted(set(_read_models().get('downloaded', [])))

def add_downloaded_model(name: str) -> None:
    """Add a model to the downloaded registry."""
    data = _read_models()
    d = set(data.get('downloaded', []))
    d.add(name)
    data['downloaded'] = sorted(d)
    _write_models(data)

def remove_downloaded_model(name: str) -> None:
    """Remove a model from the downloaded registry."""
    data = _read_models()
    d = set(data.get('downloaded', []))
    if name in d:
        d.remove(name)
    data['downloaded'] = sorted(d)
    _write_models(data)

def set_downloaded_models(names: List[str]) -> None:
    """Replace the downloaded registry with provided names."""
    _write_models({'downloaded': list(sorted(set(names)))})

def migrate_downloaded_aliases(pairs: List[Tuple[str, str]]) -> None:
    """Add model IDs for any legacy alias names in the downloaded registry.

    Parameters:
        - pairs (list[tuple[str,str]]): (alias, model_id) pairs from `foundry cache list`
    """
    if not pairs:
        return
    data = _read_models()
    d = set(data.get('downloaded', []))
    alias_to_id = {a: mid for a, mid in pairs}
    changed = False
    for name in list(d):
        if name in alias_to_id and alias_to_id[name] not in d:
            d.add(alias_to_id[name])
            changed = True
    if changed:
        _write_models({'downloaded': sorted(d)})
