"""One account-wide submission reservation and revisioned independent reads."""
from dataclasses import dataclass, replace
from PySide6.QtCore import QObject, Signal, Slot
from . import gift_api as api
from .workers import Request, start_worker, request_message

@dataclass(frozen=True)
class GiftPanelState:
    tabs: tuple = ()
    wallet: int | None = None
    wallet_valid: bool = True
    catalog_error: str = ''
    wallet_error: str = ''
    bag_error: str = ''
    loading: frozenset = frozenset()
    sending: bool = False
    feedback: str = ''

    @property
    def spendable_wallet(self):
        # Keep the displayed value even when an uncertain POST needs a fresh read.
        return self.wallet if self.wallet_valid else None

class GiftCoordinator(QObject):
    completed = Signal(object,object,object)
    busyChanged = Signal(bool)
    invalidated = Signal(int,object,object)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.revision=0
        self._worker=None
        self._token=None
        self._debit=0
        self._result=self._error=None

    @property
    def busy(self):return self._worker is not None

    def submit(self,worker,token,*,debit):
        if self.busy:return False
        self._worker,self._token,self._debit=worker,token,debit
        self._result=self._error=None
        worker.completed.connect(self._success)
        worker.failed.connect(self._failure)
        worker.finished.connect(self._finished)
        self.busyChanged.emit(True)
        start_worker(worker)
        return True

    @Slot(object,object)
    def _success(self,context,result):self._result=result
    @Slot(object,object)
    def _failure(self,context,error):self._error=error
    @Slot()
    def _finished(self):
        # Release only after the actual thread ends, even if its view vanished.
        result,error,token,debit=self._result,self._error,self._token,self._debit
        self._worker=self._token=None
        self._debit=0
        if result is not None or getattr(error,'uncertain',False):
            self.revision+=1
            # The reservation owns the captured cost even if the sending tile
            # closed or switched rooms before the confirmed response arrived.
            self.invalidated.emit(self.revision,token,debit if result is not None else None)
        self.busyChanged.emit(False)
        self.completed.emit(token,result,error)

class GiftController(QObject):
    stateChanged = Signal(object)
    sent = Signal(object)
    failed = Signal(str,bool)
    errorRaised = Signal(object,bool)

    def __init__(self,session,coordinator,parent=None):
        super().__init__(parent)
        self.session,self.coordinator=session,coordinator
        self.state=GiftPanelState(sending=coordinator.busy)
        self._room='';self._snapshot=None;self._serial=0;self._closed=False
        self._reads={};self._send=None;self._catalog=None;self._active=False
        self._read_id=0;self._revision=coordinator.revision;self._bag_valid=False;self._wallet_fresh=False
        coordinator.busyChanged.connect(self._busy)
        coordinator.invalidated.connect(self._invalidate)
        coordinator.completed.connect(self._submission_done)

    def _update(self,**changes):
        self.state=replace(self.state,**changes)
        if not self._closed:self.stateChanged.emit(self.state)

    def set_context(self,room_id,snapshot):
        if self._closed:return
        identity=(str(room_id or ''),snapshot.generation if snapshot else 0)
        current=(self._room,self._snapshot.generation if self._snapshot else 0)
        self._snapshot=snapshot
        if identity==current:return
        self._serial+=1;self._room=identity[0]
        for worker in tuple(self._reads.values()):worker.cancel()
        self._reads.clear()
        if self._send:self._send.cancel()
        self._catalog=None;self._bag_valid=False;self._wallet_fresh=False
        self.state=GiftPanelState(sending=self.coordinator.busy)
        self.stateChanged.emit(self.state)

    def set_active(self,active):self._active=bool(active)

    def load(self,force=False):
        if self._closed or not self._room or not self._snapshot:return
        self._active=True
        if force:
            for worker in tuple(self._reads.values()):worker.cancel()
            self._reads.clear()
        kinds=[]
        if force or self._catalog is None:kinds.append('catalog')
        if force or not self._wallet_fresh:kinds.append('wallet')
        if force or not self._bag_valid:kinds.append('bag')
        self._load_kinds(kinds)

    def _load_kinds(self,kinds):
        for kind in kinds:
            if kind in self._reads:continue
            snapshot=self._snapshot;room=self._room;catalog=self._catalog
            if not snapshot:continue
            self._read_id+=1
            context=(self._serial,kind,self._revision,self._read_id)
            if kind=='catalog':operation=lambda c,r=room:api.get_catalog(r,cookies=c)
            elif kind=='wallet':operation=lambda c:api.get_wallet(cookies=c)
            else:operation=lambda c,r=room,cat=catalog:api.get_bag(r,cat,cookies=c)
            worker=Request(context,operation,cookies=snapshot.values,account_generation=snapshot.generation)
            self._reads[kind]=worker
            worker.completed.connect(self._read_done)
            worker.failed.connect(self._read_failed)
            self._update(loading=frozenset(self._reads))
            start_worker(worker)

    def _current_read(self,context):
        serial,kind,revision,ident=context
        worker=self._reads.get(kind)
        return (not self._closed and serial==self._serial and worker is not None and worker.context==context
                and (kind=='catalog' or revision==self._revision))

    @Slot(object,object)
    def _read_done(self,context,result):
        if not self._current_read(context):return
        kind=context[1];self._reads.pop(kind,None)
        changes={kind+'_error':'','loading':frozenset(self._reads)}
        if kind=='catalog':
            self._catalog=result
            changes['tabs']=result.tabs+tuple(t for t in self.state.tabs if t.key=='bag')
        elif kind=='bag':
            self._bag_valid=True
            changes['tabs']=tuple(t for t in self.state.tabs if t.key!='bag')+(result,)
        else:
            self._wallet_fresh=True
            changes.update(wallet=result,wallet_valid=True)
        self._update(**changes)

    @Slot(object,object)
    def _read_failed(self,context,error):
        if not self._current_read(context):return
        kind=context[1];self._reads.pop(kind,None)
        self._update(**{kind+'_error':request_message(error),'loading':frozenset(self._reads)})
        self.errorRaised.emit(error,False)

    def send(self,gift_key,quantity):
        if self._closed or self.coordinator.busy:return
        item=api.find_gift(self.state.tabs,gift_key)
        if item is None:return
        snapshot=self._snapshot
        try:api.validate_send(item,quantity,cookies=snapshot.values if snapshot else {},wallet=self.state.spendable_wallet)
        except api.GiftSendError as error:
            self._update(feedback=str(error));self.errorRaised.emit(error,True);self.failed.emit(str(error),False);return
        serial=self._serial;room=self._room;wallet=self.state.spendable_wallet
        token=(id(self),serial,snapshot.generation)
        def operation(cookies):
            target=api.prepare_target(room,cookies=cookies)
            return api.send_gift(target,item,quantity,cookies=cookies,wallet=wallet,still_current=worker.still_current)
        worker=Request(token,operation,cookies=snapshot.values,account_generation=snapshot.generation,require_device=True)
        worker.deviceReady.connect(self.session.publish_device)
        self._send=worker
        self._update(feedback='正在赠送…')
        self.coordinator.submit(worker,token,debit=item.price*quantity if item.source=='gold' else 0)

    @Slot(bool)
    def _busy(self,busy):
        if not self._closed:self._update(sending=busy)

    @Slot(int,object,object)
    def _invalidate(self,revision,token,debit):
        if self._closed:return
        # A completion from an earlier account cannot mutate the new account.
        if not self._snapshot or token[2]!=self._snapshot.generation or revision<=self._revision:return
        # Revisions affect only this account context; another account's late POST
        # must not discard valid reads that are already in progress here.
        self._revision=revision;self._bag_valid=False;self._wallet_fresh=False
        for kind in ('wallet','bag'):
            worker=self._reads.pop(kind,None)
            if worker:worker.cancel()
        tabs=tuple(t for t in self.state.tabs if t.key!='bag')+(api.GiftTab('bag','背包',()),)
        wallet=self.state.wallet
        if debit is not None and wallet is not None:wallet=max(0,wallet-debit)
        self._update(wallet=wallet,wallet_valid=self.state.wallet_valid and debit is not None,
                     tabs=tabs,loading=frozenset(self._reads))
        if self._active:self._load_kinds(('wallet','bag'))

    @Slot(object,object,object)
    def _submission_done(self,token,result,error):
        if self._closed or token[0]!=id(self) or token[1]!=self._serial:return
        self._send=None
        if result is not None:
            self._update(feedback='');self.sent.emit(result)
        elif error is not None:
            message=request_message(error,sending=True)
            self._update(feedback=message);self.errorRaised.emit(error,True);self.failed.emit(message,bool(getattr(error,'uncertain',False)))
        else:self._update(feedback='')

    def shutdown(self):
        if self._closed:return
        self._closed=True;self._serial+=1;self._active=False
        for worker in tuple(self._reads.values()):worker.cancel()
        self._reads.clear()
        if self._send:self._send.cancel()
