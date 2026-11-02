"""Exercise production Manager with synthetic workloads, shortened idle only."""
from dataclasses import replace
from app.features.assistant.runtime import Manager
class IntegratedPool(Manager):
    def __init__(self,*args):
        super().__init__(*args);self.peak=0
    @property
    def slots(self):return self.limits.capacity
    @slots.setter
    def slots(self,v):self.limits=replace(self.limits,capacity=v)
    @property
    def idle(self):return self.limits.idle_seconds
    @idle.setter
    def idle(self,v):self.limits=replace(self.limits,idle_seconds=v)
    def _dispatch(self):
        super()._dispatch();self.peak=max(self.peak,len(self.items))
    async def request(self,p,space,name,args):
        from assistant_pool_probe import rpc
        async with self.lease(p,space) as r:return await rpc(r,name,args)

