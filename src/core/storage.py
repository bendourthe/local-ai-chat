"""
Persistent chat storage using JSON files under the user's home directory.

Chats are saved to `~/.local-ai-chat/chat_history/` using the filename pattern
`YYYY-MM-DD_{chat_name}.json`, where the date is the chat creation date
(defined as the date of the first user request) and the name is the current
chat title. If the user renames the chat, the file is renamed accordingly.

Provides list, load, save, delete operations. Also preserves the existing
downloaded models registry under the legacy base path.

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""
import json
import os
import re
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

def _base_dir() -> str:
    """Return legacy base dir for models registry (kept unchanged)."""
    if os.name == 'nt':
        root = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    else:
        root = os.path.join(os.path.expanduser('~'), '.local', 'share')
    return os.path.join(root, 'FoundryLocalChat')

def _chat_base_dir() -> str:
    """Return the base directory for chats under user's home (~/.local-ai-chat)."""
    return os.path.join(os.path.expanduser('~'), '.local-ai-chat')

_CHATS_DIR = os.path.join(_chat_base_dir(), 'chat_history')
_MODELS_FILE = os.path.join(_base_dir(), 'data', 'models.json')

def _ensure_dirs() -> None:
    """Create chat and models directories if absent."""
    os.makedirs(_CHATS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(_MODELS_FILE), exist_ok=True)

def _slug(title: str) -> str:
    """Sanitize a title for safe filesystem use on all platforms."""
    t = (title or 'Untitled').strip()
    t = re.sub(r"[\\/:*?\"<>|]", "_", t)
    t = re.sub(r"\s+", " ", t)
    t = t.strip(" .")
    if not t:
        t = 'Untitled'
    return t[:120]

def _date_from_iso(iso: Optional[str]) -> str:
    """Extract YYYY-MM-DD from an ISO timestamp (fallback to today)."""
    try:
        dt = datetime.fromisoformat(iso) if iso else datetime.utcnow()
    except Exception:
        dt = datetime.utcnow()
    return dt.strftime('%Y-%m-%d')

def _build_filename(title: str, created_iso: Optional[str]) -> str:
    """Return target filename for a chat based on date and title."""
    date_str = _date_from_iso(created_iso)
    return f"{date_str}_{_slug(title)}.json"

def _find_chat_path_by_id(chat_id: str) -> Optional[str]:
    """Scan chat history to find the file path for a given chat id."""
    _ensure_dirs()
    try:
        for name in os.listdir(_CHATS_DIR):
            if not name.endswith('.json'):
                continue
            p = os.path.join(_CHATS_DIR, name)
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                if d.get('id') == chat_id:
                    return p
            except Exception:
                continue
    except Exception:
        pass
    return None

def _unique_path_for(filename: str) -> str:
    """Ensure the returned path is unique by adding a numeric suffix if needed."""
    base, ext = os.path.splitext(filename)
    path = os.path.join(_CHATS_DIR, filename)
    if not os.path.exists(path):
        return path
    i = 1
    while True:
        cand = os.path.join(_CHATS_DIR, f"{base} ({i}){ext}")
        if not os.path.exists(cand):
            return cand
        i += 1

def _chat_path(chat_id: str) -> Optional[str]:
    """Return file path for a chat id by scanning files (may be None)."""
    return _find_chat_path_by_id(chat_id)

def list_chats() -> List[Dict]:
    """
    Return chat metadata list sorted by updated time desc.

    Returns:
        - list[dict]: [{id,title,created_at,updated_at}]
    """
    _ensure_dirs()
    items: List[Tuple[str, Dict]] = []
    try:
        for name in os.listdir(_CHATS_DIR):
            if not name.endswith('.json'):
                continue
            p = os.path.join(_CHATS_DIR, name)
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                continue
            chat_id = data.get('id') or uuid.uuid4().hex
            meta = {
                'id': chat_id,
                'title': data.get('title') or 'Untitled',
                'created_at': data.get('created_at') or datetime.utcnow().isoformat(),
                'updated_at': data.get('updated_at') or data.get('created_at') or datetime.utcnow().isoformat(),
            }
            items.append((meta['updated_at'], meta))
    except Exception:
        pass
    items.sort(key=lambda t: t[0], reverse=True)
    return [m for _, m in items]

def create_chat(title: str) -> str:
    """
    Create a new chat file and return its id. The filename uses today's date
    initially and will be corrected to the date of the first user message on
    first save.

    Parameters:
        - title (str): Chat title

    Returns:
        - str: Chat id
    """
    _ensure_dirs()
    chat_id = uuid.uuid4().hex
    now = datetime.utcnow().isoformat()
    data = {'id': chat_id, 'title': title or 'New Chat', 'messages': [], 'created_at': now, 'updated_at': now}
    fname = _build_filename(data['title'], data['created_at'])
    path = _unique_path_for(fname)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return chat_id

def rename_chat(chat_id: str, title: str) -> None:
    """Rename an existing chat and its file to match the new title."""
    path = _find_chat_path_by_id(chat_id)
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data['title'] = title or data.get('title') or 'Untitled'
        data['updated_at'] = datetime.utcnow().isoformat()
        # Write changes first
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # Compute new filename based on created_at and new title
        target_name = _build_filename(data.get('title') or 'Untitled', data.get('created_at'))
        target_path = os.path.join(_CHATS_DIR, target_name)
        if os.path.normcase(os.path.abspath(path)) != os.path.normcase(os.path.abspath(target_path)):
            target_path = _unique_path_for(target_name)
            try:
                os.replace(path, target_path)
            except Exception:
                pass
    except Exception:
        pass

def load_chat(chat_id: str) -> Optional[Dict]:
    """Load chat data by id."""
    path = _find_chat_path_by_id(chat_id)
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def save_messages(chat_id: str, messages: List[Dict]) -> None:
    """Persist messages array to a chat, update timestamps, and adjust filename."""
    path = _find_chat_path_by_id(chat_id)
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        was_empty = len(data.get('messages') or []) == 0
        data['messages'] = messages
        # If first user message arrives now, set created_at to its date
        if was_empty and messages:
            try:
                first_user_ts = None
                for m in messages:
                    if m.get('role') == 'user':
                        first_user_ts = m.get('ts')
                        break
                data['created_at'] = first_user_ts or data.get('created_at') or datetime.utcnow().isoformat()
            except Exception:
                data['created_at'] = data.get('created_at') or datetime.utcnow().isoformat()
        data['updated_at'] = datetime.utcnow().isoformat()
        # Write content first
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # If created_at just got set (or title changed previously), ensure filename matches policy
        desired_name = _build_filename(data.get('title') or 'Untitled', data.get('created_at'))
        desired_path = os.path.join(_CHATS_DIR, desired_name)
        if os.path.normcase(os.path.abspath(path)) != os.path.normcase(os.path.abspath(desired_path)):
            desired_path = _unique_path_for(desired_name)
            try:
                os.replace(path, desired_path)
            except Exception:
                pass
    except Exception:
        pass

def delete_chat(chat_id: str) -> None:
    """Delete chat file by id."""
    path = _find_chat_path_by_id(chat_id)
    try:
        if path and os.path.exists(path):
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
