from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel
from typing import Optional
from app.client import supabase
from app.logger import setup_logger
from datetime import datetime
from uuid import UUID
from app.auth import get_user_id_by_token # 根据token获取user_id
from app.config import settings
# --------------- 初始化 ----------------
logger = setup_logger(__name__)
# 初始化 FastAPI 路由器
router = APIRouter(tags=["todo"])

# ------------------ 参数管理 --------------------------
# True: 用户可以看所有人的数据, False: 用户只能看自己的数据
ALLOW_ALL_USERS = settings.ALLOW_ALL_USERS  
# 根据ALLOW_ALL_USERS去确认是否需要user_id
def get_user_id_header(authorization: str = Header(...)):
    if ALLOW_ALL_USERS:
        return None
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="无效的授权头")
    token = authorization.replace("Bearer ", "")
    return get_user_id_by_token(token)

# -------------------- 数据模型定义 --------------------
class TodoModel(BaseModel):
    id: Optional[UUID] = None
    title: str
    priority: Optional[str] = None  # 例如 high / medium / low
    status: Optional[str] = None    # 例如 pending / completed
    due_date: Optional[datetime] = None  # ISO 格式的日期字符串

# -------------------- API 接口 --------------------
# 获取所有todo
@router.get("/todos")
def get_todos(user_id: str = Depends(get_user_id_header)):
    """
    获取待办事项，根据配置决定是否筛选用户
    """
    try:
        query = supabase.table("todo_items").select("*")
        if not ALLOW_ALL_USERS:
            query = query.eq("user_id", user_id)
        response = query.execute()
        return {"todos": response.data}
    except Exception as e:
        logger.error(f"获取待办事项失败: {str(e)}")
        raise HTTPException(status_code=500, detail="无法获取待办事项")
# 新增todo
@router.post("/todos")
def create_todo(todo: TodoModel, user_id: str = Depends(get_user_id_header)):
    """
    创建待办事项，始终关联到用户
    """
    try:
        logger.debug(f"接收到的 user_id: {user_id}")  # 添加日志记录 user_id
        if ALLOW_ALL_USERS:
            user_id = None  # 明确设置为 None

        if todo.due_date:
            try:
                todo.due_date = todo.due_date.isoformat()
            except Exception:
                raise HTTPException(status_code=400, detail="无效的日期格式，应为 ISO 8601 格式")

        new_todo = {
            "title": todo.title,
            "priority": todo.priority,
            "status": todo.status,
            "due_date": todo.due_date,
            "user_id": user_id if not ALLOW_ALL_USERS else None
        }
        logger.debug(f"创建待办事项数据: {new_todo}")  # 添加调试日志
        response = supabase.table("todo_items").insert(new_todo).execute()
        logger.debug(f"Supabase 响应: {response}")
        if not response.data:
            raise HTTPException(status_code=400, detail="创建失败，可能是数据不符合约束条件")
        return {"todo": response.data[0]}
    except Exception as e:
        logger.error(f"创建失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建待办事项失败: {str(e)}")
# 更新todo
@router.patch("/todos/{todo_id}")
def update_todo(todo_id: UUID, todo: TodoModel, user_id: str = Depends(get_user_id_header)):
    """
    更新待办事项，根据配置决定是否筛选用户
    """
    try:
        updates = {
            k: (v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, UUID) else v)
            for k, v in todo.model_dump().items() if v is not None
        }
        if not updates:
            raise HTTPException(status_code=400, detail="无更新内容")

        query = supabase.table("todo_items").update(updates).eq("id", str(todo_id))
        if not ALLOW_ALL_USERS:
            query = query.eq("user_id", user_id)
        response = query.execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="未找到待办事项")
        return {"todo": response.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")
# 删除todo
@router.delete("/todos/{todo_id}")
def delete_todo(todo_id: UUID, user_id: str = Depends(get_user_id_header)):
    """
    删除待办事项，根据配置决定是否筛选用户
    """
    try:
        query = supabase.table("todo_items").delete().eq("id", str(todo_id))
        if not ALLOW_ALL_USERS:
            query = query.eq("user_id", user_id)
        response = query.execute()

        if response.data:
            return {"status": "success", "deleted": response.data[0]}
        else:
            raise HTTPException(status_code=404, detail="待办事项不存在")
    except Exception as e:
        logger.error(f"删除失败: {str(e)}")
        raise HTTPException(status_code=500, detail="删除失败")
# 同步todo
@router.post("/todos/batch")
def sync_todos(todos: list[TodoModel], user_id: str = Depends(get_user_id_header)):
    """
    批量同步待办事项，始终关联到用户
    """
    try:
        results = []
        for todo in todos:
            new_todo = {
                "title": todo.title,
                "priority": todo.priority,
                "status": todo.status,
                "due_date": todo.due_date.isoformat() if todo.due_date else None,
                "user_id": user_id if not ALLOW_ALL_USERS else None
            }
            response = supabase.table("todo_items").upsert(new_todo, on_conflict=["id"]).execute() # 修改 on_conflict 参数为 id
            results.append(response.data)

        logger.info(f"批量同步成功: {len(results)} 条待办事项")
        logger.debug(f"同步的待办事项详情: {results}") # 添加调试日志，避免敏感信息泄露
        return {"status": "success", "synced": len(results)}
    except Exception as e:
        logger.error(f"批量同步失败: {str(e)}")
        raise HTTPException(status_code=500, detail="批量同步失败")
