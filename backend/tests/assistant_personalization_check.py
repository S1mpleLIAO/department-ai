"""No live services: personal configuration guards and DNS pinning regression."""
import asyncio
from unittest.mock import patch
import httpcore
from fastapi import HTTPException
from app.features.assistant.policy import rpc
from app.features.assistant.personal_models import PublicNetwork,public_url,public_client

def invoke(method,args):
    return rpc(method,{"type":"client-request","method":method,"payload":{"args":args}},["managed"])
def deny(method,args):
    try:invoke(method,args)
    except HTTPException as e:assert e.status_code==403;return
    raise AssertionError((method,args))
def mutate(path,value=None,op="set"):
    item={"op":op,"path":path}
    if op=="set":item["value"]=value
    return {"ns":"llm-pi-ai","ops":[item]}
for preset in ("department","standard"):
    invoke("session/create",{"request":{"cwd":"/home/assistant/workspace","agentPreset":preset}})
    invoke("agentPresets/select",{"agentId":"session-test","agentPreset":preset})
deny("session/create",{"request":{"agentPreset":"cordis"}})
deny("session/create",{"request":{"cwd":"/etc"}})
deny("settings/update",{"ns":"permission","patch":{"defaultPreset":"danger-full-access"}})
for address in ("http://127.0.0.1","http://169.254.169.254","http://10.0.0.1","http://[::1]","file:///etc/passwd","https://x:y@public.example"):
    deny("settings/mutate",mutate(["providers","mine","baseURL"],address))
invoke("settings/mutate",mutate(["providers","mine"],{"api":"openai-completions","baseURL":"https://example.com/v1","apiKeyEnv":"MINE_API_KEY","models":[{"id":"model"}]}))
invoke("settings/mutate",mutate(["providers","mine"],op="unset"))
deny("settings/mutate",mutate(["providers","department"],{}))
deny("settings/mutate",mutate(["providers"],{}))
deny("settings/mutate",mutate(["providers","mine","apiKeyEnv"],"DEPARTMENT_LOCAL_MODEL"))
invoke("credentials/set",{"ref":"MINE_API_KEY","value":"synthetic"})
invoke("credentials/unset",{"ref":"MINE_API_KEY"})
deny("credentials/set",{"ref":"DEPARTMENT_LOCAL_MODEL","value":"synthetic"})
deny("agentPresets/select",{"agentId":"session-test","agentPreset":"../other"})
deny("settings/update",{"ns":"agent-presets","patch":{"roots":[]}})
invoke("$events/result",{"clientId":"client-test","eventId":"event-test","outcome":{"kind":"next"}})
deny("$events/result",{"clientId":"client-test","eventId":"event-test","outcome":{"kind":"execute"}})
async def network():
    loop=asyncio.get_running_loop()
    for ip in ("127.0.0.1","169.254.169.254","10.0.0.2","::1"):
        async def resolve(*args,**kwargs):return [(2,1,6,"",(ip,443))]
        with patch.object(loop,"getaddrinfo",resolve):
            try:await PublicNetwork().connect_tcp("public.example",443)
            except httpcore.ConnectError:pass
            else:raise AssertionError("DNS rebinding allowed")
    calls=[]
    async def resolve(*args,**kwargs):return [(2,1,6,"",("1.1.1.1",443))]
    async def connect(self,host,*args):calls.append(host);return "stream"
    from httpcore._backends.auto import AutoBackend
    with patch.object(loop,"getaddrinfo",resolve),patch.object(AutoBackend,"connect_tcp",connect):
        assert await PublicNetwork().connect_tcp("public.example",443)=="stream"
    assert calls==["1.1.1.1"]
    async with public_client():pass
asyncio.run(network())
print("PASS personal config CRUD guards, preset allowlist, managed credential protection, private IP/DNS denial and pinned connect")

invoke("commands/execute",{"agentId":"session-test","line":"/compact","submittedAttachments":[]})
for command in ("/permission danger-full-access","/compact extra","/feedback", " /compact"):
    deny("commands/execute",{"agentId":"session-test","line":command,"submittedAttachments":[]})
deny("commands/execute",{"agentId":"session-test","line":"/compact","submittedAttachments":[{}]})
print("PASS manual compaction only; permission/other commands and attachments denied")
