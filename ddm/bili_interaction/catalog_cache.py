"""Bounded display snapshots; cached permissions never authorize a send."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from ddm import config

_MAX_BYTES=4*1024*1024
_MAX_FILES=32
_MAX_AGE=7*24*60*60
_PACKAGE_FIELDS=('pkg_id','pkg_type','pkg_name','current_cover')
_EMOTE_FIELDS=('emoji','emoticon_unique','perm','url','unlock_show_text','width','height')

def _packages(value):
    if not isinstance(value,list) or len(value)>256:return None
    result=[]
    for package in value:
        if not isinstance(package,dict):return None
        emotes=package.get('emoticons')
        if emotes is not None and (not isinstance(emotes,list) or len(emotes)>5000 or
                                  any(not isinstance(e,dict) for e in emotes)):return None
        row={key:deepcopy(package[key]) for key in _PACKAGE_FIELDS if key in package}
        row['emoticons']=[{key:deepcopy(e[key]) for key in _EMOTE_FIELDS if key in e} for e in emotes or []]
        result.append(row)
    return result

def preview_packages(packages):
    result=deepcopy(packages)
    for package in result:
        for emote in package.get('emoticons') or []:
            emote.update(perm=0,unlock_show_text='正在确认当前账号权限，请刷新后再试')
    return result

class CatalogCache:
    def __init__(self,path=None):
        self.root=Path(path) if path is not None else Path(config.data_root())/'cache/bili_live/catalogs'
        self.enabled=path is not None or not bool(os.environ.get('DDM_NO_SAVE'))
    def _path(self,room,cookies):
        if not self.enabled or not isinstance(cookies,dict) or not cookies.get('SESSDATA'):return None
        identity=json.dumps([str(room),cookies['SESSDATA'],cookies.get('bili_jct','')],ensure_ascii=False)
        return self.root/(hashlib.sha256(identity.encode('utf-8')).hexdigest()+'.json')
    def load(self,room,cookies):
        path=self._path(room,cookies)
        if path is None:return None
        try:
            if path.stat().st_size>_MAX_BYTES:return None
            payload=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(payload,dict) or payload.get('version')!=1:return None
            saved=payload.get('saved_at')
            if type(saved) not in (int,float) or not 0<=time.time()-saved<=_MAX_AGE:return None
            return _packages(payload.get('packages'))
        except (OSError,ValueError,UnicodeError):return None
    def save(self,room,cookies,packages):
        path=self._path(room,cookies);clean=_packages(packages)
        if path is None or clean is None:return
        temporary=None
        try:
            data=json.dumps({'version':1,'saved_at':time.time(),'packages':clean},ensure_ascii=False,allow_nan=False).encode('utf-8')
            if len(data)>_MAX_BYTES:return
            self.root.mkdir(parents=True,exist_ok=True)
            handle,name=tempfile.mkstemp(prefix='.catalog-',suffix='.tmp',dir=self.root)
            temporary=Path(name)
            with os.fdopen(handle,'wb') as stream:stream.write(data)
            os.replace(temporary,path)
            files=sorted(self.root.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
            for old in files[_MAX_FILES:]:old.unlink(missing_ok=True)
        except (OSError,ValueError,TypeError):pass
        finally:
            if temporary is not None:
                try:temporary.unlink(missing_ok=True)
                except OSError:pass
