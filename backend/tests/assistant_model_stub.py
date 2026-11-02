"""Deterministic local SSE model for integration tests; never contacts a provider."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        messages=data.get("messages",[])
        tool=next((m for m in reversed(messages) if m.get("role")=="tool"),None)
        if tool:
            delta={"role":"assistant","content":"已按当前权限读取已发布技能："+str(tool["content"])}
            finish="stop"
        else:
            delta={"role":"assistant","tool_calls":[{"index":0,"id":"call_department","type":"function",
                   "function":{"name":"department_skill_list","arguments":"{}"}}]}
            finish="tool_calls"
        self.send_response(200);self.send_header("Content-Type","text/event-stream");self.end_headers()
        chunks=[{"id":"synthetic","object":"chat.completion.chunk","created":0,"model":"department-test",
                 "choices":[{"index":0,"delta":delta,"finish_reason":None}]},
                {"id":"synthetic","object":"chat.completion.chunk","created":0,"model":"department-test",
                 "choices":[{"index":0,"delta":{},"finish_reason":finish}],
                 "usage":{"prompt_tokens":10,"completion_tokens":10,"total_tokens":20}}]
        try:
            for chunk in chunks:self.wfile.write(("data: "+json.dumps(chunk)+"\n\n").encode());self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n");self.wfile.flush()
        except BrokenPipeError: pass
ThreadingHTTPServer(("127.0.0.1",3190),Handler).serve_forever()
