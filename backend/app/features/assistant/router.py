from fastapi import APIRouter, Request
from .auth import issue
router=APIRouter(prefix="/api/assistant",tags=["assistant"])

@router.post("/entry")
def entry(request:Request):
    return issue(request.app.state.pool,request.state.principal,request.state.space)
