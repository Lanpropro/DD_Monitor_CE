"""Immutable gift models, conservative room/bag normalization and HTTP reads."""
from copy import deepcopy
from dataclasses import dataclass, replace
import json
import time
from types import MappingProxyType
import requests
from .bili_api import HEADERS, api_result, resolve_room

BASE = 'https://api.live.bilibili.com'
GOLD_ENDPOINT = BASE + '/xlive/revenue/v1/gift/sendGold'
GOLD_MULTI_ENDPOINT = BASE + '/xlive/revenue/v2/gift/sendGoldMultiUser'
BAG_ENDPOINT = BASE + '/xlive/revenue/v1/gift/sendBag'
INTERACTIVE_ENDPOINT = BASE + '/xlive/revenue/v2/interactive_pay/send'
DIRECT_INTERACTIVE_SCENES = ('guard_gift','guard_attire')

@dataclass(frozen=True)
class GiftItem:
    key: str
    source: str
    gift_id: int
    name: str
    price: int
    gif_url: str
    image_url: str
    counts: tuple
    max_count: int
    allow_custom: bool
    disabled_reason: str
    bag_id: int = 0
    stock: int = 0
    expires_at: int = 0
    pay_type: str = 'send_gift'
    gift_scene: str = ''
    variants: tuple = ()
    gift_type: int = 0

    @property
    def payment_scene(self):
        return json.loads(self.gift_scene).get('scene','') if self.gift_scene else ''

@dataclass(frozen=True)
class GiftTab:
    key: str
    title: str
    items: tuple

@dataclass(frozen=True)
class GiftCatalog:
    tabs: tuple
    configs: object
    max_send_count: int

@dataclass(frozen=True)
class GiftTarget:
    room_id: str
    uid: int
    ruid: int

@dataclass(frozen=True)
class GiftResult:
    gift_key: str
    quantity: int
    payload: object

class GiftSendError(ValueError):
    def __init__(self, message, *, uncertain=False, login_required=False):
        super().__init__(message)
        self.uncertain = uncertain
        self.login_required = login_required

def _integer(value, default=None):
    if isinstance(value, bool) or not (isinstance(value,int) or isinstance(value,str) and value.isascii() and value.isdigit()):
        if default is not None:return default
        raise ValueError('礼物数值格式异常')
    return int(value)

def format_battery(raw):
    raw=_integer(raw)
    if raw<0:raise ValueError('余额不能为负数')
    whole, fraction=divmod(raw,100)
    return str(whole) if not fraction else f'{whole}.{fraction:02d}'.rstrip('0')

def _list(value):
    if value is None:return []
    if not isinstance(value,list) or any(not isinstance(x,dict) for x in value):
        raise ValueError('礼物列表格式异常')
    return value

def _configs(value):
    if isinstance(value,dict):value=value.get('list')
    return _list(value)

def _url(value):
    return value if isinstance(value,str) and value.startswith(('https://','http://')) else ''

def _reason(config, room_id, source):
    special=config.get('special') or {}
    if not isinstance(special,dict):return '未知礼物权限'
    if special.get('is_use',1) != 1:return str(special.get('tips') or '当前账号尚未解锁')
    if config.get('perm',1) != 1 or config.get('is_use',1) != 1:return '当前账号没有赠送权限'
    scene=config.get('gift_scene') or {}
    if not isinstance(scene,dict):return '无法识别此礼物流程'
    interactive=scene.get('pay_type')=='interactive_pay' and scene.get('scene') in DIRECT_INTERACTIVE_SCENES
    if scene.get('pay_type','send_gift')!='send_gift' and not interactive:
        return '暂不支持此购买流程'+(f"（{scene['scene']}）" if scene.get('scene') else '')
    if interactive and source=='bag':return '此礼物需要电池购买'
    try:
        flow_types=tuple(_integer(value) for value in
            (special.get('special_type',0),config.get('gift_type',0),config.get('type',0)))
    except ValueError:
        return '无法识别此礼物流程'
    special_type,gift_type,kind=flow_types
    # roomGiftList marks the ordinary fan-club light sign as special_type=3.
    # Its default_gift/send_gift path uses the same form as ordinary paid gifts.
    light_sign=(config.get('id',config.get('gift_id')) in (31164,34001) and special_type==3)
    attire=interactive and scene['scene']=='guard_attire' and special_type==15
    # Paid type-6 boxes without a special payment scene use the ordinary
    # gift sender in the official web client. Other blind-box scenes differ.
    blind=(gift_type==6 and source=='gold' and not interactive
           and scene.get('scene','') in ('','default_gift'))
    if gift_type==6 and not blind:
        return '暂不支持此盲盒流程'
    if config.get('interactive_pay') or gift_type and not blind or kind or special_type and not (light_sign or attire):
        return '暂不支持特殊礼物流程'
    bound=config.get('bind_roomid') or config.get('room_id') or 0
    if str(bound) not in ('0','',str(room_id)):return '仅限指定直播间'
    rule=config.get('rule')
    if source=='bag' and rule not in (None,'',0,{},[]):return '未知背包使用规则'
    return ''

def _item(config, key, room_id, max_count, *, source='gold', bag_id=0, stock=0, expires_at=0, now=0):
    gift_id=_integer(config.get('id',config.get('gift_id')),0)
    limit=_integer(config.get('max_send_limit',max_count),max_count)
    maximum=min(max_count,limit) if limit>0 else max_count
    if source=='bag':maximum=min(maximum,stock)
    counts=[]
    values=config.get('count_map')
    if values is None:values=[{'num':1}]
    if isinstance(values,dict):values=[{'num':k} for k in values]
    for value in values if isinstance(values,list) else []:
        count=_integer(value.get('num') if isinstance(value,dict) else value,0)
        if 0<count<=maximum and count not in counts:counts.append(count)
    reason=_reason(config,room_id,source)
    price=_integer(config.get('price'),-1)
    if not reason and (gift_id<=0 or price<0):reason='礼物资料不完整'
    if source=='gold' and config.get('coin_type')!='gold':
        source='unsupported';reason=reason or '暂不支持此支付方式'
    if source=='bag':
        if bag_id<=0 or stock<=0:reason=reason or '背包库存不足'
        if expires_at and expires_at<=now:reason=reason or '礼物已过期'
    custom=config.get('diy_count_map') in (1,True)
    # A single remaining bag item is explicitly supported. Ordinary purchases
    # must retain the server's quantity permissions, even when none fit.
    if not counts and maximum>0 and (custom or source=='bag' and stock==1):counts=[1]
    if not counts:reason=reason or '当前没有可用赠送数量'
    scene=config.get('gift_scene')
    return GiftItem(key,source,gift_id,str(config.get('name') or f'礼物 {gift_id}'),max(0,price),
        _url(config.get('gif')),_url(config.get('img_basic')) or _url(config.get('img_dynamic')),
        tuple(counts),maximum,custom and maximum>1,reason,
        bag_id,stock,expires_at,
        scene.get('pay_type','send_gift') if isinstance(scene,dict) else 'send_gift',
        json.dumps(scene,ensure_ascii=False,separators=(',',':')) if isinstance(scene,dict) else '',
        gift_type=_integer(config.get('gift_type',0),0))

def find_gift(tabs, key):
    return next((choice for tab in tabs for item in tab.items
        for choice in (item,*item.variants) if choice.key==key),None)

def _variants(parent, references, configs, room_id, maximum):
    items=[];seen={parent.gift_id}
    for row in _list(references):
        ident=_integer(row.get('gift_id'),0)
        if ident<=0 or ident in seen:continue
        seen.add(ident)
        config={**configs.get(ident,{}),'id':ident}
        # Children have their own price/counts; the room's payment route and
        # parent permission restrictions still apply to this group.
        if not config.get('gift_scene') and parent.gift_scene:
            config['gift_scene']=json.loads(parent.gift_scene)
        if row.get('alias'):config['name']=str(row['alias'])
        item=_item(config,f'{parent.key}:{ident}',room_id,maximum)
        reason=parent.disabled_reason or item.disabled_reason
        if row.get('locked'):reason=str(row.get('lock_tip') or '当前账号尚未解锁')
        items.append(replace(item,disabled_reason=reason))
    return tuple(items)

def normalize_catalog(data, room_id):
    if not isinstance(data,dict) or not isinstance(data.get('gift_data'),dict) or not isinstance(data.get('gift_config'),dict):
        raise ValueError('礼物列表格式异常')
    gifts=data['gift_data']; refs=gifts.get('room_gift_list')
    if not isinstance(refs,dict):raise ValueError('房间礼物列表格式异常')
    configs={}
    for row in (*_configs(data['gift_config'].get('base_config')), *_configs(data['gift_config'].get('room_config'))):
        ident=_integer(row.get('id',row.get('gift_id')),0)
        if ident>0:configs[ident]={**configs.get(ident,{}),**deepcopy(row)}
    maximum=_integer(gifts.get('max_send_gift'),5000)
    if maximum<=0:raise ValueError('房间赠送上限异常')
    groups=[('main','礼物',_list(refs.get('gold_list'))+_list(refs.get('silver_list')))]
    tabs=sorted(_list(gifts.get('tab_list')),key=lambda r:_integer(r.get('position'),0))
    for tab in tabs:groups.append((str(tab.get('tab_id')),str(tab.get('tab_name') or '礼物'),_list(tab.get('list'))))
    result=[]
    for key,title,rows in groups:
        items=[];seen=set()
        for row in sorted(rows,key=lambda r:_integer(r.get('position'),0)):
            ident=_integer(row.get('gift_id',row.get('id')),0)
            if ident<=0 or ident in seen:continue
            seen.add(ident)
            merged={**configs.get(ident,{}),**row,'id':ident}
            item=_item(merged,f'{key}:{ident}',room_id,maximum)
            items.append(replace(item,variants=_variants(item,merged.get('upgrade_gift'),configs,room_id,maximum)))
        result.append(GiftTab(key,title,tuple(items)))
    return GiftCatalog(tuple(result),MappingProxyType(configs),maximum)

def normalize_bag(data, catalog, room_id, *, now):
    if not isinstance(data,dict):raise ValueError('背包列表格式异常')
    configs=dict(catalog.configs) if catalog else {}
    for row in _configs(data.get('gift_config')):
        ident=_integer(row.get('id',row.get('gift_id')),0)
        configs[ident]={**configs.get(ident,{}),**row}
    items=[];seen=set()
    for row in _list(data.get('list')):
        bag_id=_integer(row.get('bag_id'),0)
        if bag_id in seen:continue
        seen.add(bag_id)
        ident=_integer(row.get('gift_id'),0)
        merged={**configs.get(ident,{}),**row,'id':ident}
        stock=_integer(row.get('gift_num',row.get('num')),0)
        expiry=_integer(row.get('expire_at',row.get('expire_time',0)),0)
        items.append(_item(merged,f'bag:{bag_id}',room_id,catalog.max_send_count if catalog else 5000,
            source='bag',bag_id=bag_id,stock=stock,expires_at=expiry,now=now))
    return GiftTab('bag','背包',tuple(items))

def _read(path, cookies, **params):
    response=requests.get(BASE+path,params=params,headers=HEADERS,cookies=dict(cookies),timeout=10)
    data=api_result(response).get('data')
    if not isinstance(data,dict):raise ValueError('礼物接口返回格式异常')
    return data

def get_catalog(room_id, *, cookies):
    return normalize_catalog(_read('/xlive/web-room/v1/giftPanel/roomGiftList',cookies,
        room_id=str(room_id),platform='pc',source='live'),room_id)

def get_wallet(*, cookies):
    raw=_integer(_read('/pay/v2/Pay/myWallet',cookies).get('gold'))
    if raw<0:raise ValueError('余额格式异常')
    return raw

def get_bag(room_id, catalog, *, cookies):
    return normalize_bag(_read('/xlive/web-room/v1/gift/bag_list',cookies,room_id=str(room_id)),
        catalog,room_id,now=int(time.time()))

def prepare_target(room_id, *, cookies):
    if not cookies.get('SESSDATA') or not cookies.get('bili_jct'):
        raise GiftSendError('请重新登录 B 站后赠送礼物',login_required=True)
    real_id, anchor=resolve_room(room_id,cookies=cookies)
    response=requests.get('https://api.bilibili.com/x/web-interface/nav',headers=HEADERS,cookies=dict(cookies),timeout=10)
    data=api_result(response).get('data') or {}
    uid=_integer(data.get('mid'),0)
    if uid<=0:raise GiftSendError('无法确认当前账号')
    return GiftTarget(real_id,uid,anchor)

def validate_send(item, quantity, *, cookies, wallet):
    if not cookies.get('SESSDATA') or not cookies.get('bili_jct'):
        raise GiftSendError('请重新登录 B 站后赠送礼物',login_required=True)
    if type(quantity) is not int or quantity<=0 or quantity>item.max_count:
        raise GiftSendError('赠送数量超出限制')
    if not item.allow_custom and quantity not in item.counts:
        raise GiftSendError('此礼物不支持该数量')
    if item.disabled_reason or item.source not in ('gold','bag'):
        raise GiftSendError(item.disabled_reason or '暂不支持此礼物流程')
    if item.gift_type==6 and (item.source!='gold' or item.pay_type!='send_gift'
                             or item.payment_scene not in ('','default_gift')):
        raise GiftSendError('暂不支持此盲盒流程')
    if item.pay_type not in ('send_gift','interactive_pay'):
        raise GiftSendError('暂不支持此购买流程')
    if item.pay_type=='interactive_pay' and (item.source!='gold' or item.payment_scene not in DIRECT_INTERACTIVE_SCENES):
        raise GiftSendError('暂不支持此礼物流程')
    if item.gift_id<=0 or item.price<0:raise GiftSendError('礼物资料无效')
    if item.source=='bag':
        if item.bag_id<=0 or quantity>item.stock:raise GiftSendError('该背包批次库存不足')
        if item.expires_at and item.expires_at<=int(time.time()):raise GiftSendError('礼物已过期')
    elif type(wallet) is not int or wallet<item.price*quantity:
        raise GiftSendError('余额未知，请刷新' if wallet is None else '电池余额不足')

def send_gift(target,item,quantity,*,cookies,wallet,still_current):
    validate_send(item,quantity,cookies=cookies,wallet=wallet)
    if (not str(target.room_id).isdigit() or int(target.room_id)<=0 or target.uid<=0 or target.ruid<=0):
        raise GiftSendError('房间或账号信息无效')
    if not still_current():raise GiftSendError('房间或账号已改变，已取消赠送')
    form={'uid':target.uid,'gift_id':item.gift_id,'gift_num':quantity,'price':item.price,
        'platform':'pc','csrf':cookies['bili_jct'],'csrf_token':cookies['bili_jct']}
    if item.pay_type=='interactive_pay':
        # The official guard gift/attire sender uses this route, not sendGold.
        ip=_read('/xlive/web-room/v1/index/getIpInfo',cookies).get('addr') or ''
        if not isinstance(ip,str):raise GiftSendError('无法确认赠送网络信息')
        endpoint=INTERACTIVE_ENDPOINT
        form.update(gift_scene=item.gift_scene,context_id=target.room_id,room_id=target.room_id,
            receiver_uid=target.ruid,anchor_id=target.ruid,context_type=1,remote_ip=ip,web_location='444.8')
    else:
        form.update(ruid=target.ruid,biz_id=target.room_id,biz_code='live',send_ruid=0,storm_beat_id=0)
        if item.source=='bag':
            endpoint=BAG_ENDPOINT;form['bag_id']=item.bag_id
        elif item.gift_type==6:
            # The current web sender submits the box ID/price, with one
            # explicit receiver. Award IDs/values never determine the charge.
            endpoint=GOLD_MULTI_ENDPOINT
            form.update(coin_type='gold',bag_id=0,biz_code='Live',
                receive_users=json.dumps([{'uid':target.ruid}],separators=(',',':')),
                all_flag=0,web_location='444.8')
        else:
            endpoint=GOLD_ENDPOINT;form.update(coin_type='gold',bag_id=0,rnd=int(time.time()),visit_id='')
    if not still_current():raise GiftSendError('房间或账号已改变，已取消赠送')
    # Exactly one form request; redirects and library-level retries stay disabled.
    try:
        response=requests.post(endpoint,data=form,cookies=dict(cookies),headers={**HEADERS,
            'Origin':'https://live.bilibili.com','Referer':f'https://live.bilibili.com/{target.room_id}'},
            timeout=10,allow_redirects=False)
        if not 200<=response.status_code<300:
            raise GiftSendError('赠送结果未确认，请先检查余额与背包',uncertain=True)
        payload=response.json()
        if not isinstance(payload,dict) or type(payload.get('code')) is not int:
            raise GiftSendError('赠送结果未确认，请先检查余额与背包',uncertain=True)
        reason=payload.get('message') or payload.get('msg')
        success_message=reason in (None,'',0,'0') or isinstance(reason,str) and reason.lower() in ('success','ok')
        if payload['code']!=0 or not success_message:
            raise GiftSendError(str(reason or '服务器拒绝赠送'),login_required=payload['code'] in (-101,-111))
    except GiftSendError:raise
    except Exception as error:
        raise GiftSendError('赠送结果未确认，请先检查余额与背包，不要重复点击',uncertain=True) from error
    return GiftResult(item.key,quantity,MappingProxyType(deepcopy(payload)))
